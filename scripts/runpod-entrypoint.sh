#!/bin/bash
set -e

# RunPod persistent storage directory
WORKSPACE="${WORKSPACE:-/workspace}"
PGDATA="/var/lib/postgresql/14/main"
REDIS_DIR="${WORKSPACE}/redis"
VIDEOS_DIR="${WORKSPACE}/videos"
PG_BACKUP="${WORKSPACE}/postgres_backup.sql"

echo "=== GoodCLIPS RunPod Entrypoint ==="
echo "Workspace: ${WORKSPACE}"

# Create directories
mkdir -p "${REDIS_DIR}" "${VIDEOS_DIR}"

# ============================================
# PostgreSQL Setup
# ============================================
echo "Setting up PostgreSQL..."

# Check if this is first run (marker file in /workspace)
INIT_MARKER="${WORKSPACE}/.pg_initialized"

if [ ! -f "${INIT_MARKER}" ]; then
    echo "First run - initializing PostgreSQL..."

    # Clear any pre-existing data from apt install
    rm -rf "${PGDATA}"
    mkdir -p "${PGDATA}"
    chown -R postgres:postgres /var/lib/postgresql
    chmod 700 "${PGDATA}"

    # Initialize as postgres user
    cd /tmp && su postgres -c "/usr/lib/postgresql/14/bin/initdb -D ${PGDATA}"

    # Configure for remote access
    echo "listen_addresses = '*'" >> "${PGDATA}/postgresql.conf"
    echo "host all all 0.0.0.0/0 md5" >> "${PGDATA}/pg_hba.conf"
    touch "${INIT_MARKER}"
    INIT_DB=true
else
    echo "PostgreSQL already initialized"
    # Ensure permissions are correct
    chown -R postgres:postgres /var/lib/postgresql 2>/dev/null || true
    INIT_DB=false
fi

# Start PostgreSQL as postgres user
echo "Starting PostgreSQL..."
cd /tmp && su postgres -c "/usr/lib/postgresql/14/bin/pg_ctl -D ${PGDATA} -l /var/lib/postgresql/postgresql.log start"

# Wait for PostgreSQL
echo "Waiting for PostgreSQL..."
for i in {1..30}; do
    if cd /tmp && su postgres -c "/usr/lib/postgresql/14/bin/pg_isready" > /dev/null 2>&1; then
        echo "PostgreSQL is ready"
        break
    fi
    sleep 1
done

if [ "$INIT_DB" = true ]; then
    echo "Creating database and user..."
    cd /tmp && su postgres -c "psql" <<EOF
CREATE USER goodclips WITH PASSWORD 'goodclips_dev_password';
CREATE DATABASE goodclips OWNER goodclips;
GRANT ALL PRIVILEGES ON DATABASE goodclips TO goodclips;
EOF

    # Create extensions as superuser
    echo "Creating extensions..."
    cd /tmp && su postgres -c "psql -d goodclips" <<EOF
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
GRANT ALL ON ALL TABLES IN SCHEMA public TO goodclips;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO goodclips;
EOF

    # Check if we have a backup to restore
    if [ -f "${PG_BACKUP}" ]; then
        echo "Restoring from backup..."
        PGPASSWORD=goodclips_dev_password psql -h localhost -U goodclips -d goodclips -f "${PG_BACKUP}"
    else
        echo "Running fresh migrations..."
        PGPASSWORD=goodclips_dev_password psql -h localhost -U goodclips -d goodclips -f /root/migrations/init.sql
    fi
    echo "Database initialized"
elif [ -f "${PG_BACKUP}" ]; then
    # Existing DB but check if we need to restore backup (e.g., after pod restart)
    echo "Checking for backup restore..."
fi

# ============================================
# Redis Setup
# ============================================
echo "Setting up Redis..."
cat > "${REDIS_DIR}/redis.conf" <<EOF
dir ${REDIS_DIR}
dbfilename dump.rdb
appendonly yes
bind 0.0.0.0
port 6379
EOF

redis-server "${REDIS_DIR}/redis.conf" --daemonize yes

for i in {1..30}; do
    if redis-cli ping > /dev/null 2>&1; then
        echo "Redis is ready"
        break
    fi
    sleep 1
done

