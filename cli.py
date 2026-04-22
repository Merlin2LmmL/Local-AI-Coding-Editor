"""CLI interface for AI Code Assistant — Dual-model pipeline (Gemma 4 + Qwen 3 Coder)."""
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from config import WORKSPACE_PATH
from tools import TOOL_DEFINITIONS, execute_tool
from llm_client import run_pipeline
import settings as user_settings

console = Console()


def show_welcome():
    settings = user_settings.load_settings()
    planner = settings.get("planner_model", "gemma4:31b")
    coder = settings.get("coder_model", "qwen3-coder:30b")
    console.print("\n")
    console.print(Panel(
        "[bold cyan]AI Code Assistant (Local)[/bold cyan]\n"
        f"[dim]Workspace: {WORKSPACE_PATH.resolve()}[/dim]\n"
        f"[dim]🧠 Planner: {planner}  ⚡ Coder: {coder}[/dim]\n"
        "[dim]Gemma plans → Qwen executes → Debug loop until build passes[/dim]",
        border_style="cyan",
    ))
    console.print("\n")


# ── Rich callbacks for real-time display ────────────────────────

def on_phase(phase, message):
    console.print(f"\n[bold magenta]{message}[/bold magenta]")


def on_plan_ready(steps):
    console.print(Panel(
        "\n".join(f"  {i}. {s}" for i, s in enumerate(steps, 1)),
        title="📋 Plan", border_style="cyan", expand=False,
    ))


def on_step_start(idx, total, step):
    console.print(f"\n[bold green][{idx}/{total}][/bold green] {step}")


def on_step_done(idx, total, result):
    short = result[:300] if result else "(no output)"
    console.print(f"[dim]  → {short}[/dim]")


def on_tool_call(name, args):
    args_str = json.dumps(args, indent=2) if args else "{}"
    console.print(Panel(
        f"[cyan]🔧 {name}[/cyan]\n[dim]{args_str}[/dim]",
        title="Tool Call", border_style="cyan", expand=False,
    ))


def on_tool_result(name, result, success):
    try:
        result_data = json.loads(result)
        
        # Handle structured data like file listings - convert to plain text list
        if isinstance(result_data, dict):
            if "items" in result_data:
                # File listing or similar with items array
                items = result_data["items"]
                result_str = "\n".join(str(item) for item in items[:50])
            elif "paths" in result_data:
                # Glob/ls output
                paths = result_data["paths"]
                result_str = "\n".join(str(p) for p in paths[:50])
            elif "files" in result_data:
                files = result_data["files"]
                result_str = "\n".join(str(f) for f in files[:50])
            elif "result" in result_data:
                result_str = result_data["result"]
            else:
                result_str = json.dumps(result_data, indent=2)
        elif isinstance(result_data, list):
            result_str = "\n".join(str(item) for item in result_data[:50])
        else:
            result_str = json.dumps(result_data, indent=2)
            
        if len(result_str) > 1000:
            result_str = result_str[:1000] + "\n... (truncated)"
    except (json.JSONDecodeError, TypeError):
        result_str = result[:500] if len(result) > 500 else result

    style = "green" if success else "red"
    icon = "✓" if success else "✗"
    # Print directly without Panel to avoid terminal rendering issues
    if result_str:
        if success:
            console.print(f"[green bold]{icon} {name}[/green bold]\n{result_str}")
        else:
            console.print(f"[red bold]{icon} {name}[/red bold]\n{result_str}")


def on_debug_start(command):
    console.print(f"\n[bold yellow]🔄 Debug loop: `{command}`[/bold yellow]")


def on_debug_done(success, log):
    if success:
        console.print("[bold green]✅ Build succeeded![/bold green]")
    else:
        console.print("[bold red]⚠️ Build failed after retries.[/bold red]")
    console.print(f"[dim]{log}[/dim]")


# ── Main loop ──────────────────────────────────────────────────

def main():
    show_welcome()
    conversation_history = []

    while True:
        try:
            user_input = Prompt.ask("\n[bold cyan]You[/bold cyan]")
            if not user_input.strip():
                continue
            if user_input.lower() in ["/exit", "/quit", "/q"]:
                console.print("[yellow]Goodbye![/yellow]")
                break
            if user_input.lower() == "/clear":
                conversation_history = []
                console.print("[green]Conversation cleared[/green]")
                continue
            if user_input.lower() == "/workspace":
                console.print(f"[cyan]Workspace: {WORKSPACE_PATH.resolve()}[/cyan]")
                continue

            settings = user_settings.load_settings()
            conversation_history.append({"role": "user", "content": user_input})

            with console.status("[bold green]Planning...", spinner="dots"):
                summary = run_pipeline(
                    user_request=user_input,
                    conversation_history=conversation_history,
                    planner_model=settings.get("planner_model", "gemma4:31b"),
                    coder_model=settings.get("coder_model", "qwen3-coder:30b"),
                    tools=TOOL_DEFINITIONS,
                    execute_tool_fn=execute_tool,
                    max_history_turns=settings.get("max_history_turns", 20),
                    on_phase=on_phase,
                    on_plan_ready=on_plan_ready,
                    on_step_start=on_step_start,
                    on_step_done=on_step_done,
                    on_tool_call=on_tool_call,
                    on_tool_result=on_tool_result,
                    on_debug_start=on_debug_start,
                    on_debug_done=on_debug_done,
                )

            if summary:
                conversation_history.append({"role": "assistant", "content": summary})
            console.print()

        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted. Use /exit to quit.[/yellow]")
        except EOFError:
            console.print("\n[yellow]Goodbye![/yellow]")
            break
        except Exception as exc:
            console.print(f"[red]Error: {exc}[/red]")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Goodbye![/yellow]")
