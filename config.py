"""Configuration for the AI Code Assistant (local-only)."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# WORKSPACE_PATH can be changed at runtime via config.WORKSPACE_PATH = Path(...)
WORKSPACE_PATH = Path(os.getenv("WORKSPACE_PATH", os.getcwd()))

# Ollama server URL (default localhost)
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# Security: Directories we never allow access to
BLOCKED_PATHS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".env",
    ".cursor",
}
