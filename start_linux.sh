#!/usr/bin/env bash
set -euo pipefail

echo "============================================================"
echo "  AI Code Assistant — Local Setup (Linux)"
echo "============================================================"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── 0. Detect GPU ──────────────────────────────────────────────
echo "[0/5] Detecting GPU..."
GPU_NAME="Unknown GPU"
GPU_VRAM="? MB"

if command -v lspci &>/dev/null; then
    # Try to find a dedicated GPU (AMD/NVIDIA first)
    GPU_LINE=$(lspci | grep -iE 'VGA|3D|Display' | grep -iE 'AMD|NVIDIA|Radeon|GeForce' | head -1)
    if [ -z "$GPU_LINE" ]; then
        GPU_LINE=$(lspci | grep -iE 'VGA|3D|Display' | head -1)
    fi
    if [ -n "$GPU_LINE" ]; then
        GPU_NAME=$(echo "$GPU_LINE" | sed 's/.*: //')
    fi
fi

# Try to get VRAM from /sys (AMD) or nvidia-smi (NVIDIA)
if command -v nvidia-smi &>/dev/null; then
    GPU_VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)
    GPU_VRAM="${GPU_VRAM} MB"
elif [ -d /sys/class/drm ]; then
    for card in /sys/class/drm/card*/device/mem_info_vram_total; do
        if [ -f "$card" ]; then
            VRAM_BYTES=$(cat "$card" 2>/dev/null)
            if [ -n "$VRAM_BYTES" ] && [ "$VRAM_BYTES" -gt 0 ] 2>/dev/null; then
                GPU_VRAM="$((VRAM_BYTES / 1048576)) MB"
            fi
            break
        fi
    done
fi

echo "       GPU: $GPU_NAME"
echo "       VRAM: $GPU_VRAM"
echo ""

# ── 1. Check / Install Ollama ──────────────────────────────────
if ! command -v ollama &>/dev/null; then
    echo "[1/5] Ollama not found. Installing..."
    curl -fsSL https://ollama.com/install.sh | sh
    if ! command -v ollama &>/dev/null; then
        echo "ERROR: Ollama installation failed."
        echo "Please install manually: https://ollama.com/download"
        exit 1
    fi
    echo "[1/5] Ollama installed successfully!"
else
    echo "[1/5] Ollama already installed. OK"
fi

# ── 2. Start Ollama server (if not running) ────────────────────
echo "[2/5] Ensuring Ollama server is running..."
if ! pgrep -x "ollama" &>/dev/null; then
    ollama serve &>/dev/null &
    sleep 3
fi
echo "       Ollama server ready."

# ── 3. Check models ────────────────────────────────────────────
echo "[3/5] Skipping model downloads..."
echo "       Models can be configured directly in Settings."

# ── 4. Python virtual environment + dependencies ───────────────
echo "[4/5] Setting up Python environment..."

if [ ! -d ".venv" ]; then
    echo "       Creating virtual environment..."
    python3 -m venv .venv
fi
source .venv/bin/activate

echo "       Installing Python dependencies..."
pip install -r requirements.txt --quiet --disable-pip-version-check
echo "       Dependencies installed."

# ── 5. Launch the GUI ──────────────────────────────────────────
echo "[5/5] Launching AI Code Assistant..."
echo ""
echo "============================================================"
echo "  GPU:     $GPU_NAME ($GPU_VRAM)"
echo "  Planner: gemma4:12b"
echo "  Coder:   qwen2.5-coder:14b"
echo "  Ready!   The assistant window should open now."
echo "============================================================"
echo ""
python gui.py
