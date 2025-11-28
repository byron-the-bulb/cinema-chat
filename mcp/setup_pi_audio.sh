#!/bin/bash
#
# Setup script for Raspberry Pi USB phone audio
# Run this once to configure the USB audio adapter for Cinema Chat
#

echo "========================================="
echo "Cinema Chat - Pi Audio Setup"
echo "========================================="
echo ""

# Check if USB audio device is present
if ! arecord -l | grep -q "USB Audio Device"; then
    echo "❌ ERROR: USB Audio Device not found!"
    echo ""
    echo "Please check:"
    echo "  1. USB phone adapter is plugged in"
    echo "  2. Run 'lsusb' to see if device is detected"
    echo "  3. Run 'arecord -l' to list audio devices"
    exit 1
fi

echo "✅ USB Audio Device found"
echo ""

# Unmute and set microphone volume
echo "Setting microphone volume..."
amixer -c 1 set 'Mic' 100% unmute
amixer -c 1 set 'Mic' cap

# Set capture volume
amixer -c 1 set 'Mic' 100% cap

# Optional: Enable auto gain control
# Uncomment if audio is too quiet or variable
# amixer -c 1 set 'Auto Gain Control' on

# Save settings
echo "Saving ALSA settings..."
sudo alsactl store 1

echo ""
echo "========================================="
echo "✅ Audio setup complete!"
echo "========================================="
echo ""
echo "Mixer settings:"
amixer -c 1 sget 'Mic'
echo ""

# Test recording
echo "Testing microphone (3 seconds)..."
echo "Please speak into the phone..."
sleep 1
arecord -D plughw:1,0 -d 3 -f S16_LE -r 16000 -c 1 test_mic.wav 2>/dev/null

# Check if audio was captured
if [ -f test_mic.wav ]; then
    size=$(stat -f%z test_mic.wav 2>/dev/null || stat -c%s test_mic.wav 2>/dev/null)
    if [ "$size" -gt 50000 ]; then
        echo "✅ Microphone test PASSED ($size bytes captured)"

        # Analyze with sox if available
        if command -v sox &> /dev/null; then
            max_amp=$(sox test_mic.wav -n stat 2>&1 | grep "Maximum amplitude" | awk '{print $3}')
            echo "   Maximum amplitude: $max_amp"

            if (( $(echo "$max_amp > 0.1" | bc -l) )); then
                echo "   ✅ Audio level is good!"
            else
                echo "   ⚠️  Audio level is low - speak louder or adjust gain"
            fi
        fi
    else
        echo "❌ Microphone test FAILED - no audio captured"
        echo "   File size: $size bytes (expected > 50000)"
    fi
    rm -f test_mic.wav
fi

echo ""
echo "Configuration saved. The Pi Daily.co client will use:"
echo "  Device: plughw:1,0"
echo "  Sample Rate: Auto (16kHz via resampling)"
echo "  Mic Volume: 100%"
echo "  Mic Playback: Unmuted"
echo ""
echo "To restore these settings after reboot:"
echo "  sudo alsactl restore 1"
echo ""