# ============================================
# Environment
# ============================================
export DB_HOST="${DB_HOST:-localhost}"
export DB_PORT="${DB_PORT:-5432}"
export DB_USER="${DB_USER:-goodclips}"
export DB_PASSWORD="${DB_PASSWORD:-goodclips_dev_password}"
export DB_NAME="${DB_NAME:-goodclips}"
export DB_SSLMODE="${DB_SSLMODE:-disable}"
export REDIS_URL="${REDIS_URL:-redis://localhost:6379}"
export IV2_DEVICE="${IV2_DEVICE:-cuda:0}"
export CLIP_DEVICE="${CLIP_DEVICE:-cuda:0}"
export EMBEDDING_BACKEND="${EMBEDDING_BACKEND:-internvl35}"
export IV2_MODEL_ID="${IV2_MODEL_ID:-OpenGVLab/InternVL3_5-2B}"
export IV2_FRAMES="${IV2_FRAMES:-8}"
export IV2_STRIDE="${IV2_STRIDE:-4}"
export IV2_RES="${IV2_RES:-448}"
export CLIP_MODEL_ID="${CLIP_MODEL_ID:-openai/clip-vit-base-patch32}"
export ENABLE_AUDIO_EMBEDDINGS="${ENABLE_AUDIO_EMBEDDINGS:-false}"
export SCENEDETECT_TIMEOUT_SECS="${SCENEDETECT_TIMEOUT_SECS:-300}"
export KEYFRAME_TIMEOUT_SECS="${KEYFRAME_TIMEOUT_SECS:-60}"
export HF_HOME="${WORKSPACE}/huggingface"
mkdir -p "${HF_HOME}"

ln -sfn "${VIDEOS_DIR}" /data/videos 2>/dev/null || mkdir -p /data/videos

echo ""
echo "=== Ready ==="
echo "IV2_DEVICE: ${IV2_DEVICE}"
echo "Videos: ${VIDEOS_DIR}"
echo "DB Backup: ${PG_BACKUP}"
echo ""
echo "To backup database before stopping: /root/export-db.sh"
echo ""

# ============================================
# Auto-download function (runs in background)
# ============================================
auto_download_video() {
    AUTO_DOWNLOAD_URL="${AUTO_DOWNLOAD_URL:-}"
    AUTO_DOWNLOAD_FILENAME="${AUTO_DOWNLOAD_FILENAME:-video.mp4}"

    if [ -z "${AUTO_DOWNLOAD_URL}" ]; then
        return
    fi

    FILEPATH="${VIDEOS_DIR}/${AUTO_DOWNLOAD_FILENAME}"

    if [ -f "${FILEPATH}" ]; then
        echo "[Auto-download] Video already exists: ${FILEPATH}"
        return
    fi

    echo "[Auto-download] Waiting for API to be ready..."
    for i in {1..60}; do
        if curl -s http://localhost:8080/health > /dev/null 2>&1; then
            echo "[Auto-download] API is ready"
            break
        fi
        sleep 2
    done

    echo "[Auto-download] Downloading: ${AUTO_DOWNLOAD_URL}"
    curl -L -A "Mozilla/5.0 (X11; Linux x86_64)" -o "${FILEPATH}" "${AUTO_DOWNLOAD_URL}"

    FILESIZE=$(stat -c%s "${FILEPATH}" 2>/dev/null || echo "0")
    echo "[Auto-download] Downloaded: ${FILESIZE} bytes"

    if [ "${FILESIZE}" -gt 1000000 ]; then
        echo "[Auto-download] Submitting for processing..."
        curl -s -X POST http://localhost:8080/api/v1/videos \
            -H "Content-Type: application/json" \
            -d "{\"filename\": \"${AUTO_DOWNLOAD_FILENAME}\", \"filepath\": \"${FILEPATH}\"}"
        echo "[Auto-download] Video submitted!"
    else
        echo "[Auto-download] WARNING: Download failed (file too small)"
        cat "${FILEPATH}"
    fi
}

# ============================================
# Start GoodCLIPS
# ============================================
RUN_MODE="${RUN_MODE:-both}"

case "$RUN_MODE" in
    worker)
        exec /root/goodclips worker
        ;;
    api)
        exec /root/goodclips
        ;;
    both)
        # Start API in background
        /root/goodclips &

        # Start auto-download in background (if URL provided)
        auto_download_video &

        # Start worker in foreground
        exec /root/goodclips worker
        ;;
    shell)
        exec /bin/bash
        ;;
esac
