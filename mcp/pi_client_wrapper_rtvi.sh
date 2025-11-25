#!/bin/bash
#
# Wrapper script for Pi RTVI Daily.co client
# Loops forever, waiting for new sessions and restarting client
#

CONFIG_FILE="/home/twistedtv/cinema_config.env"
PYTHON_CLIENT="/home/twistedtv/pi_daily_client_rtvi.py"
VENV_PYTHON="/home/twistedtv/venv_daily/bin/python3"

echo "Cinema Chat Pi Client Wrapper - Starting..."
echo "Waiting for new sessions..."

while true; do
    # Wait for config file to exist (created by dashboard when session starts)
    while [ ! -f "$CONFIG_FILE" ]; do
        sleep 2
    done

    # Source the config and export all variables
    source "$CONFIG_FILE"

    # Export all variables so Python can read them
    export DAILY_ROOM_URL
    export DAILY_TOKEN
    export BACKEND_URL
    export VIDEO_SERVICE_URL="${VIDEO_SERVICE_URL:-http://localhost:5000}"

    echo ""
    echo "=== New Session Starting ==="
    echo "Room URL: ${DAILY_ROOM_URL:-not set}"
    echo "Backend URL: ${BACKEND_URL:-not set}"
    echo "Video Service: ${VIDEO_SERVICE_URL}"
    echo ""

    # Run the Pi RTVI client (will block until session ends)
    $VENV_PYTHON $PYTHON_CLIENT

    echo ""
    echo "=== Session Ended ==="
    echo "Cleaning up and waiting for next session..."

    # Remove config file so we wait for a fresh one
    rm -f "$CONFIG_FILE"

    # Small delay before checking for new session
    sleep 2
done
