# Use CUDA 12.1 base image for runtime
FROM nvidia/cuda:12.1.0-base-ubuntu22.04

# Set working directory
WORKDIR /app

# Install basic dependencies and tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    python3.10 \
    python3-pip \
    ffmpeg \
    libsndfile1 \
    libsm6 \
    libxext6 \
    libcudnn9-cuda-12 \
    libcublas-12-1 \
    awscli \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt
COPY requirements.txt .

# Install CTranslate2, faster-whisper, and other Python dependencies
RUN pip3 install --no-cache-dir ctranslate2 faster-whisper -r requirements.txt

# Create directories for whisper models
RUN mkdir -p /root/.cache/whisper

# Copy application code from the cinema_bot directory
COPY cinema_bot/ /app/cinema_bot/

# Note: Termination script not included in restructured version
# Add back if needed for RunPod deployment

# Create an entry point script that accepts environment variables
RUN echo '#!/bin/bash\n\
# Create log directory\n\
mkdir -p /app/logs\n\
\n\
# Execute the Python command and redirect stdout/stderr to log file\n\
python3 -u -m cinema_bot \
    -u "${DAILY_ROOM_URL}" \
    -t "${DAILY_TOKEN}" \
    -i "${IDENTIFIER}" \
    ${TTS_CONFIG:+-d "${TTS_CONFIG}"} 2>&1 | tee /app/logs/cinema_bot.log\n\
\n\
# Store the exit code of the Python process\n\
EXIT_CODE=${PIPESTATUS[0]}\n\
\n\
echo "Python process exited with code $EXIT_CODE. Capturing logs for upload..."\n\
\n\
# Shut down the RunPod container when the process exits\n\
/app/terminate_pod.sh\n\
\n\
# Exit with the same code as the Python process\n\
exit $EXIT_CODE\n\
' > /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Command to run when container starts
ENTRYPOINT ["/app/entrypoint.sh"]