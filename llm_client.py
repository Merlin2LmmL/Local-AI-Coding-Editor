"""
LLM client — dual-model pipeline (Planner + Executor) via Ollama.

Architecture:
  1. Gemma 4 (planner) receives the user request and creates a strict
     step-by-step plan.  (Optional — can be disabled or auto-detected.)
  2. Qwen 3 Coder (executor) receives each plan step as a concrete task
     and executes it using tool calls.
  3. After all steps, a build/deploy verification loop runs.  The executor
     re-attempts fixes until the build succeeds or the retry limit is hit.

When planning is disabled or the request is deemed simple, the executor
receives the full user request directly — no planner round-trip.
"""
import json
import re
from typing import Any, Callable

import ollama


# ── Low-level Ollama helpers ────────────────────────────────────────────

def chat_ollama(
    messages: list[dict],
    model: str,
    tools: list | None = None,
) -> tuple[str, list[dict] | None]:
    """
    Single-turn Ollama chat.
    Returns (content, tool_calls_or_None).
    """
    kwargs: dict[str, Any] = {"model": model, "messages": messages}
    if tools:
        kwargs["tools"] = tools

    response = ollama.chat(**kwargs)
    message = response.message
    content = message.content or ""

    raw_tool_calls = getattr(message, "tool_calls", None)
    if raw_tool_calls:
        parsed: list[dict] = []
        for tc in raw_tool_calls:
            fn = tc.function
            parsed.append({
                "name": fn.name,
                "arguments": dict(fn.arguments) if fn.arguments else {},
            })
        return content, parsed

    # Fallback parser for Qwen's raw XML tool call format if native parsing fails
    if tools and not raw_tool_calls and "<function=" in content:
        parsed = []
        # Match <function=name>...</function> (or up to end of string if truncated)
        func_pattern = re.compile(r"<function=([^>]+)>(.*?)(?:</function>|$)", re.DOTALL)
        for match in func_pattern.finditer(content):
            name = match.group(1).strip()
            args_text = match.group(2)
            args = {}
            
            # Match <parameter=key>value</parameter>
            param_pattern = re.compile(r"<parameter=([^>]+)>(.*?)(?:</parameter>|$)", re.DOTALL)
            for p_match in param_pattern.finditer(args_text):
                p_name = p_match.group(1).strip()
                p_val = p_match.group(2).strip()
                args[p_name] = p_val
                
            parsed.append({"name": name, "arguments": args})
            
        # Clean up the raw XML from the content so it doesn't show in UI
        clean_content = func_pattern.sub("", content).strip()
        
        if parsed:
            return clean_content, parsed

    return content, None


# ── Chat-history optimisation ───────────────────────────────────────────

def trim_history(
    history: list[dict],
    max_turns: int = 20,
    summariser_model: str = "gemma4:31b",
) -> list[dict]:
    """
    Keep the conversation context lean.

    * Recent `max_turns` user/assistant pairs are kept verbatim.
    * Older turns are compressed into a single summary message so the
      model still has context without burning the whole context window.
    * Tool-result messages that are very long get truncated.
    """
    # Truncate large tool results everywhere
    compacted: list[dict] = []
    for msg in history:
        if msg.get("role") == "tool" and len(msg.get("content", "")) > 2000:
            compacted.append({**msg, "content": msg["content"][:2000] + "\n...(truncated)"})
        else:
            compacted.append(msg)

    # Count user/assistant turn pairs (ignore system/tool)
    turn_indices: list[int] = []
    for idx, msg in enumerate(compacted):
        if msg.get("role") == "user":
            turn_indices.append(idx)

    if len(turn_indices) <= max_turns:
        return compacted

    # Split into old (to summarise) and recent (to keep)
    cutoff_index = turn_indices[-max_turns]
    old_messages = compacted[:cutoff_index]
    recent_messages = compacted[cutoff_index:]

    if not old_messages:
        return recent_messages

    # Build a lightweight summary of old context
    summary_prompt = (
        "Summarise the following conversation history in ≤150 words. "
        "Focus on: what the user asked for, what was done, what files were "
        "changed, and any unresolved issues.\n\n"
    )
    for msg in old_messages:
        role = msg.get("role", "?")
        content = msg.get("content", "")[:500]
        if role in ("user", "assistant"):
            summary_prompt += f"[{role}]: {content}\n"

    try:
        summary, _ = chat_ollama(
            [{"role": "user", "content": summary_prompt}],
            model=summariser_model,
        )
    except Exception:
        # If summarisation fails, just keep a naive truncation
        summary = "(previous conversation context unavailable)"

    context_message = {
        "role": "system",
        "content": f"[Earlier conversation summary]\n{summary}",
    }
    return [context_message] + recent_messages


