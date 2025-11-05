# Build stage
FROM golang:1.23-alpine AS builder

WORKDIR /app

# Copy go mod and sum files
COPY go.mod ./

# Download all dependencies
RUN go mod tidy

# Copy source code
COPY . .

# Build the binary
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o goodclips cmd/main.go

# Final stage (Debian-based for PySceneDetect/OpenCV compatibility)
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ffmpeg \
       ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
      numpy \
      opencv-python-headless \
      scenedetect \
    && pip install --no-cache-dir \
      torch==2.4.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir \
      transformers==4.52.1 einops accelerate huggingface-hub

WORKDIR /root/

# Copy the binary from builder stage
COPY --from=builder /app/goodclips .

# Copy Python scenedetect scripts (both runner and legacy module)
COPY --from=builder /app/internal/scenedetect/ ./internal/scenedetect/
COPY --from=builder /app/internal/embeddings/ ./internal/embeddings/

# Make Python scripts executable
RUN chmod +x ./internal/scenedetect/*.py ./internal/embeddings/*.py

# Expose port
EXPOSE 8080

# Run the binary
CMD ["./goodclips"]

# GPU runtime stage for InternVideo2 embeddings
FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04 AS runtime-gpu

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System deps (python, pip, ffmpeg)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3 \
        python3-pip \
       ffmpeg \
       ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch (CUDA 12.1 wheels) and other Python deps
RUN python3 -m pip install --upgrade pip \
    && pip install --no-cache-dir \
         torch==2.5.1+cu121 torchvision==0.20.1+cu121 torchaudio==2.5.1+cu121 \
         --index-url https://download.pytorch.org/whl/cu121 \
    && pip install --no-cache-dir \
         decord av opencv-python-headless timm huggingface-hub \
         transformers==4.52.1 einops accelerate scenedetect \
         open-clip-torch pillow safetensors librosa audioread

WORKDIR /root/

# Copy Go binary
COPY --from=builder /app/goodclips .

# Copy Python scripts
COPY --from=builder /app/internal/scenedetect/ ./internal/scenedetect/
COPY --from=builder /app/internal/embeddings/ ./internal/embeddings/

RUN chmod +x ./internal/scenedetect/*.py ./internal/embeddings/*.py

EXPOSE 8080

CMD ["./goodclips"]