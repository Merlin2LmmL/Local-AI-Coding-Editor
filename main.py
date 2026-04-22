"""AI Code Assistant — FastAPI backend, dual-model pipeline (Gemma 4 + Qwen 3 Coder)."""
import json
import os
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel

from config import WORKSPACE_PATH
from tools import TOOL_DEFINITIONS, execute_tool
from llm_client import chat_ollama, run_pipeline
import settings as user_settings

app = FastAPI(title="AI Code Assistant (Local)")
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Compact system prompt — every token counts on local models
SYSTEM_PROMPT = (
    "You are a local AI coding assistant. Complete tasks using the provided tools. "
    "Use search_replace for small edits, write_file for new files. "
    "Read files before editing. Run build/tests after changes. "
    "Reply concisely in Markdown. Use backticks for paths and symbols."
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    workspace_path: str | None = None


def build_messages(request: ChatRequest) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for message in request.messages:
        messages.append({"role": message.role, "content": message.content})
    return messages


async def chat_stream(request: ChatRequest) -> AsyncGenerator[str, None]:
    """Stream chat with dual-model pipeline via local Ollama."""
    settings = user_settings.load_settings()
    planner_model = settings.get("planner_model", "gemma4:12b")
    coder_model = settings.get("coder_model", "qwen2.5-coder:14b")
    messages = build_messages(request)
    max_iterations = 25
    iteration = 0
    consecutive_errors = 0

    while iteration < max_iterations:
        iteration += 1
        try:
            content, tool_calls = chat_ollama(
                messages, model=coder_model, tools=TOOL_DEFINITIONS)
            consecutive_errors = 0
        except Exception as exc:
            consecutive_errors += 1
            error_msg = f"Ollama Error: {exc}"
            if consecutive_errors >= 3:
                yield json.dumps({"type": "error", "content": f"{error_msg} (stopping)"}) + "\n"
                return
            yield json.dumps({"type": "error", "content": error_msg}) + "\n"
            continue

        if content:
            yield json.dumps({"type": "content", "content": content}) + "\n"
        if not tool_calls:
            break

        for tc in tool_calls:
            name = tc.get("name", "unknown")
            args = tc.get("arguments", {})
            yield json.dumps({"type": "tool_call", "name": name, "args": args}) + "\n"
            try:
                result = execute_tool(name, args)
                yield json.dumps({"type": "tool_result", "name": name, "result": result}) + "\n"
            except Exception as exc:
                result = f"Error executing {name}: {exc}"
                yield json.dumps({"type": "tool_result", "name": name, "result": result}) + "\n"

            messages.append({
                "role": "assistant", "content": content or "",
                "tool_calls": [{"function": {"name": name, "arguments": args}}],
            })
            messages.append({"role": "tool", "content": result})

    yield json.dumps({"type": "done"}) + "\n"


@app.post("/api/chat/stream")
async def chat_stream_endpoint(req: ChatRequest):
    return StreamingResponse(chat_stream(req), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache"})


@app.get("/api/files")
async def list_workspace_files(path: str = "."):
    from tools import list_files
    return json.loads(list_files(path, recursive=True))


@app.get("/api/file")
async def get_file(path: str):
    from tools import read_file
    result = read_file(path)
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        return {"path": path, "content": result, "error": True}


@app.get("/api/workspace")
async def get_workspace():
    return {"path": str(WORKSPACE_PATH.resolve())}


@app.get("/")
async def root():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "AI Code Assistant (Local). Run: uvicorn main:app --reload"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
