#!/bin/bash
# CUDA Setup Script for TwistedTV Server
# This script handles the CUDA library version mismatch between PyTorch CUDA 11.8 and NVIDIA libraries
#
# Issue: PyTorch built with CUDA 11.8 expects libcublas.so.12 library names,
# but the installed nvidia-cublas-cu11 package provides libcublas.so.11
#
# Solution: Create symbolic links to bridge the version mismatch

set -e

echo "Setting up CUDA libraries for TwistedTV server..."

# Activate virtual environment
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Error: Virtual environment not found at $VENV_DIR"
    echo "Please run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

source "$VENV_DIR/bin/activate"

# Find the NVIDIA cuBLAS library directory
CUBLAS_DIR=$(python3 -c "import site; import os; print(os.path.join(site.getsitepackages()[0], 'nvidia/cublas/lib'))" 2>/dev/null)

if [ ! -d "$CUBLAS_DIR" ]; then
    echo "Error: NVIDIA cuBLAS library directory not found"
    echo "Please ensure PyTorch with CUDA support is installed:"
    echo "  pip install torch==2.7.1+cu118 --extra-index-url https://download.pytorch.org/whl/cu118"
    exit 1
fi

echo "Found cuBLAS directory: $CUBLAS_DIR"

# Create symbolic links for CUDA 12 library names
cd "$CUBLAS_DIR"

echo "Creating symbolic links..."

# Check if libcublas.so.11 exists
if [ ! -f "libcublas.so.11" ]; then
    echo "Error: libcublas.so.11 not found in $CUBLAS_DIR"
    exit 1
fi

# Create symlinks if they don't exist or point to wrong targets
if [ ! -L "libcublas.so.12" ] || [ "$(readlink libcublas.so.12)" != "libcublas.so.11" ]; then
    echo "  Creating libcublas.so.12 -> libcublas.so.11"
    ln -sf libcublas.so.11 libcublas.so.12
else
    echo "  libcublas.so.12 already exists and is correct"
fi

if [ ! -L "libcublasLt.so.12" ] || [ "$(readlink libcublasLt.so.12)" != "libcublasLt.so.11" ]; then
    echo "  Creating libcublasLt.so.12 -> libcublasLt.so.11"
    ln -sf libcublasLt.so.11 libcublasLt.so.12
else
    echo "  libcublasLt.so.12 already exists and is correct"
fi

echo ""
echo "CUDA setup complete!"
echo ""
echo "Verification:"
ls -lh "$CUBLAS_DIR"/libcublas*.so.1*

echo ""
echo "You can now start the TwistedTV server with CUDA-accelerated Whisper transcription."
