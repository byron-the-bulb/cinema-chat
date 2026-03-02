#!/bin/bash
# Set up a Python 3.12 virtual environment for the ASR benchmark.
#
# Usage:
#   ./model-benchmark/setup.sh
#
# After setup:
#   source model-benchmark/venv/bin/activate
#   python model-benchmark/asr-benchmark.py data/videos/clip.mp4 --max-secs 60
#
# GPU notes (AMD Ryzen AI MAX / ROCm):
#   The default torch wheel is CPU-only. To use the AMD GPU via ROCm:
#     1. Install ROCm: https://rocm.docs.amd.com/en/latest/
#     2. Replace the torch install below with:
#        pip install torch torchaudio --index-url https://download.pytorch.org/whl/rocm6.1
#   Without ROCm, both models run fine on CPU (INT8 quantization via CTranslate2).

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/venv"
PYTHON="${PYTHON:-python3.12}"

# ── Prerequisites ──────────────────────────────────────────────────────────────
echo "=== ASR Benchmark Setup ==="

if ! which "$PYTHON" > /dev/null 2>&1; then
    echo "ERROR: $PYTHON not found. Install Python 3.12:"
    echo "  sudo dnf install python3.12"
    exit 1
fi

if ! which ffmpeg > /dev/null 2>&1; then
    echo "ERROR: ffmpeg not found. Install it:"
    echo "  sudo dnf install ffmpeg"
    exit 1
fi

echo "Python:  $($PYTHON --version)"
echo "ffmpeg:  $(ffmpeg -version 2>&1 | head -1)"
echo "Venv:    $VENV_DIR"
echo ""

# ── Create venv ────────────────────────────────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    "$PYTHON" -m venv "$VENV_DIR"
else
    echo "Venv already exists, updating..."
fi

source "$VENV_DIR/bin/activate"
pip install --upgrade pip --quiet

# ── PyTorch (CPU by default) ───────────────────────────────────────────────────
echo "Installing PyTorch (CPU)..."
echo "  (For AMD ROCm GPU: edit setup.sh and swap in the ROCm wheel URL)"
pip install torch torchaudio --quiet

# ── Everything else ────────────────────────────────────────────────────────────
echo "Installing ASR packages..."
pip install -r "${SCRIPT_DIR}/requirements.txt" --quiet

echo ""
echo "=== Setup complete ==="
echo ""
echo "Activate:"
echo "  source ${VENV_DIR}/bin/activate"
echo ""
echo "Quick test (first 60s, whisperx only — no model download needed beyond HF cache):"
echo "  python ${SCRIPT_DIR}/asr-benchmark.py ../data/videos/clip.mp4 \\"
echo "      --models whisperx --max-secs 60"
echo ""
echo "Full benchmark:"
echo "  python ${SCRIPT_DIR}/asr-benchmark.py ../data/videos/clip.mp4"
echo ""
echo "Qwen3-ASR note:"
echo "  First run will download the model from HuggingFace (~7GB for 7B variant)."
echo "  Model is cached in ~/.cache/huggingface after the first download."
echo "  Verify/override the model ID with --qwen-model <ID>."
