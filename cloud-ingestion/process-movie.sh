#!/bin/bash
# Process a movie on RunPod and import results locally
#
# This script automates the full ingestion pipeline:
#   1. Spins up a GPU pod on RunPod with the goodclips-runpod Docker image
#   2. The pod downloads (URL) or receives (local file) the movie
#   3. The pod transcribes audio, detects scenes, generates embeddings + captions
#   4. Results are exported from the pod's PostgreSQL into the local database
#   5. The SRT sidecar is downloaded from the pod via HTTP
#   6. The video file is ensured locally (downloaded or already present)
#   7. The pod is terminated
#
# Usage:
#   ./cloud-ingestion/process-movie.sh <url_or_file> [title]
#
#   url_or_file: https:// URL  — pod downloads the video directly
#                /local/path   — file is uploaded to the pod from this machine
#   title:       optional display title (default: filename without extension)
#
# Examples:
#   ./cloud-ingestion/process-movie.sh \
#     'https://archive.org/download/carnival_of_souls/carnival_of_souls.mp4'
#
#   ./cloud-ingestion/process-movie.sh /path/to/my_movie.mp4
#   ./cloud-ingestion/process-movie.sh /path/to/my_movie.mp4 'House on the Hill'
#
# Environment variables:
#   RUNPOD_API_KEY  - Your RunPod API key (required; or in cinema_bot/.env)
#   GPU_TYPE        - GPU type (default: NVIDIA RTX A4000)
#   KEEP_POD        - Set to 'true' to keep pod running after completion
#   MOVIE_TITLE     - Video title (default: filename without extension)
#
# Prerequisites:
#   - RUNPOD_API_KEY in environment or in twistedtv-server/cinema_bot/.env
#   - Local PostgreSQL running with goodclips database (via docker compose)
#   - psql client installed locally

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

SOURCE="${1}"
MOVIE_TITLE_ARG="${2:-}"   # optional title; filename is always derived from source

