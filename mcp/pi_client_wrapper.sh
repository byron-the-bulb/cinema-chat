#!/bin/bash
#
# Wrapper script for Pi Daily.co client
# Reads room URL from config file and starts the client
#

CONFIG_FILE="/home/twistedtv/cinema_config.env"

# Wait for config file to exist (created by Next.js when session starts)
echo "Waiting for session configuration..."
while [ ! -f "$CONFIG_FILE" ]; do
    sleep 2
done

# Source the config
source "$CONFIG_FILE"

# Check if DAILY_ROOM_URL is set
if [ -z "$DAILY_ROOM_URL" ]; then
    echo "Error: DAILY_ROOM_URL not set in $CONFIG_FILE"
    exit 1
fi

echo "Starting Cinema Chat Pi client..."
echo "Room URL: $DAILY_ROOM_URL"

# Run the Pi client
exec /home/twistedtv/venv_daily/bin/python3 /home/twistedtv/pi_daily_client_simple.py
