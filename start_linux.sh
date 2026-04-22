#!/usr/bin/env bash
set -euo pipefail
echo "============================================================"
echo "  AI Code Assistant — Robust Local Setup (Linux)"
echo "============================================================"
echo ""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── 0. Detect GPU ──────────────────────────────────────────────
echo "[0/5] Detecting GPU..."

# Keep PCI ID database fresh so new hardware (e.g. RX 9070 XT) is named correctly
echo "       Refreshing PCI ID database..."
if command -v update-pciids &>/dev/null; then
    sudo update-pciids 2>/dev/null || true          # runs as root; silently skip if it fails
elif command -v curl &>/dev/null; then
    # Fallback: update the user-local copy directly
    mkdir -p "$HOME/.local/share"
    curl -fsSL https://pci-ids.ucw.cz/v2.2/pci.ids.gz \
        | gunzip > "$HOME/.local/share/pci.ids" 2>/dev/null || true
    export PCIIDS="$HOME/.local/share/pci.ids"
fi

GPU_NAME="Unknown GPU"
GPU_VRAM="Unknown"
GPU_VENDOR="unknown"   # nvidia | amd | intel | unknown
GPU_INDEX=0            # PCI device index of the chosen GPU

if command -v lspci &>/dev/null; then
    # Collect all display-capable devices with their indices
    mapfile -t GPU_LINES < <(lspci | grep -iE 'VGA|3D|Display' || true)

    DEDICATED_LINE=""
    DEDICATED_INDEX=0
    FALLBACK_LINE=""
    FALLBACK_INDEX=0

    for i in "${!GPU_LINES[@]}"; do
        line="${GPU_LINES[$i]}"
        # Prefer NVIDIA or AMD Radeon discrete cards (not APU/integrated)
        if echo "$line" | grep -iqE 'NVIDIA|GeForce|Quadro|Tesla'; then
            DEDICATED_LINE="$line"
            DEDICATED_INDEX=$i
            GPU_VENDOR="nvidia"
            break
        elif echo "$line" | grep -iqE 'AMD|ATI|Radeon'; then
            DEDICATED_LINE="$line"
            DEDICATED_INDEX=$i
            GPU_VENDOR="amd"
            break
        fi
        # Keep integrated as fallback
        if [ -z "$FALLBACK_LINE" ]; then
            FALLBACK_LINE="$line"
            FALLBACK_INDEX=$i
        fi
    done

    if [ -n "$DEDICATED_LINE" ]; then
        GPU_NAME=$(echo "$DEDICATED_LINE" | sed 's/.*: //')
        GPU_INDEX=$DEDICATED_INDEX
        echo "       Dedicated GPU found (index $GPU_INDEX): $GPU_NAME"
    elif [ -n "$FALLBACK_LINE" ]; then
        GPU_NAME=$(echo "$FALLBACK_LINE" | sed 's/.*: //')
        GPU_INDEX=$FALLBACK_INDEX
        GPU_VENDOR="integrated"
        echo "WARNING: No discrete GPU found. Falling back to: $GPU_NAME"
    else
        echo "WARNING: No GPU detected at all — Ollama will use CPU."
        GPU_VENDOR="none"
    fi
fi

# Get VRAM (NVIDIA path)
if [ "$GPU_VENDOR" = "nvidia" ] && command -v nvidia-smi &>/dev/null; then
    GPU_VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null \
        | sed -n "$((GPU_INDEX + 1))p" || true)
    GPU_VRAM="${GPU_VRAM} MB"
fi

# Get VRAM (AMD path via rocm-smi)
if [ "$GPU_VENDOR" = "amd" ] && command -v rocm-smi &>/dev/null; then
    GPU_VRAM=$(rocm-smi --showmeminfo vram 2>/dev/null \
        | grep -i 'total' | head-1 | awk '{print $NF}' || true)
    GPU_VRAM="${GPU_VRAM:-Unknown}"
fi

echo "       GPU:  $GPU_NAME"
echo "       VRAM: $GPU_VRAM"
echo ""

# ── 1. Ensure Python exists ────────────────────────────────────
echo "[1/5] Checking Python environment..."
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.10+ first."
    exit 1
fi
PYTHON_VER=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "       Python version: $PYTHON_VER"

# ── 2. Ensure venv support exists ──────────────────────────────
echo "[2/5] Checking venv support..."
if ! python3 -m venv --help &>/dev/null; then
    echo "ERROR: python3-venv is missing."
    echo "Install it via:"
    echo "   Ubuntu/Debian: sudo apt install python3-venv python3-pip"
    echo "   Arch:          sudo pacman -S python"
    exit 1
fi

# ── 3. Create / repair virtual environment ─────────────────────
echo "[3/5] Setting up virtual environment..."
if [ ! -d ".venv" ]; then
    echo "       Creating .venv ..."
    python3 -m venv .venv
fi
if [ ! -f ".venv/bin/activate" ]; then
    echo "WARNING: Broken venv detected. Rebuilding..."
    rm -rf .venv
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip --quiet

# ── 4. Dependencies ────────────────────────────────────────────
echo "[4/5] Installing dependencies..."
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt --quiet --disable-pip-version-check
else
    echo "WARNING: requirements.txt not found. Skipping dependency install."
fi
echo "       Dependencies ready."

# ── 5. Ollama setup ────────────────────────────────────────────
echo "[5/5] Starting Ollama..."
if ! command -v ollama &>/dev/null; then
    echo "       Ollama not found. Installing..."
    curl -fsSL https://ollama.com/install.sh | sh
fi

# ── Force Ollama onto the dedicated GPU ───────────────────────
# Ollama inherits these env vars from the shell that launches it.
# OLLAMA_GPU_OVERHEAD reserves a small VRAM buffer to prevent OOM.
case "$GPU_VENDOR" in
    nvidia)
        echo "       Pinning Ollama to NVIDIA GPU index $GPU_INDEX..."
        export CUDA_VISIBLE_DEVICES="$GPU_INDEX"
        unset HIP_VISIBLE_DEVICES ROCR_VISIBLE_DEVICES 2>/dev/null || true
        ;;
    amd)
        echo "       Pinning Ollama to AMD/ROCm GPU index $GPU_INDEX..."
        export HIP_VISIBLE_DEVICES="$GPU_INDEX"
        export ROCR_VISIBLE_DEVICES="$GPU_INDEX"
        unset CUDA_VISIBLE_DEVICES 2>/dev/null || true
        ;;
    integrated|none)
        echo "       No discrete GPU — letting Ollama choose (CPU/iGPU)."
        ;;
    *)
        echo "WARNING: Unknown vendor '$GPU_VENDOR'; not overriding GPU selection."
        ;;
esac

# Prevent Ollama from spilling layers onto the iGPU when VRAM is tight
export OLLAMA_GPU_OVERHEAD=268435456   # reserve 256 MB headroom

if ! pgrep -x "ollama" &>/dev/null; then
    echo "       Starting Ollama server..."
    nohup ollama serve >/dev/null 2>&1 &
    sleep 3
fi

if ! pgrep -x "ollama" &>/dev/null; then
    echo "WARNING: Ollama may not have started correctly."
else
    echo "       Ollama running."
fi

# ── 6. Launch application ──────────────────────────────────────
echo ""
echo "============================================================"
echo "  Launching AI Code Assistant"
echo "============================================================"
echo "  GPU:    $GPU_NAME ($GPU_VRAM)"
echo "  Vendor: $GPU_VENDOR  |  Device index: $GPU_INDEX"
echo "  Status: Ready"
echo "============================================================"
echo ""
exec python gui.py
