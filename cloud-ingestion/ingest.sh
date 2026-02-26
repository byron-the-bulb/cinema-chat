#!/bin/bash
# One-command movie ingestion wrapper
#
# Usage:
#   ./cloud-ingestion/ingest.sh              # process all un-ingested movies
#   ./cloud-ingestion/ingest.sh movie.mp4    # process one specific movie from the list

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONF_FILE="${SCRIPT_DIR}/movies.conf"
VIDEO_DIR="${PROJECT_DIR}/data/videos"
ENV_FILE="${PROJECT_DIR}/twistedtv-server/cinema_bot/.env"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[ingest]${NC} $1"; }
warn() { echo -e "${YELLOW}[ingest]${NC} $1"; }
error(){ echo -e "${RED}[ingest] ERROR:${NC} $1"; exit 1; }

# Auto-source RUNPOD_API_KEY from .env if not already set
if [ -z "$RUNPOD_API_KEY" ]; then
    if [ -f "$ENV_FILE" ]; then
        RUNPOD_API_KEY=$(grep -E '^RUNPOD_API_KEY=' "$ENV_FILE" | cut -d'=' -f2- | tr -d '"' | tr -d "'")
        export RUNPOD_API_KEY
        [ -n "$RUNPOD_API_KEY" ] && log "Loaded RUNPOD_API_KEY from .env"
    fi
    [ -z "$RUNPOD_API_KEY" ] && error "RUNPOD_API_KEY not set and not found in $ENV_FILE"
fi

[ -f "$CONF_FILE" ] || error "Movie list not found: $CONF_FILE"

FILTER="${1:-}"
PROCESSED=0
SKIPPED=0

while IFS= read -r line || [ -n "$line" ]; do
    # Skip comments and blank lines
    line="$(echo "$line" | sed 's/#.*//' | xargs)"
    [ -z "$line" ] && continue

    FILENAME="$(echo "$line" | awk '{print $1}')"
    URL="$(echo "$line" | awk '{print $2}')"

    [ -z "$FILENAME" ] || [ -z "$URL" ] && continue

    # If a specific movie was requested, skip others
    if [ -n "$FILTER" ] && [ "$FILENAME" != "$FILTER" ]; then
        continue
    fi

    # Skip already-ingested movies
    if [ -f "${VIDEO_DIR}/${FILENAME}" ]; then
        log "Skipping ${FILENAME} (already in data/videos/)"
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    log "Processing: ${FILENAME}"
    "${SCRIPT_DIR}/process-movie.sh" "$URL" "$FILENAME"
    PROCESSED=$((PROCESSED + 1))

done < "$CONF_FILE"

if [ -n "$FILTER" ] && [ "$PROCESSED" -eq 0 ] && [ "$SKIPPED" -eq 0 ]; then
    error "${FILTER} not found in ${CONF_FILE}"
fi

echo ""
log "Done! Processed: ${PROCESSED}, Skipped: ${SKIPPED}"
