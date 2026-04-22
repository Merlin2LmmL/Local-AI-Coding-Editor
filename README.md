# AI Code Assistant (Local-Only)

A fully local AI coding assistant powered by **Ollama**. No cloud APIs, no data leaves your machine.

## Hardware

Optimised for high-end consumer GPUs:

| GPU | VRAM | Recommended Models |
|---|---|---|
| **AMD RX 9070 XT** | 16 GB | Qwen 3 Coder 30B (MoE), Gemma 4 12B |
| Any GPU ≥ 8 GB | 8+ GB | Qwen 2.5 Coder 7B, Gemma 4 E4B |
| CPU-only | — | TinyLlama 1.1B, Qwen 2.5 Coder 0.5B |

## Quick Start

### Windows

Double-click **`start_windows.bat`** — it will:
1. Download & install Ollama (if not installed)
2. Start the Ollama server
3. Pull default models (`qwen3-coder:30b`, `gemma4:12b`)
4. Create a Python virtual environment
5. Install dependencies
6. Launch the GUI

### Linux

```bash
chmod +x start_linux.sh
./start_linux.sh
```

Same steps as Windows, adapted for Linux.

## Manual Setup

If you prefer to set things up yourself:

```bash
# 1. Install Ollama: https://ollama.com/download

# 2. Pull a model
ollama pull qwen3-coder:30b

# 3. Install Python dependencies
python -m venv .venv
source .venv/bin/activate    # Linux/macOS
.venv\Scripts\activate       # Windows
pip install -r requirements.txt

# 4. Launch
python gui.py          # Desktop GUI
# or
uvicorn main:app       # Web API (http://localhost:8000)
```

## Available Models

The settings menu (⚙) lets you switch between any model Ollama supports. Pre-configured options include:

- **Qwen 3 Coder 30B** ★ — MoE architecture, only 3B active params, fits 16 GB VRAM
- **Gemma 4 12B / 27B** — Google's latest open model family
- **Qwen 2.5 Coder** (0.5B–32B) — Previous-gen coding specialist
- **CodeLlama** (7B–34B) — Meta's code model
- **DeepSeek Coder** (6.7B–33B) — Strong at code
- **StarCoder2** (3B–7B) — 600+ programming languages
- And more...

## Architecture

```
gui.py            — Desktop GUI (Tkinter)
main.py           — FastAPI web backend
llm_client.py     — Ollama Python client (tool calling)
tools.py          — File system & command tools
settings.py       — Model presets & settings persistence
config.py         — Workspace & security config
```

All inference runs through Ollama's local server (`http://localhost:11434`).
Tool calling is handled natively by Ollama-supported models.

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com/download)
- A GPU with ≥ 8 GB VRAM (recommended)