# ── Planner (Gemma 4) ──────────────────────────────────────────────────

PLANNER_SYSTEM = (
    "You are a task planner. Given a user request, produce a numbered list "
    "of concrete coding steps.\n"
    "CRITICAL RULES:\n"
    "- Preserve ALL user constraints and preferences EXACTLY (e.g. 'single file', "
    "'no dependencies', 'no CSS', specific language/framework choices).\n"
    "- Do NOT add steps that contradict user instructions.\n"
    "- Do NOT split work into multiple files unless the user explicitly asks for it.\n"
    "- Do NOT add abstraction, modularity, or test steps the user did not request.\n"
    "- Each step must be a single, actionable instruction.\n"
    "- Include a final verification step (e.g. run build/tests) ONLY if applicable.\n"
    "- Output ONLY the numbered list — no commentary, no code."
)


def create_plan(
    user_request: str,
    conversation_summary: str,
    planner_model: str = "gemma4:31b",
) -> list[str]:
    """Ask the planner model to produce a step-by-step plan."""
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM},
    ]
    if conversation_summary:
        messages.append({
            "role": "system",
            "content": f"[Context from earlier conversation]\n{conversation_summary}",
        })
    messages.append({"role": "user", "content": user_request})

    raw_plan, _ = chat_ollama(messages, model=planner_model)

    # Parse numbered lines
    steps: list[str] = []
    for line in raw_plan.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Accept lines starting with a digit, or "- " bullets
        if stripped[0].isdigit() or stripped.startswith("- "):
            # Remove leading number/bullet
            clean = stripped.lstrip("0123456789.-) ").strip()
            if clean:
                steps.append(clean)

    # Fallback: if parsing yielded nothing, use the whole response as one step
    if not steps:
        steps = [raw_plan.strip()]

    return steps


# ── Complexity heuristic ────────────────────────────────────────────────

# Keywords / patterns that signal a request is complex enough to plan
_COMPLEX_KEYWORDS = [
    # Multi-step signals
    "and then", "after that", "followed by", "next ", "also ",
    "first ", "then ", "finally ",
    # Architectural / large-scope work
    "refactor", "migrate", "redesign", "restructure", "rewrite",
    "implement", "integrate", "architecture", "overhaul",
    # Multi-file signals
    "multiple files", "across the", "all files", "project-wide",
    "entire codebase", "every file",
    # Explicit planning
    "step by step", "plan ", "create a plan",
]

_COMPLEX_PATTERNS = re.compile(
    r"(?:" + "|".join(re.escape(kw) for kw in _COMPLEX_KEYWORDS) + r")",
    re.IGNORECASE,
)


def should_use_planner(user_request: str) -> bool:
    """
    Heuristic: return True if the request looks complex enough to benefit
    from a separate planning step.

    Checks:
      - Request length (>300 chars → likely detailed / multi-part)
      - Presence of multi-step or architectural keywords
      - Multiple sentences (rough proxy for multi-part requests)
    """
    text = user_request.strip()

    # Very short requests are almost never complex
    if len(text) < 60:
        return False

    # Long requests are usually complex
    if len(text) > 300:
        return True

    # Keyword / pattern match
    if _COMPLEX_PATTERNS.search(text):
        return True

    # Multiple sentences (3+) suggest multi-part work
    sentence_count = len(re.split(r'[.!?]+', text))
    if sentence_count >= 4:
        return True

    return False


# ── Executor (Qwen 3 Coder) ────────────────────────────────────────────

