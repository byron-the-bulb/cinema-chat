#!/bin/bash
# Download a video and submit it for processing
# Usage: /root/download-and-process.sh <url> [filename]

set -e

URL="${1}"
FILENAME="${2:-$(basename "$URL")}"
VIDEOS_DIR="/workspace/videos"

if [ -z "$URL" ]; then
    echo "Usage: $0 <url> [filename]"
    echo ""
    echo "Examples:"
    echo "  $0 'https://archive.org/download/night_of_the_living_dead_dvd/Night.mp4' 'notld.mp4'"
    echo "  $0 'https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4'"
    exit 1
fi

mkdir -p "${VIDEOS_DIR}"
cd "${VIDEOS_DIR}"

echo "Downloading: ${URL}"
echo "Saving as: ${FILENAME}"

# Download with user agent and follow redirects (archive.org needs this)
curl -L -A "Mozilla/5.0 (X11; Linux x86_64)" -o "${FILENAME}" "${URL}"

FILEPATH="${VIDEOS_DIR}/${FILENAME}"
FILESIZE=$(stat -c%s "${FILEPATH}" 2>/dev/null || echo "0")

echo ""
echo "Downloaded: ${FILEPATH} (${FILESIZE} bytes)"

# Check if download succeeded (file should be > 1MB for a video)
if [ "${FILESIZE}" -lt 1000000 ]; then
    echo "WARNING: File seems too small. Checking content..."
    head -c 200 "${FILEPATH}"
    echo ""
    echo "Download may have failed. Check the URL and try again."
    exit 1
fi

echo ""

# Submit for processing
echo "Submitting for processing..."
RESPONSE=$(curl -s -X POST http://localhost:8080/api/v1/videos \
  -H "Content-Type: application/json" \
  -d "{\"filename\": \"${FILENAME}\", \"filepath\": \"${FILEPATH}\"}")

echo "Response: ${RESPONSE}"
echo ""
echo "Check status with: curl -s http://localhost:8080/api/v1/jobs | python3 -m json.tool"
