# CUDA Setup for TwistedTV Server

This document explains the CUDA setup required for GPU-accelerated Whisper speech-to-text.

## Overview

The TwistedTV server uses **faster-whisper** with CUDA acceleration for real-time speech transcription. The setup requires PyTorch with CUDA 11.8 support, but there's a library version mismatch that must be resolved.

## The Problem

PyTorch CUDA 11.8 (built with CUDA 11.8 toolkit) looks for library files with CUDA 12 naming conventions:
- Looks for: `libcublas.so.12` and `libcublasLt.so.12`
- But installed: `libcublas.so.11` and `libcublasLt.so.11`

This causes runtime errors:
```
RuntimeError: Library libcublas.so.12 is not found or cannot be loaded
```

## The Solution

We use symbolic links to bridge the version mismatch. The `setup_cuda.sh` script automates this process.

### Manual Setup (if script fails)

1. **Find your Python site-packages directory:**
   ```bash
   cd twistedtv-server
   source venv/bin/activate
   python3 -c "import site; print(site.getsitepackages()[0])"
   ```

2. **Navigate to the cuBLAS library directory:**
   ```bash
   cd <site-packages>/nvidia/cublas/lib
   ```

3. **Create symbolic links:**
   ```bash
   ln -sf libcublas.so.11 libcublas.so.12
   ln -sf libcublasLt.so.11 libcublasLt.so.12
   ```

4. **Verify the links:**
   ```bash
   ls -lh libcublas*.so.1*
   ```

   You should see:
   ```
   libcublas.so.11 -> actual library file
   libcublas.so.12 -> libcublas.so.11
   libcublasLt.so.11 -> actual library file
   libcublasLt.so.12 -> libcublasLt.so.11
   ```

### Automated Setup

Simply run the provided script after installing dependencies:

```bash
cd twistedtv-server
source venv/bin/activate
pip install -r requirements.txt
./setup_cuda.sh
```

The script will:
1. Check that the virtual environment exists
2. Locate the NVIDIA cuBLAS library directory
3. Create the necessary symbolic links
4. Verify the setup

## Environment Configuration

The server automatically configures the `LD_LIBRARY_PATH` to include all NVIDIA CUDA libraries when spawning bot processes. This happens in `cinema_bot/server.py`:

```python
# Find all NVIDIA library directories
import site
import glob
packages = site.getsitepackages()[0]
nvidia_libs = glob.glob(os.path.join(packages, 'nvidia/*/lib'))

# Add to LD_LIBRARY_PATH
if nvidia_libs:
    current_ld_path = env.get('LD_LIBRARY_PATH', '')
    lib_paths = ':'.join(nvidia_libs)
    env['LD_LIBRARY_PATH'] = f"{lib_paths}:{current_ld_path}"
```

This ensures the bot subprocess can find all required CUDA libraries:
- nvidia/cublas/lib
- nvidia/cudnn/lib
- nvidia/cuda_runtime/lib
- nvidia/curand/lib
- nvidia/cusolver/lib
- nvidia/cusparse/lib
- nvidia/cufft/lib
- nvidia/cuda_nvrtc/lib
- nvidia/nccl/lib
- nvidia/nvtx/lib
- nvidia/cuda_cupti/lib

## Verification

After setup, test CUDA transcription by starting the server and connecting a client:

```bash
cd cinema_bot
source ../venv/bin/activate
python3 server.py --port 8765
```

Check the logs for:
```
[DEBUG] Found 11 NVIDIA library directories
[DEBUG] Set LD_LIBRARY_PATH=...
```

When a conversation starts, you should see Whisper loading with CUDA:
```
Whisper model loaded successfully on device: cuda
```

## Troubleshooting

### "libcublas.so.12 not found"
- Run `./setup_cuda.sh` to create the symbolic links
- Verify links exist: `ls -lh venv/lib/python3.*/site-packages/nvidia/cublas/lib/libcublas*.so.1*`

### "CUDA out of memory"
- Reduce Whisper model size in `.env`: `REPO_ID=Systran/faster-distil-whisper-small.en`
- Check GPU memory: `nvidia-smi`

### "No CUDA devices found"
- Verify GPU is available: `nvidia-smi`
- Check PyTorch can see CUDA: `python3 -c "import torch; print(torch.cuda.is_available())"`

### Transcriptions slow/not working
- Check server logs for CUDA library errors
- Verify `WHISPER_DEVICE=cuda` in `.env`
- Ensure `LD_LIBRARY_PATH` is set (check server startup logs)

## Why This Approach?

**Why not use CUDA 12?**
- PyTorch wheels with CUDA 12 support are much larger
- CUDA 11.8 is more widely compatible with existing systems
- The symlink approach works reliably and is simple to automate

**Why not downgrade PyTorch?**
- Newer PyTorch versions have better performance and bug fixes
- faster-whisper requires recent PyTorch versions
- The library mismatch is a naming issue, not a binary incompatibility

**Why symlinks instead of renaming?**
- Symlinks are reversible and don't modify original files
- Multiple library versions can coexist
- Easier to troubleshoot and understand

## Fresh Installation Checklist

When setting up on a new machine:

1. ✅ Install Python 3.11+ and NVIDIA drivers
2. ✅ Clone repository
3. ✅ Create virtual environment: `python3 -m venv venv`
4. ✅ Activate venv: `source venv/bin/activate`
5. ✅ Install dependencies: `pip install -r requirements.txt`
6. ✅ **Run CUDA setup: `./setup_cuda.sh`**
7. ✅ Configure `.env` file
8. ✅ Start server: `python3 cinema_bot/server.py --port 8765`
9. ✅ Verify CUDA in logs

**Don't skip step 6!** Without the symlinks, Whisper will fail to load CUDA libraries.
