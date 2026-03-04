#!/bin/bash
set -e

# Configuration
DOCKER_USERNAME="${DOCKER_USERNAME:-}"
IMAGE_NAME="goodclips-runpod"
TAG="${TAG:-latest}"

if [ -z "$DOCKER_USERNAME" ]; then
    echo "Error: DOCKER_USERNAME required"
    echo "Usage: DOCKER_USERNAME=yourusername ./scripts/build-runpod.sh"
    exit 1
fi

FULL_IMAGE="${DOCKER_USERNAME}/${IMAGE_NAME}:${TAG}"

# Navigate to repo root (parent of cloud-ingestion/)
cd "$(dirname "$0")/.."

echo "Building ${FULL_IMAGE}..."
docker build -f cloud-ingestion/Dockerfile -t "${FULL_IMAGE}" .

echo "Pushing to Docker Hub..."
docker push "${FULL_IMAGE}"

echo ""
echo "=== Done ==="
echo "Image: ${FULL_IMAGE}"
echo ""
echo "RunPod Setup:"
echo "  1. Create a GPU pod with this image"
echo "  2. Set HUGGINGFACE_HUB_TOKEN in environment"
echo "  3. Upload videos to /workspace/videos"
echo "  4. API available on port 8080"
echo "  5. When done, run: /root/export-db.sh"
