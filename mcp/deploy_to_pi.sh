#!/bin/bash
#
# Deploy updated Pi client files to Raspberry Pi
#

# Configuration
PI_USER="twistedtv"
PI_HOST="${PI_HOST:-raspberrypi.local}"  # Override with env var if needed
PI_PATH="/home/twistedtv/cinema-chat/mcp"

echo "========================================================================"
echo "Deploying Cinema Chat Pi Client"
echo "========================================================================"
echo ""
echo "Target: $PI_USER@$PI_HOST:$PI_PATH"
echo ""

# Check if we can reach the Pi
echo "Testing connection to Pi..."
if ! ping -c 1 -W 2 "$PI_HOST" > /dev/null 2>&1; then
    echo "❌ Cannot reach Pi at $PI_HOST"
    echo ""
    echo "Set PI_HOST environment variable if using different hostname/IP:"
    echo "  export PI_HOST=192.168.1.XXX"
    echo ""
    exit 1
fi
echo "✅ Pi is reachable"
echo ""

# Files to sync
FILES=(
    "pi_daily_client_audio_sender.py"
    "pi_daily_client_rtvi.py"
    "requirements.txt"
    "test_audio_config.py"
    "diagnose_audio.sh"
)

echo "Syncing files to Pi..."
echo "--------------------"

for file in "${FILES[@]}"; do
    echo "  → $file"
    scp "$file" "$PI_USER@$PI_HOST:$PI_PATH/" || {
        echo "❌ Failed to copy $file"
        exit 1
    }
done

echo ""
echo "✅ All files synced successfully!"
echo ""

# Optionally install dependencies
read -p "Install/update Python dependencies on Pi? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "Installing dependencies on Pi..."
    echo "================================"

    ssh "$PI_USER@$PI_HOST" << 'ENDSSH'
        cd ~/cinema-chat/mcp

        # Install portaudio (needed for pyaudio)
        echo "Installing portaudio19-dev..."
        sudo apt-get update -qq
        sudo apt-get install -y portaudio19-dev

        # Install Python packages
        echo ""
        echo "Installing Python packages..."
        pip3 install -r requirements.txt

        echo ""
        echo "✅ Dependencies installed"
ENDSSH

    if [ $? -eq 0 ]; then
        echo ""
        echo "✅ Dependencies installation complete"
    else
        echo ""
        echo "⚠️  Dependency installation had errors (check output above)"
    fi
fi

echo ""
echo "========================================================================"
echo "Deployment Complete!"
echo "========================================================================"
echo ""
echo "Next steps on the Pi:"
echo ""
echo "1. SSH to the Pi:"
echo "   ssh $PI_USER@$PI_HOST"
echo ""
echo "2. Run diagnostics:"
echo "   cd ~/cinema-chat/mcp"
echo "   ./diagnose_audio.sh"
echo ""
echo "3. Start the audio sender client:"
echo "   export BACKEND_URL='http://YOUR_SERVER_IP:8765/api'"
echo "   python3 pi_daily_client_audio_sender.py"
echo ""
