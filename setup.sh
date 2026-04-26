#!/usr/bin/env bash
# ============================================================================
#  DBD Auto Skill Check - Setup (Linux / macOS)
#  --------------------------------------------------------------------------
#  Creates a local virtual environment in .venv/, then installs every
#  Python package the tool needs:
#      - All required runtime deps from requirements.txt (incl. pynput)
#      - ONNX Runtime (GPU build if an NVIDIA driver is detected, else CPU)
#
#  Run this ONCE after cloning. After it finishes, use start.sh to launch
#  the tool. Re-run any time requirements.txt changes.
# ============================================================================

set -u

cd "$(dirname "$0")"

echo
echo "============================================================================"
echo "  DBD Auto Skill Check - Setup"
echo "============================================================================"
echo

# ------------------------------------------------------------------- Python --
PYTHON=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        PYTHON="$cand"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "[ERROR] Python is not on PATH."
    echo "        Install Python 3.10+ from your package manager, e.g.:"
    echo "          sudo apt install python3 python3-venv python3-pip   # Debian/Ubuntu"
    echo "          sudo dnf install python3 python3-pip                # Fedora"
    echo "          brew install python                                  # macOS"
    exit 1
fi

PYVER="$("$PYTHON" --version 2>&1 | awk '{print $2}')"
echo "[OK] Found Python $PYVER ($PYTHON)"

if ! "$PYTHON" -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >/dev/null 2>&1; then
    echo "[ERROR] Python 3.9+ is required - found $PYVER."
    exit 1
fi

# ------------------------------------------------------------ venv creation --
VENV_PY=".venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
    echo
    echo "[1/4] Creating virtual environment in .venv/ ..."
    if ! "$PYTHON" -m venv .venv; then
        echo "[ERROR] Could not create virtual environment."
        echo "        On Debian/Ubuntu you may need:  sudo apt install python3-venv"
        exit 1
    fi
else
    echo "[1/4] Virtual environment already exists - reusing .venv/"
fi

if [ ! -x "$VENV_PY" ]; then
    echo "[ERROR] Virtual environment looks broken: $VENV_PY missing."
    echo "        Delete .venv/ and re-run this script."
    exit 1
fi

# -------------------------------------------------------- upgrade pip first --
echo
echo "[2/4] Upgrading pip / setuptools / wheel ..."
if ! "$VENV_PY" -m pip install --upgrade pip setuptools wheel; then
    echo "[WARN] pip upgrade failed - continuing anyway."
fi

# ------------------------------------------- install requirements.txt deps --
echo
echo "[3/4] Installing required packages from requirements.txt ..."
if ! "$VENV_PY" -m pip install -r requirements.txt; then
    echo "[ERROR] pip install -r requirements.txt failed."
    echo "        Scroll up to see which package errored out."
    exit 1
fi

# ------------------------------------- decide GPU vs CPU ONNX Runtime ------
echo
echo "[4/4] Detecting NVIDIA GPU ..."
USE_GPU_ORT=""
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
    USE_GPU_ORT=1
    echo "      NVIDIA GPU detected - installing GPU ONNX Runtime (CUDA)."
else
    echo "      No working NVIDIA GPU detected - installing CPU ONNX Runtime."
fi

# Refuse to mix onnxruntime + onnxruntime-gpu - they share .so files and conflict.
"$VENV_PY" -m pip uninstall -y onnxruntime onnxruntime-gpu >/dev/null 2>&1 || true

if [ -n "$USE_GPU_ORT" ]; then
    if ! "$VENV_PY" -m pip install --upgrade onnxruntime-gpu; then
        echo "[WARN] onnxruntime-gpu install failed - falling back to CPU build."
        if ! "$VENV_PY" -m pip install --upgrade onnxruntime; then
            echo "[ERROR] CPU ONNX Runtime install also failed."
            exit 1
        fi
    fi
else
    if ! "$VENV_PY" -m pip install --upgrade onnxruntime; then
        echo "[ERROR] ONNX Runtime install failed."
        exit 1
    fi
fi

# ------------------------------------------------ model files sanity check --
mkdir -p models
if ! ls models/*.onnx models/*.trt >/dev/null 2>&1; then
    echo
    echo "[INFO] No model files found in ./models/."
    echo "       Drop your .onnx (or .trt for TensorRT) model into the models/ folder"
    echo "       before starting the tool. The README explains where to grab one."
fi

# ------------------------------------------------------------ final notes ---
cat <<'EOF'

============================================================================
  Setup complete.

  Next step:  ./start.sh

  Linux notes:
    - DBD itself runs via Proton/Steam Play.
    - Under Wayland, mss screen capture can fail on fullscreen windows -
      an X11/XWayland session is the most reliable option.
    - pynput key sending under Wayland may need uinput permissions; X11
      works without setup.
============================================================================
EOF
