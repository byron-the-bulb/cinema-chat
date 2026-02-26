#!/bin/bash
# End-to-end ingestion pipeline test
#
# Builds the Docker image, processes a short test clip through the real
# ingestion pipeline on RunPod, imports results locally, shows a summary,
# and plays sample clips for manual inspection.
#
# Usage:
#   ./cloud-ingestion/test-pipeline.sh [--keep] [--no-build]
#
# Flags:
#   --keep      Don't delete test data from local DB after inspection
#   --no-build  Skip Docker build/push (reuse existing test image)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# --- Test clip configuration ---
# Short public domain cartoon with dialogue (~6 min). Change URL to test a different clip.
TEST_URL="https://archive.org/download/Popeye_forPresident/Popeye_forPresident_512kb.mp4"
TEST_FILENAME="__test_clip__.mp4"

# --- Parse flags ---
KEEP=false
NO_BUILD=false
for arg in "$@"; do
    case "$arg" in
        --keep)     KEEP=true ;;
        --no-build) NO_BUILD=true ;;
        *)          echo "Unknown flag: $arg"; exit 1 ;;
    esac
done

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'
log()  { echo -e "${GREEN}[test]${NC} $1"; }
info() { echo -e "${BLUE}[test]${NC} $1"; }
warn() { echo -e "${YELLOW}[test]${NC} $1"; }

# DB helper — runs a query against local goodclips database
db() {
    PGPASSWORD=goodclips_dev_password psql -h localhost -U goodclips -d goodclips -tA -c "$1"
}

TAG="test-$(git -C "$PROJECT_DIR" rev-parse --short HEAD)"

# ============================================
# Step 1: Build & push Docker image
# ============================================
if [ "$NO_BUILD" = "false" ]; then
    log "Building Docker image va55/goodclips-runpod:${TAG}..."
    DOCKER_USERNAME=va55 TAG="$TAG" "$SCRIPT_DIR/build.sh"
else
    log "Skipping build (--no-build), using va55/goodclips-runpod:${TAG}"
fi

# ============================================
# Step 2: Run the real ingestion pipeline
# ============================================
log "Running ingestion pipeline with test clip..."
export DOCKER_IMAGE="va55/goodclips-runpod:${TAG}"
"$SCRIPT_DIR/process-movie.sh" "$TEST_URL" "$TEST_FILENAME"

# ============================================
# Step 3: Terminal bell
# ============================================
echo -e '\a'

# ============================================
# Step 4: Query & display results
# ============================================
SCENE_COUNT=$(db "
    SELECT COUNT(*) FROM scenes s
    JOIN videos v ON s.video_id = v.id
    WHERE v.filename = '${TEST_FILENAME}'" | tr -d '[:space:]')

WHISPER_COUNT=$(db "
    SELECT COUNT(*) FROM captions c
    JOIN videos v ON c.video_id = v.id
    WHERE v.filename = '${TEST_FILENAME}' AND c.language = 'en'" | tr -d '[:space:]')

IV2_COUNT=$(db "
    SELECT COUNT(*) FROM captions c
    JOIN videos v ON c.video_id = v.id
    WHERE v.filename = '${TEST_FILENAME}' AND c.language = 'iv2'" | tr -d '[:space:]')

echo ""
echo "=== Test Results ==="
echo "  Scenes:       ${SCENE_COUNT}"
echo "  Whisper (en): ${WHISPER_COUNT}"
echo "  Visual (iv2): ${IV2_COUNT}"
echo ""

# Sample transcription lines (3 evenly spaced)
echo "  Sample dialogue:"
SAMPLES=$(db "
    WITH numbered AS (
        SELECT c.text, c.start_time,
               ROW_NUMBER() OVER (ORDER BY c.start_time) AS rn,
               COUNT(*) OVER () AS total
        FROM captions c
        JOIN videos v ON c.video_id = v.id
        WHERE v.filename = '${TEST_FILENAME}' AND c.language = 'en'
    )
    SELECT '    ['
        || LPAD(FLOOR(start_time / 60)::int::text, 2, '0') || ':'
        || LPAD((FLOOR(start_time)::int % 60)::text, 2, '0')
        || '] \"' || LEFT(text, 80) || '\"'
    FROM numbered
    WHERE rn IN (GREATEST(total / 4, 1), GREATEST(total / 2, 2), GREATEST(total * 3 / 4, 3))
    ORDER BY start_time
    LIMIT 3;
" 2>/dev/null)

if [ -n "$SAMPLES" ]; then
    echo "$SAMPLES"
else
    echo "    (no transcription lines found)"
fi

echo ""

# ============================================
# Step 5: Wait for keypress
# ============================================
read -n1 -rsp "Press any key to play 3 sample clips..."
echo ""

# ============================================
# Step 6: Play 3 evenly-spaced sample clips
# ============================================
VIDEO_ID=$(db "SELECT id FROM videos WHERE filename = '${TEST_FILENAME}'" | tr -d '[:space:]')
VIDEO_PATH="${PROJECT_DIR}/data/videos/${TEST_FILENAME}"

if [ -n "$VIDEO_ID" ] && [ -f "$VIDEO_PATH" ]; then
    CLIPS=$(db "
        WITH numbered AS (
            SELECT scene_index, start_time, end_time,
                   ROW_NUMBER() OVER (ORDER BY scene_index) AS rn,
                   COUNT(*) OVER () AS total
            FROM scenes WHERE video_id = ${VIDEO_ID}
        )
        SELECT scene_index || '|' || start_time || '|' || LEAST(end_time - start_time, 30)
        FROM numbered
        WHERE rn IN (1, GREATEST(total / 2, 1), total)
        ORDER BY scene_index;
    ")

    while IFS='|' read -r idx start dur; do
        [ -z "$idx" ] && continue
        start_fmt=$(python3 -c "s=$start; print(f'{int(s)//60}:{int(s)%60:02d}')")
        end_fmt=$(python3 -c "s=$start+$dur; print(f'{int(s)//60}:{int(s)%60:02d}')")
        info "Playing scene ${idx} (${start_fmt}-${end_fmt})..."
        ffplay -autoexit -loglevel warning -ss "$start" -t "$dur" "$VIDEO_PATH" 2>/dev/null \
            || warn "ffplay failed or not available"
    done <<< "$CLIPS"
else
    warn "Video file not found at ${VIDEO_PATH}, skipping playback"
fi

echo ""

# ============================================
# Step 7: Cleanup (unless --keep)
# ============================================
if [ "$KEEP" = "true" ]; then
    log "Keeping test data in local DB (--keep flag)"
else
    log "Cleaning up test data from local DB..."
    PGPASSWORD=goodclips_dev_password psql -h localhost -U goodclips -d goodclips -c \
        "DELETE FROM videos WHERE filename = '${TEST_FILENAME}';" > /dev/null
    if [ -f "$VIDEO_PATH" ]; then
        rm "$VIDEO_PATH"
        log "Removed ${VIDEO_PATH}"
    fi
    log "Cleaned up test data."
fi

log "Done!"
