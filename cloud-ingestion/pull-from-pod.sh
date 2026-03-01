#!/bin/bash
# Pull processed movie data from a running RunPod instance to the local machine.
#
# What this does:
#   1. Queries RunPod API for the pod's direct PostgreSQL IP and HTTP API URL
#   2. Exports the movie's scenes, captions, and metadata via direct TCP pg \copy
#      (the HTTP proxy cannot carry PostgreSQL traffic — direct TCP is required)
#   3. Imports into the local PostgreSQL database with ID remapping
#   4. Downloads the Whisper SRT sidecar via the HTTP API
#   5. Optionally downloads the video file from a source URL
#
# The video is NOT downloaded from the pod — supply MOVIE_URL if you need it
# fetched. If you already have the file locally, omit it.
#
# Usage:
#   RUNPOD_API_KEY=rpa_... ./cloud-ingestion/pull-from-pod.sh \
#       <pod-id> <movie-filename> [movie-url]
#
# Examples:
#   # DB + SRT only (video already local or will be fetched separately):
#   RUNPOD_API_KEY=rpa_... ./cloud-ingestion/pull-from-pod.sh \
#       abc123def carnival_of_souls.mp4
#
#   # DB + SRT + video from Archive.org:
#   RUNPOD_API_KEY=rpa_... ./cloud-ingestion/pull-from-pod.sh \
#       abc123def carnival_of_souls.mp4 \
#       'https://archive.org/download/carnival_of_souls/carnival_of_souls.mp4'
#
#   # Night of the Living Dead:
#   RUNPOD_API_KEY=rpa_... ./cloud-ingestion/pull-from-pod.sh \
#       abc123def notld.mp4 \
#       'https://archive.org/download/night_of_the_living_dead_dvd/Night.mp4'
#
# Prerequisites:
#   - RUNPOD_API_KEY environment variable
#   - psql installed locally
#   - Local PostgreSQL running (docker compose up)

set -e

POD_ID="${1}"
MOVIE_FILENAME="${2}"
MOVIE_URL="${3:-}"

