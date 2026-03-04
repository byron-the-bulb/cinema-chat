#!/bin/bash
# Run embedding generation on a separate RunPod pod.
#
# This is Phase 2 of the two-pod pipeline:
#   Pod 1 (process-movie.sh with SKIP_EMBEDDINGS=true):
#       scene_detection + caption_extraction + clip_generation → export to server
#   Pod 2 (this script):
#       import DB from server → embedding_generation only → export back to server
#
# Separating the two phases avoids the OOM problem where Lighthouse (clip_gen)
# and InternVL (embedding_gen) compete for system RAM on the same pod, killing
# PostgreSQL.
#
# Usage:
#   ./cloud-ingestion/run-embeddings.sh <movie-filename>
#
# Example:
#   ./cloud-ingestion/run-embeddings.sh Flubber.mp4
#
# Environment variables:
#   RUNPOD_API_KEY  - Your RunPod API key (required; or in cinema_bot/.env)
#   GPU_TYPE        - GPU type (default: NVIDIA GeForce RTX 3090)
#   DOCKER_IMAGE    - Docker image (default: same as process-movie.sh)
#   KEEP_POD        - Set to 'true' to keep pod running after completion

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VIDEO_DIR="${PROJECT_DIR}/data/videos"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')] WARNING:${NC} $1"; }
error(){ echo -e "${RED}[$(date '+%H:%M:%S')] ERROR:${NC} $1"; exit 1; }
info() { echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $1"; }

MOVIE_FILENAME="${1}"
[ -z "$MOVIE_FILENAME" ] && error "Usage: $0 <movie-filename>"

# Source API key from .env if not set
if [ -z "$RUNPOD_API_KEY" ]; then
    ENV_FILE="${PROJECT_DIR}/twistedtv-server/cinema_bot/.env"
    if [ -f "$ENV_FILE" ]; then
        RUNPOD_API_KEY=$(grep -E '^RUNPOD_API_KEY=' "$ENV_FILE" | cut -d= -f2- | tr -d '"' | tr -d "'")
    fi
fi
[ -z "$RUNPOD_API_KEY" ] && error "RUNPOD_API_KEY not set"

# Verify movie exists in local DB
LOCAL_VID=$(PGPASSWORD=goodclips_dev_password psql -h localhost -U goodclips -d goodclips -tA \
    -c "SELECT id FROM videos WHERE filename = '${MOVIE_FILENAME}'" | tr -d '[:space:]')
[ -z "$LOCAL_VID" ] && error "Movie '${MOVIE_FILENAME}' not found in local database. Run process-movie.sh first."

LOCAL_CLIPS=$(PGPASSWORD=goodclips_dev_password psql -h localhost -U goodclips -d goodclips -tA \
    -c "SELECT COUNT(*) FROM clips WHERE video_id = ${LOCAL_VID}" | tr -d '[:space:]')
[ "$LOCAL_CLIPS" = "0" ] && error "No clips found for '${MOVIE_FILENAME}'. Run process-movie.sh with SKIP_EMBEDDINGS=true first."

log "Movie: ${MOVIE_FILENAME} (video_id=${LOCAL_VID}, ${LOCAL_CLIPS} clips)"

GPU_TYPE="${GPU_TYPE:-NVIDIA GeForce RTX 3090}"
DOCKER_IMAGE="${DOCKER_IMAGE:-va55/goodclips-runpod:clips2}"

# ============================================
# Step 1: Create RunPod (no auto-download — embeddings only)
# ============================================
log "Creating RunPod instance (${GPU_TYPE})..."

POD_RESPONSE=$(curl -s --max-time 60 --request POST \
  --url "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
  --header 'content-type: application/json' \
  --data '{
    "query": "mutation { podFindAndDeployOnDemand(input: { cloudType: SECURE, gpuCount: 1, volumeInGb: 50, containerDiskInGb: 50, gpuTypeId: \"'"${GPU_TYPE}"'\", name: \"goodclips-embeddings\", imageName: \"'"${DOCKER_IMAGE}"'\", dockerArgs: \"\", ports: \"8080/http,5432/tcp\", volumeMountPath: \"/workspace\" }) { id machineId } }"
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

# Cleanup trap — terminate pod on exit (unless KEEP_POD=true)
cleanup() {
    if [ "$KEEP_POD" = "true" ]; then
        warn "KEEP_POD=true — pod $POD_ID left running"
    elif [ -n "$POD_ID" ]; then
        log "Terminating pod $POD_ID..."
        curl -s --max-time 30 --request POST \
          --url "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
          --header 'content-type: application/json' \
          --data '{"query": "mutation { podTerminate(input: { podId: \"'"${POD_ID}"'\" }) }"}' > /dev/null 2>&1
        log "Pod terminated"
    fi
}
trap cleanup EXIT

# ============================================
# Step 2: Wait for pod + API
# ============================================
log "Waiting for pod to be ready..."

API_URL=""
for i in $(seq 1 120); do
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
" 2>/dev/null)"
        [ -n "$API_URL" ] && break
        echo -n "p"
    else
        echo -n "."
    fi
    sleep 10
done
echo ""

[ -z "$API_URL" ] && error "Pod never became ready"
PG_PORT="${PG_PORT:-5432}"
log "API: $API_URL"
log "PostgreSQL: $PG_HOST:$PG_PORT"

log "Waiting for API to be healthy..."
for i in $(seq 1 60); do
    HEALTH=$(curl -s --max-time 10 "$API_URL/health" 2>/dev/null \
        | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || true)
    [ "$HEALTH" = "ok" ] && break
    sleep 5
done
[ "$HEALTH" != "ok" ] && error "API never became healthy"
log "API is healthy"

# ============================================
# Step 3: Push local DB to pod (video + scenes + captions + clips)
# ============================================
log "Pushing local database to pod..."

EXPORT_DIR=$(mktemp -d)

# Export video
PGPASSWORD=goodclips_dev_password psql -h localhost -U goodclips -d goodclips \
    -c "\copy (SELECT filename, file_hash, title, duration, scene_count, caption_count, embedding_model, status, filepath FROM videos WHERE id = ${LOCAL_VID}) TO '${EXPORT_DIR}/video.tsv'"

# Export scenes
PGPASSWORD=goodclips_dev_password psql -h localhost -U goodclips -d goodclips \
    -c "\copy (SELECT id, scene_index, start_time, end_time, has_captions, caption_count, created_at FROM scenes WHERE video_id = ${LOCAL_VID} ORDER BY id) TO '${EXPORT_DIR}/scenes.tsv'"

# Export captions
PGPASSWORD=goodclips_dev_password psql -h localhost -U goodclips -d goodclips \
    -c "\copy (SELECT id, scene_id, start_time, end_time, text, language, confidence, created_at FROM captions WHERE video_id = ${LOCAL_VID} ORDER BY id) TO '${EXPORT_DIR}/captions.tsv'"

# Export clips (without embeddings — those will be generated on the pod)
PGPASSWORD=goodclips_dev_password psql -h localhost -U goodclips -d goodclips \
    -c "\copy (SELECT id, clip_type, source_scene_id, source_caption_id, start_time, end_time, label, salience_score, metadata, created_at FROM clips WHERE video_id = ${LOCAL_VID} ORDER BY id) TO '${EXPORT_DIR}/clips.tsv'"

EXPORT_SCENES=$(wc -l < "${EXPORT_DIR}/scenes.tsv")
EXPORT_CAPTIONS=$(wc -l < "${EXPORT_DIR}/captions.tsv")
EXPORT_CLIPS=$(wc -l < "${EXPORT_DIR}/clips.tsv")
log "Exported: ${EXPORT_SCENES} scenes, ${EXPORT_CAPTIONS} captions, ${EXPORT_CLIPS} clips"

# Import into pod DB. The video filepath on the pod is /data/videos/<filename>.
PGPASSWORD=goodclips_dev_password psql -h "$PG_HOST" -p "$PG_PORT" -U goodclips -d goodclips << IMPORT_SQL
-- Clean slate for this movie on the pod
DELETE FROM videos WHERE filename = '${MOVIE_FILENAME}';

-- Insert video
CREATE TEMP TABLE _stg_video (
    filename text, file_hash text, title text, duration real,
    scene_count int, caption_count int, embedding_model text,
    status text, filepath text
);
\copy _stg_video FROM '${EXPORT_DIR}/video.tsv'

INSERT INTO videos (uuid, filename, filepath, file_hash, title, duration,
    scene_count, caption_count, embedding_model, status)
SELECT uuid_generate_v4(), filename, '/data/videos/' || filename,
    file_hash, title, duration, scene_count, caption_count,
    embedding_model, 'processing'
FROM _stg_video
RETURNING id AS new_vid \gset

-- Import scenes with ID mapping
CREATE TEMP TABLE _stg_scenes (
    remote_id int, scene_index int, start_time real, end_time real,
    has_captions bool, caption_count int, created_at timestamptz
);
\copy _stg_scenes FROM '${EXPORT_DIR}/scenes.tsv'

CREATE TEMP TABLE _scene_map AS
WITH inserted AS (
    INSERT INTO scenes (uuid, video_id, scene_index, start_time, end_time,
        has_captions, caption_count, created_at)
    SELECT uuid_generate_v4(), :new_vid, scene_index, start_time, end_time,
        has_captions, caption_count, created_at
    FROM _stg_scenes ORDER BY remote_id
    RETURNING id, scene_index
)
SELECT s.remote_id, i.id AS local_id
FROM inserted i JOIN _stg_scenes s USING (scene_index);

-- Import captions with scene ID remapping
CREATE TEMP TABLE _stg_captions (
    remote_id int, remote_scene_id int, start_time real, end_time real,
    text text, language varchar(10), confidence real, created_at timestamptz
);
\copy _stg_captions FROM '${EXPORT_DIR}/captions.tsv'

INSERT INTO captions (uuid, video_id, scene_id, start_time, end_time,
    text, language, confidence, created_at)
SELECT uuid_generate_v4(), :new_vid, sm.local_id,
    c.start_time, c.end_time, c.text, c.language, c.confidence, c.created_at
FROM _stg_captions c
LEFT JOIN _scene_map sm ON c.remote_scene_id = sm.remote_id;

-- Import clips (no embeddings — those will be generated)
CREATE TEMP TABLE _stg_clips (
    remote_id int, clip_type varchar(16),
    remote_scene_id int, remote_caption_id int,
    start_time real, end_time real, label text, salience_score real,
    metadata jsonb, created_at timestamptz
);
\copy _stg_clips FROM '${EXPORT_DIR}/clips.tsv'

INSERT INTO clips (uuid, video_id, clip_type, source_scene_id,
    start_time, end_time, label, salience_score, metadata, created_at)
SELECT uuid_generate_v4(), :new_vid, cl.clip_type, sm.local_id,
    cl.start_time, cl.end_time, cl.label, cl.salience_score,
    cl.metadata, cl.created_at
FROM _stg_clips cl
LEFT JOIN _scene_map sm ON cl.remote_scene_id = sm.remote_id
ON CONFLICT (video_id, clip_type, start_time, end_time) DO NOTHING;

SELECT 'Imported video_id=' || :new_vid AS result;
IMPORT_SQL

rm -rf "$EXPORT_DIR"

# Get the video ID on the pod
POD_VID=$(PGPASSWORD=goodclips_dev_password psql -h "$PG_HOST" -p "$PG_PORT" \
    -U goodclips -d goodclips -tA \
    -c "SELECT id FROM videos WHERE filename = '${MOVIE_FILENAME}'" | tr -d '[:space:]')
log "Pod video_id: ${POD_VID}"

POD_CLIPS=$(PGPASSWORD=goodclips_dev_password psql -h "$PG_HOST" -p "$PG_PORT" \
    -U goodclips -d goodclips -tA \
    -c "SELECT COUNT(*) FROM clips WHERE video_id = ${POD_VID}" | tr -d '[:space:]')
log "Pod has ${POD_CLIPS} clips ready for embedding"

# ============================================
# Step 4: Upload video file to pod (needed for keyframe extraction during embedding)
# ============================================
VIDEO_LOCAL="${VIDEO_DIR}/${MOVIE_FILENAME}"
if [ -f "$VIDEO_LOCAL" ]; then
    # Get upload URL (direct TCP on port 9000)
    UPLOAD_URL=""
    eval "$(echo "$POD_STATUS" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ports = d['data']['pod']['runtime'].get('ports', [])
for p in ports:
    if p['privatePort'] == 9000 and p.get('ip'):
        print(f'UPLOAD_URL=http://{p[\"ip\"]}:{p[\"publicPort\"]}')
" 2>/dev/null)"
    UPLOAD_URL="${UPLOAD_URL:-$API_URL}"

    FILESIZE=$(stat -c%s "$VIDEO_LOCAL" 2>/dev/null || echo "0")
    log "Uploading video to pod ($(numfmt --to=iec $FILESIZE 2>/dev/null || echo "${FILESIZE} bytes"))..."
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        --max-time 3600 \
        -T "$VIDEO_LOCAL" \
        "$UPLOAD_URL/api/v1/files/$MOVIE_FILENAME")
    [ "$HTTP_CODE" = "200" ] || warn "File upload returned HTTP $HTTP_CODE (embedding may still work if pod has cached files)"
    log "Upload complete"
else
    warn "Video file not found locally: $VIDEO_LOCAL"
    warn "Embeddings may fail if the pod cannot access the video"
fi

# ============================================
# Step 5: Enqueue embedding_generation job
# ============================================
log "Enqueuing embedding_generation job..."
curl -s -X POST "$API_URL/api/v1/jobs" \
    -H "Content-Type: application/json" \
    -d "{\"type\": \"embedding_generation\", \"payload\": {\"video_id\": ${POD_VID}}}" \
    > /dev/null
log "Job enqueued"

# ============================================
# Step 6: Wait for embedding completion
# ============================================
log "Waiting for embedding generation..."
echo ""

START_TIME=$(date +%s)

while true; do
    sleep 30

    JOBS=$(curl -s --max-time 15 "$API_URL/api/v1/jobs" 2>/dev/null || echo '{"jobs":[]}')
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

    JOB_SUMMARY=$(echo "$JOBS" | python3 -c "
import sys, json
try:
    jobs = json.load(sys.stdin).get('jobs', [])
    parts = []
    for j in jobs:
        t = j.get('type','?').replace('_generation','_gen')
        s = j.get('status','?')
        parts.append(f'{t}:{s}')
    print(' | '.join(parts) if parts else '(no jobs)')
except:
    print('(error)')
" 2>/dev/null || echo "(error)")

    # Check embedding counts
    EMBED_INFO=$(PGPASSWORD=goodclips_dev_password psql -h "$PG_HOST" -p "$PG_PORT" \
        -U goodclips -d goodclips -tA \
        -c "SELECT COUNT(*) FILTER (WHERE visual_embedding IS NOT NULL) AS visual,
                   COUNT(*) FILTER (WHERE clip_embedding IS NOT NULL) AS clip,
                   COUNT(*) FILTER (WHERE text_embedding IS NOT NULL) AS text,
                   COUNT(*) FILTER (WHERE dialog_embedding IS NOT NULL) AS dialog
            FROM clips WHERE video_id = ${POD_VID}" 2>/dev/null | tr -d '[:space:]' || echo "?|?|?|?")

    info "  embeddings: vis=${EMBED_INFO} | ${GPU_INFO}"
    info "  jobs: ${JOB_SUMMARY}"

    ALL_STATUS=$(echo "$JOBS" | python3 -c "
import sys, json
try:
    jobs = json.load(sys.stdin).get('jobs', [])
    if not jobs:
        print('no_jobs')
    else:
        failed = [j for j in jobs if j.get('status') == 'failed']
        if failed:
            err = failed[0].get('error') or '(no details)'
            print(f\"failed:{err}\")
        elif all(j.get('status') == 'completed' for j in jobs):
            print('all_done')
        else:
            print('running')
except:
    print('error')
" 2>/dev/null || echo "error")

    if [[ "$ALL_STATUS" == failed:* ]]; then
        warn "=== FAILED: ${ALL_STATUS#failed:} ==="
        error "Embedding job failed"
    fi

    if [ "$ALL_STATUS" = "all_done" ]; then
        echo ""
        log "Embedding generation complete!"
        break
    fi

    ELAPSED=$(($(date +%s) - START_TIME))
    if [ "$ELAPSED" -gt 7200 ]; then
        error "Timed out after 120 minutes"
    fi
done

# ============================================
# Step 7: Pull updated data back to server
# ============================================
log "Pulling embeddings back to server..."
RUNPOD_API_KEY="$RUNPOD_API_KEY" \
    "${SCRIPT_DIR}/pull-from-pod.sh" "$POD_ID" "$MOVIE_FILENAME"

# Final check
FINAL_CLIPS=$(PGPASSWORD=goodclips_dev_password psql -h localhost -U goodclips -d goodclips -tA \
    -c "SELECT COUNT(*) FILTER (WHERE visual_embedding IS NOT NULL) AS visual,
               COUNT(*) FILTER (WHERE clip_embedding IS NOT NULL) AS clip,
               COUNT(*) FILTER (WHERE text_embedding IS NOT NULL) AS text,
               COUNT(*) FILTER (WHERE dialog_embedding IS NOT NULL) AS dialog
        FROM clips cl JOIN videos v ON cl.video_id = v.id
        WHERE v.filename = '${MOVIE_FILENAME}'" | tr -d '[:space:]')

log "Done!"
echo ""
echo "=== Summary ==="
echo "  Movie:      $MOVIE_FILENAME"
echo "  Embeddings: $FINAL_CLIPS (visual|clip|text|dialog)"
echo "  Pod ID:     $POD_ID"
echo ""
