#!/bin/bash
# Process a movie on RunPod and import results locally
# Usage: ./scripts/process-movie.sh <movie_url> [filename]
#
# Prerequisites:
#   - RUNPOD_API_KEY environment variable set
#   - Local PostgreSQL running with goodclips database
#   - SSH key at ~/.ssh/id_ed25519

set -e

MOVIE_URL="${1}"
MOVIE_FILENAME="${2:-movie.mp4}"
RUNPOD_API_KEY="${RUNPOD_API_KEY:-}"
GPU_TYPE="${GPU_TYPE:-NVIDIA RTX A4000}"
DOCKER_IMAGE="va55/goodclips-runpod:latest"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')] WARNING:${NC} $1"; }
error() { echo -e "${RED}[$(date '+%H:%M:%S')] ERROR:${NC} $1"; exit 1; }

# Check prerequisites
if [ -z "$MOVIE_URL" ]; then
    echo "Usage: $0 <movie_url> [filename]"
    echo ""
    echo "Examples:"
    echo "  $0 'https://archive.org/download/night_of_the_living_dead_dvd/Night.mp4' 'notld.mp4'"
    echo ""
    echo "Environment variables:"
    echo "  RUNPOD_API_KEY  - Your RunPod API key (required)"
    echo "  GPU_TYPE        - GPU type (default: NVIDIA RTX A4000)"
    exit 1
fi

if [ -z "$RUNPOD_API_KEY" ]; then
    error "RUNPOD_API_KEY environment variable not set"
fi

log "Starting movie processing pipeline"
log "Movie URL: $MOVIE_URL"
log "Filename: $MOVIE_FILENAME"

# ============================================
# Step 1: Create RunPod
# ============================================
log "Creating RunPod instance..."

POD_RESPONSE=$(curl -s --request POST \
  --url "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
  --header 'content-type: application/json' \
  --data '{
    "query": "mutation { podFindAndDeployOnDemand(input: { cloudType: SECURE, gpuCount: 1, volumeInGb: 50, containerDiskInGb: 50, gpuTypeId: \"'"${GPU_TYPE}"'\", name: \"goodclips-processor\", imageName: \"'"${DOCKER_IMAGE}"'\", dockerArgs: \"\", ports: \"8080/http\", volumeMountPath: \"/workspace\", env: [{key: \"AUTO_DOWNLOAD_URL\", value: \"'"${MOVIE_URL}"'\"}, {key: \"AUTO_DOWNLOAD_FILENAME\", value: \"'"${MOVIE_FILENAME}"'\"}] }) { id machineId } }"
  }')

POD_ID=$(echo "$POD_RESPONSE" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('data',{}).get('podFindAndDeployOnDemand',{}).get('id',''))" 2>/dev/null)

if [ -z "$POD_ID" ]; then
    echo "Response: $POD_RESPONSE"
    error "Failed to create pod"
fi

log "Pod created: $POD_ID"

# ============================================
# Step 2: Wait for pod to be ready
# ============================================
log "Waiting for pod to be ready..."

