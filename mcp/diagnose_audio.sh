#!/bin/bash
#
# Audio Diagnostic Script for Raspberry Pi
# Tests all audio-related components before running the Pi Daily client
#

echo "========================================================================"
echo "Cinema Chat - Audio Diagnostics"
echo "========================================================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test 1: Check if running on Pi
echo "Test 1: System Check"
echo "--------------------"
if command -v arecord &> /dev/null; then
    echo -e "${GREEN}✅ ALSA tools available${NC}"
else
    echo -e "${RED}❌ ALSA tools not found. Install with: sudo apt-get install alsa-utils${NC}"
fi
echo ""

# Test 2: List audio devices
echo "Test 2: Available Audio Devices"
echo "--------------------------------"
if command -v arecord &> /dev/null; then
    arecord -l
    echo ""
else
    echo -e "${YELLOW}⚠️  Cannot list devices (arecord not available)${NC}"
    echo ""
fi

# Test 3: Check config file
echo "Test 3: Audio Device Configuration"
echo "-----------------------------------"
CONFIG_FILE="/home/twistedtv/audio_device.conf"
if [ -f "$CONFIG_FILE" ]; then
    DEVICE=$(cat "$CONFIG_FILE")
    echo -e "${GREEN}✅ Config file exists: $CONFIG_FILE${NC}"
    echo "   Selected device: $DEVICE"
else
    echo -e "${YELLOW}⚠️  Config file not found: $CONFIG_FILE${NC}"
    echo "   Will use default device or AUDIO_DEVICE env var"
fi
echo ""

# Test 4: Check environment variable
echo "Test 4: Environment Variables"
echo "------------------------------"
if [ -n "$AUDIO_DEVICE" ]; then
    echo -e "${GREEN}✅ AUDIO_DEVICE env var set: $AUDIO_DEVICE${NC}"
else
    echo -e "${YELLOW}⚠️  AUDIO_DEVICE env var not set${NC}"
fi

if [ -n "$BACKEND_URL" ]; then
    echo -e "${GREEN}✅ BACKEND_URL env var set: $BACKEND_URL${NC}"
else
    echo -e "${YELLOW}⚠️  BACKEND_URL env var not set${NC}"
    echo "   Set with: export BACKEND_URL='http://YOUR_IP:8765/api'"
fi
echo ""

# Test 5: Check Python dependencies
echo "Test 5: Python Dependencies"
echo "----------------------------"
python3 -c "import daily" 2>/dev/null && echo -e "${GREEN}✅ daily-python installed${NC}" || echo -e "${RED}❌ daily-python not installed${NC}"
python3 -c "import httpx" 2>/dev/null && echo -e "${GREEN}✅ httpx installed${NC}" || echo -e "${RED}❌ httpx not installed${NC}"
echo ""

# Test 6: Test audio capture (optional)
echo "Test 6: Quick Audio Capture Test (Optional)"
echo "--------------------------------------------"
echo "Press Enter to record 3 seconds of audio, or Ctrl+C to skip..."
read -r

if command -v arecord &> /dev/null; then
    # Determine which device to use
    TEST_DEVICE="default"
    if [ -f "$CONFIG_FILE" ]; then
        TEST_DEVICE=$(cat "$CONFIG_FILE")
    elif [ -n "$AUDIO_DEVICE" ]; then
        TEST_DEVICE="$AUDIO_DEVICE"
    fi

    echo "Recording 3 seconds from device: $TEST_DEVICE"
    echo "🔴 SPEAK NOW..."

    arecord -D "$TEST_DEVICE" -f S16_LE -r 16000 -c 1 -d 3 /tmp/test_audio.wav 2>&1

    if [ -f /tmp/test_audio.wav ]; then
        FILE_SIZE=$(stat -f%z /tmp/test_audio.wav 2>/dev/null || stat -c%s /tmp/test_audio.wav 2>/dev/null)
        echo ""
        echo "Recording complete! File size: $FILE_SIZE bytes"

        if [ "$FILE_SIZE" -lt 1000 ]; then
            echo -e "${RED}❌ File is very small - microphone may not be working!${NC}"
        else
            echo -e "${GREEN}✅ Recording successful${NC}"

            # Try to play it back
            if command -v aplay &> /dev/null; then
                echo ""
                echo "Playing back recording..."
                aplay /tmp/test_audio.wav 2>&1
            fi
        fi
    else
        echo -e "${RED}❌ Recording failed${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Cannot test audio capture (arecord not available)${NC}"
fi
echo ""

# Summary
echo "========================================================================"
echo "Summary"
echo "========================================================================"
echo ""
echo "Next steps:"
echo "1. If all tests passed, run: python3 pi_daily_client_rtvi.py"
echo "2. If audio device tests failed, check USB connection and permissions"
echo "3. If backend URL not set, configure it with:"
echo "   export BACKEND_URL='http://YOUR_SERVER_IP:8765/api'"
echo ""
echo "For detailed testing guide, see: PI_AUDIO_TESTING.md"
echo ""