# Detect local file vs remote URL
if [[ "$SOURCE" == http://* ]] || [[ "$SOURCE" == https://* ]]; then
    IS_LOCAL=false
    MOVIE_URL="$SOURCE"
    MOVIE_FILENAME="$(basename "${MOVIE_URL%%\?*}")"
else
    IS_LOCAL=true
    LOCAL_FILE="$(realpath "$SOURCE" 2>/dev/null || echo "$SOURCE")"
    MOVIE_URL=""
    MOVIE_FILENAME="$(basename "$LOCAL_FILE")"
fi

# Title: explicit arg > MOVIE_TITLE env var > filename without extension
MOVIE_TITLE="${MOVIE_TITLE_ARG:-${MOVIE_TITLE:-${MOVIE_FILENAME%.*}}}"
# Auto-source RUNPOD_API_KEY from .env if not already set
if [ -z "$RUNPOD_API_KEY" ]; then
    ENV_FILE="${PROJECT_DIR}/twistedtv-server/cinema_bot/.env"
    if [ -f "$ENV_FILE" ]; then
        RUNPOD_API_KEY=$(grep -E '^RUNPOD_API_KEY=' "$ENV_FILE" | cut -d'=' -f2- | tr -d '"' | tr -d "'")
    fi
fi
RUNPOD_API_KEY="${RUNPOD_API_KEY:-}"
GPU_TYPE="${GPU_TYPE:-NVIDIA RTX A4000}"
DOCKER_IMAGE="${DOCKER_IMAGE:-va55/goodclips-runpod:whisper-transcription}"
VIDEO_DIR="${PROJECT_DIR}/data/videos"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')] WARNING:${NC} $1"; }
error(){ echo -e "${RED}[$(date '+%H:%M:%S')] ERROR:${NC} $1"; exit 1; }
info() { echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $1"; }

# Cleanup function to terminate pod on script exit/error
cleanup() {
    if [ -n "$POD_ID" ] && [ "$KEEP_POD" != "true" ]; then
        warn "Cleaning up - terminating pod $POD_ID..."
        curl -s --max-time 15 --request POST \
          --url "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
          --header 'content-type: application/json' \
          --data '{"query": "mutation { podTerminate(input: {podId: \"'"${POD_ID}"'\"}) }"}' > /dev/null 2>&1
        log "Pod terminated"
    fi
}
trap cleanup EXIT

# ============================================
# Validate prerequisites
# ============================================
if [ -z "$SOURCE" ]; then
    echo "Usage: $0 <url_or_file> [title]"
    echo ""
    echo "  url_or_file: https:// URL  — pod downloads the video directly"
    echo "               /local/path   — file is uploaded to the pod from this machine"
    echo "  title:       optional display title (default: filename without extension)"
    echo ""
    echo "Examples:"
    echo "  $0 'https://archive.org/download/carnival_of_souls/carnival_of_souls.mp4'"
    echo "  $0 /path/to/my_movie.mp4"
    echo "  $0 /path/to/my_movie.mp4 'House on the Hill'"
    echo ""
    echo "Environment variables:"
    echo "  RUNPOD_API_KEY  - Your RunPod API key (required)"
    echo "  GPU_TYPE        - GPU type (default: NVIDIA RTX A4000)"
    echo "  KEEP_POD        - Set to 'true' to keep pod running after completion"
    echo "  MOVIE_TITLE     - Video title (default: filename without extension)"
    exit 1
fi

[ "$IS_LOCAL" = true ] && [ ! -f "$LOCAL_FILE" ] && error "Local file not found: $LOCAL_FILE"

[ -z "$RUNPOD_API_KEY" ] && error "RUNPOD_API_KEY environment variable not set"
which psql > /dev/null 2>&1 || error "psql not installed. Run: sudo dnf install -y postgresql"
which curl > /dev/null 2>&1 || error "curl not installed"

# Verify local PostgreSQL is reachable
PGPASSWORD=goodclips_dev_password psql -h localhost -U goodclips -d goodclips -c "SELECT 1" > /dev/null 2>&1 \
    || error "Cannot connect to local PostgreSQL. Is the goodclips docker compose stack running?"

log "Starting movie processing pipeline"
if [ "$IS_LOCAL" = true ]; then
    log "Source:   $LOCAL_FILE (local file)"
else
    log "Source:   $MOVIE_URL"
fi
log "Filename: $MOVIE_FILENAME"
log "Title:    $MOVIE_TITLE"

# For local files: copy to videos dir now so it's available after processing
if [ "$IS_LOCAL" = true ]; then
    mkdir -p "$VIDEO_DIR"
    VIDEO_LOCAL_COPY="${VIDEO_DIR}/${MOVIE_FILENAME}"
    if [ ! -f "$VIDEO_LOCAL_COPY" ]; then
        log "Copying local file to videos directory..."
        cp "$LOCAL_FILE" "$VIDEO_LOCAL_COPY"
    else
        log "File already in videos directory: $VIDEO_LOCAL_COPY"
    fi
fi

# ============================================
# Step 1: Create RunPod with all required ports
# ============================================
log "Creating RunPod instance..."

POD_RESPONSE=$(curl -s --max-time 60 --request POST \
  --url "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
  --header 'content-type: application/json' \
  --data '{
    "query": "mutation { podFindAndDeployOnDemand(input: { cloudType: SECURE, gpuCount: 1, volumeInGb: 50, containerDiskInGb: 50, gpuTypeId: \"'"${GPU_TYPE}"'\", name: \"goodclips-processor\", imageName: \"'"${DOCKER_IMAGE}"'\", dockerArgs: \"\", ports: \"8080/http,5432/tcp\", volumeMountPath: \"/workspace\", env: [{key: \"AUTO_DOWNLOAD_URL\", value: \"'"${MOVIE_URL}"'\"}, {key: \"AUTO_DOWNLOAD_FILENAME\", value: \"'"${MOVIE_FILENAME}"'\"}, {key: \"AUTO_TITLE\", value: \"'"${MOVIE_TITLE}"'\"}] }) { id machineId } }"
  }')

POD_ID=$(echo "$POD_RESPONSE" | python3 -c "
import sys, json
d = json.load(sys.stdin)
pod = d.get('data',{}).get('podFindAndDeployOnDemand',{})
if pod:
    print(pod.get('id',''))
else:
    errors = d.get('errors', [])
    if errors:
        print('ERROR:' + errors[0].get('message','Unknown error'), file=sys.stderr)
    print('')
" 2>&1)

if [ -z "$POD_ID" ] || [[ "$POD_ID" == ERROR* ]]; then
    echo "Response: $POD_RESPONSE"
    error "Failed to create pod"
fi

log "Pod created: $POD_ID"

# ============================================
# Step 2: Wait for pod to be ready
# ============================================
log "Waiting for pod to be ready..."

API_URL=""
PG_PROXY=""

for i in $(seq 1 60); do
    POD_STATUS=$(curl -s --max-time 15 --request POST \
      --url "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
      --header 'content-type: application/json' \
      --data '{"query": "query { pod(input: {podId: \"'"${POD_ID}"'\"}) { id desiredStatus runtime { uptimeInSeconds ports { ip isIpPublic privatePort publicPort type } } } }"}')

    RUNTIME=$(echo "$POD_STATUS" | python3 -c "
import sys, json
d = json.load(sys.stdin)
r = d.get('data',{}).get('pod',{}).get('runtime')
print('yes' if r else 'no')
" 2>/dev/null)

    if [ "$RUNTIME" = "yes" ]; then
        log "Pod is running!"

        # Extract port info
        # HTTP port uses RunPod proxy, but TCP port (Postgres) needs direct IP
        eval "$(echo "$POD_STATUS" | python3 -c "
import sys, json
d = json.load(sys.stdin)
pod_id = d['data']['pod']['id']
ports = d['data']['pod']['runtime'].get('ports', [])
for p in ports:
    if p['privatePort'] == 8080:
        print(f'API_URL=https://{pod_id}-8080.proxy.runpod.net')
    if p['privatePort'] == 5432:
        ip = p.get('ip', '')
        pub_port = p.get('publicPort', 5432)
        if ip:
            print(f'PG_HOST={ip}')
            print(f'PG_PORT={pub_port}')
        else:
            # Fallback to proxy (may not work for TCP)
            print(f'PG_HOST={pod_id}-5432.proxy.runpod.net')
            print(f'PG_PORT=5432')
" 2>/dev/null)"
        break
    fi

    echo -n "."
    sleep 10
done
echo ""

[ -z "$API_URL" ] && error "Pod never became ready (timed out after 10 minutes)"

PG_PORT="${PG_PORT:-5432}"
log "API endpoint: $API_URL"
log "PostgreSQL: $PG_HOST:$PG_PORT"

# ============================================
# Step 3: Wait for API to be healthy
# ============================================
log "Waiting for GoodCLIPS API to start..."

for i in $(seq 1 30); do
    HEALTH=$(curl -s --max-time 10 "$API_URL/health" 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('status',''))
except:
    print('')
" 2>/dev/null)

    if [ "$HEALTH" = "ok" ]; then
        log "API is healthy"
        break
    fi
    sleep 10
done

[ "$HEALTH" != "ok" ] && error "API never became healthy"

# ============================================
# Step 3b: Upload local file to pod (local-file mode only)
# ============================================
if [ "$IS_LOCAL" = true ]; then
    log "Uploading local file to pod (this may take a while for large files)..."
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        --max-time 3600 \
        -T "$LOCAL_FILE" \
        "$API_URL/api/v1/files/$MOVIE_FILENAME")
    [ "$HTTP_CODE" = "200" ] || error "File upload failed (HTTP $HTTP_CODE)"
    log "Upload complete: $MOVIE_FILENAME"

    # Also upload a sidecar SRT if one already exists alongside the source file
    LOCAL_SRT="${LOCAL_FILE%.*}.srt"
    SRT_FILENAME="${MOVIE_FILENAME%.*}.srt"
    if [ -f "$LOCAL_SRT" ]; then
        log "Uploading SRT sidecar..."
        curl -s -o /dev/null --max-time 60 -T "$LOCAL_SRT" "$API_URL/api/v1/files/$SRT_FILENAME"
        log "SRT uploaded: $SRT_FILENAME"
    fi

    log "Submitting video for processing..."
    curl -s -X POST "$API_URL/api/v1/videos" \
        -H "Content-Type: application/json" \
        -d "{\"filename\": \"${MOVIE_FILENAME}\", \"filepath\": \"/data/videos/${MOVIE_FILENAME}\", \"title\": \"${MOVIE_TITLE}\"}" \
        > /dev/null
    log "Video submitted"
fi

# ============================================
# Step 4: Wait for processing to complete
# ============================================
log "Waiting for video processing..."
log "This takes 30-60 minutes for a full movie"
echo ""

LAST_EMBED_COUNT=0
STALL_COUNT=0
START_TIME=$(date +%s)

while true; do
    sleep 30

    # Get stats and job status
    STATS=$(curl -s --max-time 15 "$API_URL/api/v1/stats" 2>/dev/null || echo "{}")
    JOBS=$(curl -s --max-time 15 "$API_URL/api/v1/jobs" 2>/dev/null || echo '{"jobs":[]}')

    # Get GPU utilization
    GPU_INFO=$(curl -s --max-time 15 --request POST \
      --url "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
      --header 'content-type: application/json' \
      --data '{"query": "query { pod(input: {podId: \"'"${POD_ID}"'\"}) { runtime { gpus { gpuUtilPercent memoryUtilPercent } } } }"}' 2>/dev/null \
      | python3 -c "
import sys, json
try:
    g = json.load(sys.stdin)['data']['pod']['runtime']['gpus'][0]
    print(f\"GPU:{g['gpuUtilPercent']}% MEM:{g['memoryUtilPercent']}%\")
except:
    print('GPU:? MEM:?')
" 2>/dev/null || echo "GPU:? MEM:?")

    # Parse stats
    EMBED_COUNT=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('scenes_with_embeddings',0))" 2>/dev/null || echo 0)
    TOTAL_SCENES=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('total_scenes',0))" 2>/dev/null || echo 0)
    CAPTIONS=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('total_captions',0))" 2>/dev/null || echo 0)

    # Parse all job statuses and surface any failures
    JOB_SUMMARY=$(echo "$JOBS" | python3 -c "
import sys, json
try:
    jobs = json.load(sys.stdin).get('jobs', [])
    parts = []
    for j in jobs:
        t = j.get('type','?').replace('_generation','_gen').replace('_extraction','_ext').replace('_detection','_det').replace('_ingestion','_ingest')
        s = j.get('status','?')
        parts.append(f'{t}:{s}')
    print(' | '.join(parts))
except:
    print('(no jobs)')
" 2>/dev/null || echo "(error)")

    EMBED_STATUS=$(echo "$JOBS" | python3 -c "
import sys, json
try:
    for j in json.load(sys.stdin).get('jobs', []):
        if j.get('type') == 'embedding_generation':
            print(j.get('status',''))
            break
except:
    pass
" 2>/dev/null || true)

    FAILED_JOB=$(echo "$JOBS" | python3 -c "
import sys, json
try:
    for j in json.load(sys.stdin).get('jobs', []):
        if j.get('status') == 'failed':
            err = j.get('error') or j.get('error_message') or '(no error message)'
            print(f\"{j.get('type','?')}: {err}\")
            break
except:
    pass
" 2>/dev/null || true)

    info "  scenes: ${TOTAL_SCENES} | embeds: ${EMBED_COUNT} | captions: ${CAPTIONS} | ${GPU_INFO}"
    info "  jobs: ${JOB_SUMMARY}"

    # Abort immediately on any failed job
    if [ -n "$FAILED_JOB" ]; then
        echo ""
        warn "=== FAILED JOB: ${FAILED_JOB} ==="
        warn "Check pod logs at: https://www.runpod.io/console/pods/${POD_ID}"
        warn "Pod API: ${API_URL}/api/v1/jobs"
        error "A job failed — see details above. Set KEEP_POD=true to inspect the pod."
    fi

    # Check completion
    if [ "$EMBED_STATUS" = "completed" ]; then
        echo ""
        log "All processing complete!"
        break
    fi

    # Stall detection: if GPU is at 0% for too long after initial startup
    if echo "$GPU_INFO" | grep -q "GPU:0%" 2>/dev/null; then
        STALL_COUNT=$((STALL_COUNT + 1))
        if [ "$STALL_COUNT" -ge 10 ] && [ "$EMBED_STATUS" = "running" ]; then
            warn "GPU has been idle for 5+ minutes while job is 'running' - possible stall"
        fi
    else
        STALL_COUNT=0
    fi

    # Safety: 150 min covers download + transcription + full ingestion
    ELAPSED=$(($(date +%s) - START_TIME))
    if [ "$ELAPSED" -gt 9000 ]; then
        error "Processing timed out after 150 minutes"
    fi
done

# ============================================
# Steps 5-8: Export DB, fetch SRT, download video
# ============================================
log "Pulling data from pod..."
RUNPOD_API_KEY="$RUNPOD_API_KEY" \
    "${SCRIPT_DIR}/pull-from-pod.sh" "$POD_ID" "$MOVIE_FILENAME" "$MOVIE_URL"

# Read back counts for the summary below
LOCAL_SCENES=$(PGPASSWORD=goodclips_dev_password psql -h localhost -U goodclips -d goodclips -tA \
    -c "SELECT COUNT(*) FROM scenes s JOIN videos v ON s.video_id = v.id WHERE v.filename = '${MOVIE_FILENAME}'" \
    | tr -d '[:space:]')
LOCAL_CAPTIONS=$(PGPASSWORD=goodclips_dev_password psql -h localhost -U goodclips -d goodclips -tA \
    -c "SELECT COUNT(*) FROM captions c JOIN videos v ON c.video_id = v.id WHERE v.filename = '${MOVIE_FILENAME}'" \
    | tr -d '[:space:]')
SRT_LOCAL="${VIDEO_DIR}/${MOVIE_FILENAME%.*}.srt"

# ============================================
# Step 9: Terminate pod
# ============================================
log "Terminating pod..."
KEEP_POD=false  # Allow cleanup trap to terminate
# Trap will handle termination

log "Done!"
echo ""
echo "=== Summary ==="
echo "  Movie:    $MOVIE_FILENAME"
echo "  Title:    $MOVIE_TITLE"
echo "  Scenes:   $LOCAL_SCENES"
echo "  Captions: $LOCAL_CAPTIONS"
echo "  Video:    ${VIDEO_DIR}/${MOVIE_FILENAME}"
echo "  SRT:      ${SRT_LOCAL}"
echo "  Pod ID:   $POD_ID"
echo ""
echo "Test search: curl -s http://localhost:8080/api/v1/search/semantic -H 'Content-Type: application/json' -d '{\"query\": \"a woman looking scared\", \"limit\": 3}'"
