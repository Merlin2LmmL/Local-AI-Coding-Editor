"""User settings - persisted to JSON for runtime config (local-only, Ollama)."""
import json
from pathlib import Path

SETTINGS_FILE = Path(__file__).parent / "settings.json"

# All models run locally via Ollama.
# Format: (ollama_tag, display_name, vram_hint, description)
OLLAMA_MODELS = [
    # ── Tiny (2–4 GB VRAM) ──────────────────────────────────────────
    ("tinyllama", "TinyLlama (1.1B)", "~2 GB", "Fastest, very light"),
    ("qwen2.5-coder:0.5b", "Qwen 2.5 Coder 0.5B", "~1 GB", "Tiny, autocomplete"),
    ("qwen2.5-coder:1.5b", "Qwen 2.5 Coder 1.5B", "~2 GB", "Code-focused, minimal VRAM"),
    ("phi3:mini", "Phi-3 Mini (3.8B)", "~4 GB", "Microsoft, basic tasks"),
    ("llama3.2:1b", "Llama 3.2 1B", "~2 GB", "Smallest Llama"),
    ("starcoder2:3b", "StarCoder2 3B", "~4 GB", "Lightweight, 600+ languages"),

    # ── Small (4–8 GB VRAM) ─────────────────────────────────────────
    ("llama3.2:3b", "Llama 3.2 3B", "~4 GB", "Small, efficient"),
    ("gemma4:e2b", "Gemma 4 E2B", "~3 GB", "Google edge model, very fast"),
    ("gemma4:e4b", "Gemma 4 E4B", "~5 GB", "Google edge model, fast"),
    ("codellama:7b", "CodeLlama 7B", "~8 GB", "Meta code model"),
    ("deepseek-coder:6.7b", "DeepSeek Coder 6.7B", "~6 GB", "Strong at code"),
    ("qwen2.5-coder:7b", "Qwen 2.5 Coder 7B", "~8 GB", "Excellent coding"),
    ("mistral:7b", "Mistral 7B", "~8 GB", "Good general + code"),
    ("starcoder2:7b", "StarCoder2 7B", "~8 GB", "Fast inference, many languages"),
    ("llama3.2:latest", "Llama 3.2 (8B)", "~8 GB", "Latest Llama 3.2"),

    # ── Medium (8–16 GB VRAM) ───────────────────────────────────────
    ("codellama:13b", "CodeLlama 13B", "~14 GB", "Better code understanding"),
    ("qwen2.5-coder:14b", "Qwen 2.5 Coder 14B", "~12 GB", "Larger Qwen coder"),
    ("deepseek-coder:16b", "DeepSeek Coder 16B", "~16 GB", "MoE, 338 languages"),
    ("llama3.1:8b", "Llama 3.1 8B", "~8 GB", "General + code"),
    ("gemma4:12b", "Gemma 4 12B", "~10 GB", "Google Gemma 4, great quality"),

    # ── Large / MoE ─────────────────────────────────────────────────
    ("qwen3-coder:30b", "Qwen 3 Coder 30B ★", "~18 GB", "MoE, 3B active — best coding"),
    ("gemma4:27b", "Gemma 4 27B", "~18 GB", "Google Gemma 4, near-frontier"),
    ("qwen2.5-coder:32b", "Qwen 2.5 Coder 32B", "~24 GB", "Best local coding (prev gen)"),
    ("deepseek-coder:33b", "DeepSeek Coder 33B", "~24 GB", "Large, powerful"),
    ("codellama:34b", "CodeLlama 34B", "~20 GB", "Advanced code completion"),
    ("codestral", "Codestral (22B)", "~16 GB", "Mistral coding specialist"),
    ("gemma4:31b", "Gemma 4 31B (Dense)", "~24 GB", "Dense 31B, top quality"),
]

# Models the launch scripts will pre-pull
DEFAULT_MODELS_TO_PULL = [
    "qwen2.5-coder:14b",
    "gemma4:12b",
]

DEFAULTS = {
    "planner_model": "gemma4:12b",
    "coder_model": "qwen2.5-coder:14b",
    # Maximum conversation turns to keep in context (older ones get summarised)
    "max_history_turns": 20,
    # Task planning toggle — when False, all requests go directly to the coder
    "task_planning_enabled": True,
    # When True, the planner only runs for complex multi-step requests
    "planning_auto_detect": True,
}


def load_settings() -> dict:
    """Load settings from JSON file."""
    settings = DEFAULTS.copy()
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            for key, value in data.items():
                if key in settings:
                    settings[key] = value
        except Exception:
            pass
    return settings


def save_settings(settings: dict):
    """Save settings to JSON file."""
    to_save = DEFAULTS.copy()
    for key, value in settings.items():
        if key in DEFAULTS:
            to_save[key] = value
    SETTINGS_FILE.write_text(json.dumps(to_save, indent=2), encoding="utf-8")
