#!/bin/bash
# Cleanup and setup script for Cinema Chat video system
# Run this on the Raspberry Pi to fix the video service issues

echo "=== Cinema Chat Video Service Cleanup and Setup ==="
echo ""

# Step 1: Kill all video processes
echo "Step 1: Killing all video processes..."
sudo pkill -9 mpv 2>/dev/null
pkill -9 -f "python.*video" 2>/dev/null
sleep 2

# Step 2: Disable any system services
echo "Step 2: Disabling system services..."
sudo systemctl stop video-playback 2>/dev/null
sudo systemctl disable video-playback 2>/dev/null

# Step 3: Verify everything is stopped
echo "Step 3: Verifying all processes stopped..."
if ps aux | grep -E "(mpv|python.*video)" | grep -v grep; then
    echo "WARNING: Some processes still running!"
else
    echo "✓ All video processes stopped"
fi

# Step 4: Check which video service files exist
echo ""
echo "Step 4: Video service files on system:"
ls -la /home/twistedtv/video_playback*.py 2>/dev/null

echo ""
echo "=== Setup Complete ==="
echo ""
echo "The video service should now be:"
echo "  - OFF when no experience is running (display blank/off)"
echo "  - Started automatically when 'Start Experience' is clicked"
echo "  - Showing static noise when experience is active but no video playing"
echo "  - Stopped automatically when experience ends"
echo ""
echo "To test:"
echo "  1. Reboot the Pi"
echo "  2. Verify display is blank"
echo "  3. Click 'Start Experience' in admin panel"
echo "  4. Static noise should appear immediately"
echo "  5. Video playback should replace static"
echo "  6. Static should resume after video"
echo "  7. End experience - display should go blank again"