EXECUTOR_SYSTEM = (
    "You are a precise code executor. You receive a task that is part of a "
    "larger user request. You MUST follow the user's original instructions "
    "and constraints exactly — never contradict them. Complete the task using "
    "the available tools. Do NOT ask clarifying questions. Do NOT split into "
    "multiple files unless explicitly instructed. Implement the change, then "
    "confirm what you did in ≤2 sentences."
)


def execute_step(
    task: str,
    coder_model: str,
    tools: list,
    execute_tool_fn: Callable,
    on_tool_call: Callable | None = None,
    on_tool_result: Callable | None = None,
    original_request: str = "",
    cancel_flag: Callable | None = None,
) -> str:
    """
    Run one plan step through the coder model with tool calling.
    Returns the coder's final text response.
    """
    # Build the user message — include original request as context
    if original_request:
        user_content = (
            f"Original user request: \"{original_request}\"\n\n"
            f"Current task: {task}"
        )
    else:
        user_content = task

    messages: list[dict] = [
        {"role": "system", "content": EXECUTOR_SYSTEM},
        {"role": "user", "content": user_content},
    ]
    max_iterations = 15
    full_response = ""

    for _ in range(max_iterations):
        if cancel_flag and cancel_flag():
            return full_response + "\n(cancelled)"
        content, tool_calls = chat_ollama(messages, model=coder_model, tools=tools)

        if content:
            full_response += content

        if not tool_calls:
            break

        for tc in tool_calls:
            name = tc.get("name", "unknown")
            args = tc.get("arguments", {})

            if on_tool_call:
                on_tool_call(name, args)

            try:
                result = execute_tool_fn(name, args)
                if on_tool_result:
                    on_tool_result(name, result, True)
            except Exception as exc:
                result = f"Error: {exc}"
                if on_tool_result:
                    on_tool_result(name, result, False)

            messages.append({
                "role": "assistant",
                "content": content or "",
                "tool_calls": [{"function": {"name": name, "arguments": args}}],
            })
            messages.append({"role": "tool", "content": result})

    return full_response


# ── Debug / verification loop ──────────────────────────────────────────

def run_debug_loop(
    build_command: str,
    coder_model: str,
    tools: list,
    execute_tool_fn: Callable,
    on_tool_call: Callable | None = None,
    on_tool_result: Callable | None = None,
    max_retries: int = 5,
) -> tuple[bool, str]:
    """
    Try to build/deploy. On failure, ask the coder to fix the errors and
    retry.  Returns (success, log_summary).
    """
    log_lines: list[str] = []

    for attempt in range(1, max_retries + 1):
        # Run the build command via tool
        if on_tool_call:
            on_tool_call("run_command", {"command": build_command})

        build_result = execute_tool_fn("run_command", {"command": build_command})

        if on_tool_result:
            on_tool_result("run_command", build_result, True)

        # Check exit code
        try:
            result_data = json.loads(build_result)
            exit_code = result_data.get("exit_code", 1)
            output = result_data.get("output", "")
        except (json.JSONDecodeError, TypeError):
            exit_code = 1
            output = str(build_result)

        if exit_code == 0:
            log_lines.append(f"Attempt {attempt}: ✓ Build succeeded.")
            return True, "\n".join(log_lines)

        log_lines.append(f"Attempt {attempt}: ✗ Build failed (exit {exit_code}).")

        # Ask the coder to fix the errors
        fix_task = (
            f"The build command `{build_command}` failed with exit code {exit_code}.\n"
            f"Error output:\n```\n{output[:3000]}\n```\n"
            f"Fix the errors and confirm what you changed."
        )
        fix_response = execute_step(
            fix_task,
            coder_model=coder_model,
            tools=tools,
            execute_tool_fn=execute_tool_fn,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
            original_request="",
        )
        log_lines.append(f"  Fix applied: {fix_response[:200]}")

    return False, "\n".join(log_lines)


# ── Full pipeline ───────────────────────────────────────────────────────