RUNPOD_API_KEY="${RUNPOD_API_KEY:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VIDEO_DIR="${PROJECT_DIR}/data/videos"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')] WARNING:${NC} $1"; }
error(){ echo -e "${RED}[$(date '+%H:%M:%S')] ERROR:${NC} $1"; exit 1; }
info() { echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $1"; }

if [ -z "$POD_ID" ] || [ -z "$MOVIE_FILENAME" ]; then
    echo "Usage: $0 <pod-id> <movie-filename> [movie-url]"
    echo ""
    echo "Examples:"
    echo "  $0 abc123def carnival_of_souls.mp4"
    echo "  $0 abc123def notld.mp4 'https://archive.org/download/night_of_the_living_dead_dvd/Night.mp4'"
    exit 1
fi

[ -z "$RUNPOD_API_KEY" ] && error "RUNPOD_API_KEY not set"
which psql > /dev/null 2>&1 || error "psql not installed. Run: sudo dnf install -y postgresql"

PGPASSWORD=goodclips_dev_password psql -h localhost -U goodclips -d goodclips -c "SELECT 1" > /dev/null 2>&1 \
    || error "Cannot connect to local PostgreSQL. Is the goodclips docker compose stack running?"

log "Pod:   $POD_ID"
log "Movie: $MOVIE_FILENAME"
[ -n "$MOVIE_URL" ] && log "URL:   $MOVIE_URL"

# ============================================
# Step 1: Get pod connection details
# ============================================
log "Getting pod connection details from RunPod API..."

POD_STATUS=$(curl -s --max-time 15 --request POST \
  --url "https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}" \
  --header 'content-type: application/json' \
  --data '{"query": "query { pod(input: {podId: \"'"${POD_ID}"'\"}) { id desiredStatus runtime { uptimeInSeconds ports { ip isIpPublic privatePort publicPort type } } } }"}')

eval "$(echo "$POD_STATUS" | python3 -c "
import sys, json
d = json.load(sys.stdin)
pod = d.get('data', {}).get('pod', {})
rt = pod.get('runtime') or {}
ports = rt.get('ports', [])
for p in ports:
    if p['privatePort'] == 8080:
        print(f'API_URL=https://{pod[\"id\"]}-8080.proxy.runpod.net')
    if p['privatePort'] == 5432:
        ip = p.get('ip', '')
        pub_port = p.get('publicPort', 5432)
        if ip:
            print(f'PG_HOST={ip}')
            print(f'PG_PORT={pub_port}')
" 2>/dev/null)"

[ -z "$API_URL" ]  && error "Could not get pod API URL. Is the pod running with port 8080 exposed?"
[ -z "$PG_HOST" ]  && error "Could not get PostgreSQL host. Is port 5432/tcp exposed on the pod?"
PG_PORT="${PG_PORT:-5432}"

log "API:        $API_URL"
log "PostgreSQL: $PG_HOST:$PG_PORT"

# ============================================
# Step 2: Verify API is reachable
# ============================================
HEALTH=""
for i in $(seq 1 10); do
    HEALTH=$(curl -s --max-time 10 "$API_URL/health" 2>/dev/null \
        | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || true)
    [ "$HEALTH" = "ok" ] && break
    sleep 3
done
[ "$HEALTH" != "ok" ] && error "API is not responding at $API_URL"

# ============================================
# Step 3: Export movie data from RunPod via PostgreSQL TCP
# ============================================
log "Exporting movie data from RunPod PostgreSQL..."

REMOTE_VID=$(PGPASSWORD=goodclips_dev_password psql -h "$PG_HOST" -p "$PG_PORT" \
    -U goodclips -d goodclips -tA \
    -c "SELECT id FROM videos WHERE filename = '${MOVIE_FILENAME}'" | tr -d '[:space:]')

[ -z "$REMOTE_VID" ] && error "Movie '${MOVIE_FILENAME}' not found in RunPod database. Is processing complete?"
log "Remote video ID: $REMOTE_VID"

EXPORT_DIR=$(mktemp -d)
trap 'rm -rf "$EXPORT_DIR"' EXIT

PGPASSWORD=goodclips_dev_password psql -h "$PG_HOST" -p "$PG_PORT" -U goodclips -d goodclips \
    -c "\copy (SELECT uuid, filename, file_hash, title, duration, scene_count, caption_count, embedding_model, created_at, updated_at, last_processed_at, tags, status, metadata, error_message FROM videos WHERE id = ${REMOTE_VID}) TO '${EXPORT_DIR}/video.tsv'"

PGPASSWORD=goodclips_dev_password psql -h "$PG_HOST" -p "$PG_PORT" -U goodclips -d goodclips \
    -c "\copy (SELECT id, uuid, scene_index, start_time, end_time, has_captions, caption_count, visual_embedding, text_embedding, audio_embedding, visual_clip_embedding, combined_embedding, created_at FROM scenes WHERE video_id = ${REMOTE_VID} ORDER BY id) TO '${EXPORT_DIR}/scenes.tsv'"

PGPASSWORD=goodclips_dev_password psql -h "$PG_HOST" -p "$PG_PORT" -U goodclips -d goodclips \
    -c "\copy (SELECT uuid, scene_id, start_time, end_time, text, language, confidence, created_at FROM captions WHERE video_id = ${REMOTE_VID} ORDER BY id) TO '${EXPORT_DIR}/captions.tsv'"

EXPORT_SCENES=$(wc -l < "${EXPORT_DIR}/scenes.tsv")
EXPORT_CAPTIONS=$(wc -l < "${EXPORT_DIR}/captions.tsv")
log "Exported: ${EXPORT_SCENES} scenes, ${EXPORT_CAPTIONS} captions"

# ============================================
# Step 4: Import into local database
# ============================================
log "Importing into local PostgreSQL..."

# Remove any previous import of this movie (CASCADE clears scenes + captions)
PGPASSWORD=goodclips_dev_password psql -h localhost -U goodclips -d goodclips \
    -c "DELETE FROM videos WHERE filename = '${MOVIE_FILENAME}';" 2>/dev/null || true

PGPASSWORD=goodclips_dev_password psql -h localhost -U goodclips -d goodclips << IMPORT_SQL
CREATE TEMP TABLE _stg_video (
    uuid uuid, filename text, file_hash text, title text, duration real,
    scene_count int, caption_count int, embedding_model text,
    created_at timestamptz, updated_at timestamptz, last_processed_at timestamptz,
    tags jsonb, status text, metadata jsonb, error_message text
);
CREATE TEMP TABLE _stg_scenes (
    remote_id int, uuid uuid, scene_index int, start_time real, end_time real,
    has_captions bool, caption_count int,
    visual_embedding vector(1024), text_embedding vector(768),
    audio_embedding vector(512), visual_clip_embedding vector(512),
    combined_embedding vector(768), created_at timestamptz
);
CREATE TEMP TABLE _stg_captions (
    uuid uuid, remote_scene_id int, start_time real, end_time real,
    text text, language varchar(10), confidence real, created_at timestamptz
);

\copy _stg_video   FROM '${EXPORT_DIR}/video.tsv'
\copy _stg_scenes  FROM '${EXPORT_DIR}/scenes.tsv'
\copy _stg_captions FROM '${EXPORT_DIR}/captions.tsv'

INSERT INTO videos (uuid, filename, filepath, file_hash, title, duration, scene_count,
    caption_count, embedding_model, created_at, updated_at, last_processed_at,
    tags, status, metadata, error_message)
SELECT uuid_generate_v4(), filename, '${VIDEO_DIR}/' || filename,
    md5(filename || now()::text), title, duration, scene_count,
    caption_count, embedding_model, created_at, updated_at, last_processed_at,
    tags, 'completed', metadata, error_message
FROM _stg_video
RETURNING id AS new_vid_id \gset

CREATE TEMP TABLE _scene_map AS
WITH inserted AS (
    INSERT INTO scenes (uuid, video_id, scene_index, start_time, end_time,
        has_captions, caption_count, visual_embedding, text_embedding,
        audio_embedding, visual_clip_embedding, combined_embedding, created_at)
    SELECT uuid_generate_v4(), :new_vid_id, scene_index, start_time, end_time,
        has_captions, caption_count, visual_embedding, text_embedding,
        audio_embedding, visual_clip_embedding, combined_embedding, created_at
    FROM _stg_scenes ORDER BY remote_id
    RETURNING id, scene_index
)
SELECT s.remote_id, i.id AS local_id
FROM inserted i JOIN _stg_scenes s USING (scene_index);

INSERT INTO captions (uuid, video_id, scene_id, start_time, end_time,
    text, language, confidence, created_at)
SELECT uuid_generate_v4(), :new_vid_id, m.local_id,
    c.start_time, c.end_time, c.text, c.language, c.confidence, c.created_at
FROM _stg_captions c
LEFT JOIN _scene_map m ON c.remote_scene_id = m.remote_id;
IMPORT_SQL

LOCAL_SCENES=$(PGPASSWORD=goodclips_dev_password psql -h localhost -U goodclips -d goodclips -tA \
    -c "SELECT COUNT(*) FROM scenes s JOIN videos v ON s.video_id = v.id WHERE v.filename = '${MOVIE_FILENAME}'" \
    | tr -d '[:space:]')
LOCAL_CAPTIONS=$(PGPASSWORD=goodclips_dev_password psql -h localhost -U goodclips -d goodclips -tA \
    -c "SELECT COUNT(*) FROM captions c JOIN videos v ON c.video_id = v.id WHERE v.filename = '${MOVIE_FILENAME}'" \
    | tr -d '[:space:]')
log "Import complete: ${LOCAL_SCENES} scenes, ${LOCAL_CAPTIONS} captions"

# ============================================
# Step 5: Download SRT sidecar via HTTP API
# ============================================
SRT_FILENAME="${MOVIE_FILENAME%.*}.srt"
SRT_LOCAL="${VIDEO_DIR}/${SRT_FILENAME}"
mkdir -p "$VIDEO_DIR"

if [ -f "${SRT_LOCAL}" ]; then
    log "SRT already exists locally: ${SRT_LOCAL}"
else
    log "Fetching SRT sidecar via HTTP API..."
    HTTP_CODE=$(curl -s -o "${SRT_LOCAL}" -w "%{http_code}" \
        "${API_URL}/api/v1/files/${SRT_FILENAME}")
    if [ "$HTTP_CODE" = "200" ]; then
        SRT_SIZE=$(stat -c%s "${SRT_LOCAL}" 2>/dev/null || echo "0")
        log "Downloaded ${SRT_FILENAME} ($(numfmt --to=iec ${SRT_SIZE} 2>/dev/null || echo ${SRT_SIZE} bytes))"
    else
        warn "SRT not available (HTTP ${HTTP_CODE}) — film may have no dialog track"
        rm -f "${SRT_LOCAL}"
        SRT_LOCAL="(none)"
    fi
fi

# ============================================
# Step 6: Download video from source URL (optional)
# ============================================
VIDEO_LOCAL="${VIDEO_DIR}/${MOVIE_FILENAME}"

if [ -f "${VIDEO_LOCAL}" ]; then
    log "Video already exists locally: ${VIDEO_LOCAL}"
elif [ -n "$MOVIE_URL" ]; then
    log "Downloading video from source URL..."
    curl -L -A "Mozilla/5.0 (X11; Linux x86_64)" \
        --progress-bar \
        -o "${VIDEO_LOCAL}" \
        "${MOVIE_URL}"
    FILESIZE=$(stat -c%s "${VIDEO_LOCAL}" 2>/dev/null || echo "0")
    log "Downloaded ${MOVIE_FILENAME} ($(numfmt --to=iec ${FILESIZE} 2>/dev/null || echo ${FILESIZE} bytes))"
else
    warn "No MOVIE_URL provided and video not found locally."
    info "Fetch it separately:"
    info "  curl -L -o ${VIDEO_LOCAL} <source-url>"
fi

log "Done."
echo ""
echo "=== Summary ==="
echo "  Pod:      $POD_ID  (still running — terminate manually if done)"
echo "  Movie:    $MOVIE_FILENAME"
echo "  Scenes:   $LOCAL_SCENES"
echo "  Captions: $LOCAL_CAPTIONS"
echo "  SRT:      $SRT_LOCAL"
echo "  Video:    $VIDEO_LOCAL"
echo ""
echo "Test: curl -s http://localhost:8080/api/v1/search/text -H 'Content-Type: application/json' \\"
echo "  -d '{\"query\": \"I don'\''t want to die\", \"limit\": 3}'"