for i in {1..60}; do
    POD_STATUS=$(curl -s --request POST \
      --url "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
      --header 'content-type: application/json' \
      --data '{"query": "query { pod(input: {podId: \"'"${POD_ID}"'\"}) { id desiredStatus runtime { uptimeInSeconds ports { ip isIpPublic privatePort publicPort type } } } }"}')

    RUNTIME=$(echo "$POD_STATUS" | python3 -c "import sys, json; d=json.load(sys.stdin); r=d.get('data',{}).get('pod',{}).get('runtime'); print('yes' if r else 'no')" 2>/dev/null)

    if [ "$RUNTIME" = "yes" ]; then
        log "Pod is running!"

        # Extract SSH connection info
        SSH_INFO=$(echo "$POD_STATUS" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ports = d.get('data',{}).get('pod',{}).get('runtime',{}).get('ports',[])
for p in ports:
    if p.get('privatePort') == 22:
        print(f\"{p.get('ip')}:{p.get('publicPort')}\")
        break
" 2>/dev/null)
        break
    fi

    echo -n "."
    sleep 10
done
echo ""

if [ -z "$SSH_INFO" ]; then
    warn "Could not get SSH info, will use API to monitor"
fi

# ============================================
# Step 3: Wait for processing to complete
# ============================================
log "Waiting for video processing to complete..."
log "This may take 30-60 minutes for a full movie..."

# Get the public HTTP endpoint
HTTP_PORT=$(echo "$POD_STATUS" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ports = d.get('data',{}).get('pod',{}).get('runtime',{}).get('ports',[])
for p in ports:
    if p.get('privatePort') == 8080:
        print(f\"https://{d.get('data',{}).get('pod',{}).get('id')}-8080.proxy.runpod.net\")
        break
" 2>/dev/null)

log "API endpoint: $HTTP_PORT"

# Poll for job completion
LAST_STATUS=""
while true; do
    sleep 30

    JOBS=$(curl -s "${HTTP_PORT}/api/v1/jobs" 2>/dev/null || echo "{}")

    # Check if embedding_generation is complete
    EMBEDDING_STATUS=$(echo "$JOBS" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    jobs = d.get('jobs', [])
    for j in jobs:
        if j.get('type') == 'embedding_generation' and j.get('payload',{}).get('video_id') == 2:
            print(j.get('status'))
            break
except:
    print('waiting')
" 2>/dev/null)

    if [ "$EMBEDDING_STATUS" != "$LAST_STATUS" ]; then
        log "Embedding job status: $EMBEDDING_STATUS"
        LAST_STATUS="$EMBEDDING_STATUS"
    fi

    if [ "$EMBEDDING_STATUS" = "completed" ]; then
        log "Processing complete!"
        break
    fi

    if [ "$EMBEDDING_STATUS" = "failed" ]; then
        error "Processing failed!"
    fi
done

# ============================================
# Step 4: Export and download database
# ============================================
log "Exporting database..."

# Trigger export via SSH or API
# For now, we'll need to SSH in
SSH_HOST=$(echo "$SSH_INFO" | cut -d: -f1)
SSH_PORT=$(echo "$SSH_INFO" | cut -d: -f2)

if [ -n "$SSH_HOST" ] && [ -n "$SSH_PORT" ]; then
    log "Running export via SSH..."
    ssh -o StrictHostKeyChecking=no -p "$SSH_PORT" -i ~/.ssh/id_ed25519 "root@${SSH_HOST}" "/root/export-db.sh"

    log "Downloading database export..."
    EXPORT_FILE=$(ssh -o StrictHostKeyChecking=no -p "$SSH_PORT" -i ~/.ssh/id_ed25519 "root@${SSH_HOST}" "ls -t /workspace/exports/*.gz | head -1")
    scp -o StrictHostKeyChecking=no -P "$SSH_PORT" -i ~/.ssh/id_ed25519 "root@${SSH_HOST}:${EXPORT_FILE}" ./

    LOCAL_FILE=$(basename "$EXPORT_FILE")
    log "Downloaded: $LOCAL_FILE"
else
    warn "Could not SSH - please manually export the database"
    warn "Run on the pod: /root/export-db.sh"
    warn "Then download /workspace/exports/*.gz"
    read -p "Press Enter when you've downloaded the export file, then enter filename: " LOCAL_FILE
fi

# ============================================
# Step 5: Import into local database
# ============================================
if [ -f "$LOCAL_FILE" ]; then
    log "Importing into local database..."

    gunzip -k "$LOCAL_FILE" 2>/dev/null || true
    SQL_FILE="${LOCAL_FILE%.gz}"

    # Import (adjust connection params as needed)
    PGPASSWORD=goodclips_dev_password psql -h localhost -U goodclips -d goodclips -f "$SQL_FILE"

    log "Import complete!"
else
    warn "No export file found - skipping import"
fi

# ============================================
# Step 6: Terminate pod
# ============================================
read -p "Terminate the RunPod? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    log "Terminating pod..."
    curl -s --request POST \
      --url "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
      --header 'content-type: application/json' \
      --data '{"query": "mutation { podTerminate(input: {podId: \"'"${POD_ID}"'\"}) }"}'
    log "Pod terminated"
fi

log "Done!"
echo ""
echo "=== Summary ==="
echo "Movie: $MOVIE_FILENAME"
echo "Database export: $LOCAL_FILE"
echo "Pod ID: $POD_ID"