def run_pipeline(
    user_request: str,
    conversation_history: list[dict],
    planner_model: str = "gemma4:12b",
    coder_model: str = "qwen2.5-coder:14b",
    tools: list | None = None,
    execute_tool_fn: Callable | None = None,
    max_history_turns: int = 20,
    use_planner: bool = True,
    auto_detect_complexity: bool = True,
    on_phase: Callable | None = None,
    on_plan_ready: Callable | None = None,
    on_step_start: Callable | None = None,
    on_step_done: Callable | None = None,
    on_tool_call: Callable | None = None,
    on_tool_result: Callable | None = None,
    on_debug_start: Callable | None = None,
    on_debug_done: Callable | None = None,
) -> str:
    """
    Full Gemma-plans → Qwen-executes → debug-loop pipeline.

    Callbacks let the GUI/CLI display progress in real-time.
    Returns the final summary text.
    """
    # ── 1. Trim history for token efficiency
    trimmed = trim_history(conversation_history, max_turns=max_history_turns,
                           summariser_model=planner_model)
    # Build a short context summary string for the planner
    context_summary = ""
    for msg in trimmed:
        if msg.get("role") == "system" and "[Earlier conversation summary]" in msg.get("content", ""):
            context_summary = msg["content"]
            break

    # ── 2. Decide whether to plan
    do_plan = use_planner
    if do_plan and auto_detect_complexity:
        do_plan = should_use_planner(user_request)

    if do_plan:
        # Plan phase (Gemma 4)
        if on_phase:
            on_phase("planning", f"🧠 Planning with {planner_model}...")

        steps = create_plan(user_request, context_summary,
                            planner_model=planner_model)

        if on_plan_ready:
            on_plan_ready(steps)
    else:
        # Skip planning — treat the whole request as one step
        if on_phase:
            on_phase("executing", "⚡ Direct mode — sending straight to coder...")
        steps = [user_request]

    # ── 3. Execute phase (Qwen 3 Coder)
    if on_phase:
        on_phase("executing", f"⚡ Executing with {coder_model}...")

    step_results: list[str] = []
    build_command: str | None = None

    for idx, step in enumerate(steps, 1):
        if on_step_start:
            on_step_start(idx, len(steps), step)

        result = execute_step(
            step,
            coder_model=coder_model,
            tools=tools or [],
            execute_tool_fn=execute_tool_fn or (lambda n, a: "no tool executor"),
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
            original_request=user_request,
        )
        step_results.append(result)

        if on_step_done:
            on_step_done(idx, len(steps), result)

        # Detect if this step mentions a build/test command
        step_lower = step.lower()
        for keyword in ("run build", "npm run build", "pytest", "cargo build",
                        "python -m pytest", "make", "go build", "dotnet build",
                        "mvn", "gradle", "pip install"):
            if keyword in step_lower:
                # Extract the command from the step text
                build_command = step
                break

    # ── 4. Debug loop (if a build command was detected)
    if build_command and execute_tool_fn:
        # Try to extract a clean shell command from the step text
        clean_cmd = _extract_command(build_command)
        if clean_cmd:
            if on_debug_start:
                on_debug_start(clean_cmd)

            success, debug_log = run_debug_loop(
                build_command=clean_cmd,
                coder_model=coder_model,
                tools=tools or [],
                execute_tool_fn=execute_tool_fn,
                on_tool_call=on_tool_call,
                on_tool_result=on_tool_result,
            )

            if on_debug_done:
                on_debug_done(success, debug_log)

    # ── 5. Produce final summary
    summary_parts = [f"### Plan ({len(steps)} steps)"]
    for idx, step in enumerate(steps, 1):
        summary_parts.append(f"{idx}. {step}")
    summary_parts.append("")
    summary_parts.append("### Results")
    for idx, result in enumerate(step_results, 1):
        short = result[:300] if result else "(no output)"
        summary_parts.append(f"**Step {idx}:** {short}")

    return "\n".join(summary_parts)


def _extract_command(step_text: str) -> str | None:
    """Try to extract a runnable shell command from a plan step string."""
    # Look for text in backticks first
    import re
    backtick_match = re.search(r"`([^`]+)`", step_text)
    if backtick_match:
        return backtick_match.group(1)

    # Common command patterns
    for prefix in ("run ", "execute ", "Run ", "Execute "):
        if prefix in step_text:
            after = step_text.split(prefix, 1)[1].strip().rstrip(".")
            if after:
                return after

    return None
