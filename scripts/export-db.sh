#!/bin/bash
# Export the goodclips database for download
# Run this on RunPod when processing is complete

WORKSPACE="${WORKSPACE:-/workspace}"
EXPORT_DIR="${WORKSPACE}/exports"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DUMP_FILE="${EXPORT_DIR}/goodclips_${TIMESTAMP}.sql"

mkdir -p "${EXPORT_DIR}"

# Update video statuses before export
echo "Updating video statuses..."
PGPASSWORD=goodclips_dev_password psql -h localhost -U goodclips -d goodclips -c \
    "UPDATE videos SET status='completed' WHERE scene_count > 0 AND status='processing';"

# Show summary
echo ""
echo "=== Database Summary ==="
PGPASSWORD=goodclips_dev_password psql -h localhost -U goodclips -d goodclips -c \
    "SELECT id, filename, scene_count, status FROM videos WHERE id > 1;"
echo ""
PGPASSWORD=goodclips_dev_password psql -h localhost -U goodclips -d goodclips -c \
    "SELECT COUNT(*) as total_scenes, COUNT(visual_embedding) as with_embeddings FROM scenes;"
echo ""

echo "Exporting goodclips database..."
PGPASSWORD=goodclips_dev_password pg_dump \
    -h localhost \
    -U goodclips \
    -d goodclips \
    --no-owner \
    --no-acl \
    -f "${DUMP_FILE}"

echo "Compressing..."
gzip "${DUMP_FILE}"

echo ""
echo "=== Export Complete ==="
echo "File: ${DUMP_FILE}.gz"
echo "Size: $(du -h "${DUMP_FILE}.gz" | cut -f1)"
echo ""
echo "Download via RunPod file browser or:"
echo "  runpodctl receive ${DUMP_FILE}.gz"
echo ""
echo "To restore locally:"
echo "  gunzip goodclips_${TIMESTAMP}.sql.gz"
echo "  psql -h localhost -U goodclips -d goodclips -f goodclips_${TIMESTAMP}.sql"
