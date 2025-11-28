# Raspberry Pi Audio Testing Guide

This guide explains how to test and verify that the Pi Daily client is properly sending audio to the backend.

## What We Fixed

### Issue
The Pi Daily client was not sending audio - the `userIsSpeaking` indicator never activated and no transcriptions appeared in the conversation log.

### Root Causes Fixed

1. **Incorrect Daily SDK configuration structure**
   - Was using: `"microphone": True`
   - Fixed to: `"microphone": {"isEnabled": True, "settings": {"deviceId": "hw:1,0"}}`

2. **Missing audio device selection**
   - Pi client wasn't reading the device selected in the admin panel
   - Added code to read from `/home/twistedtv/audio_device.conf`
   - Falls back to `AUDIO_DEVICE` environment variable

### Files Modified

- [mcp/pi_daily_client_rtvi.py](mcp/pi_daily_client_rtvi.py)
  - Added `get_audio_device()` function (lines 30-46)
  - Updated `call_client.join()` with correct structure (lines 266-290)
  - Now reads device from config file and passes to Daily SDK

## Testing Steps

### 1. Verify Audio Device Configuration

Run the audio config test script:
```bash
cd /home/va55/code/cinema-chat/mcp
python3 test_audio_config.py
```

This will show:
- Whether the config file exists
- What device will be selected
- Validation of the device format

### 2. Check Available Audio Devices

On the Raspberry Pi, list available audio input devices:
```bash
arecord -l
```

Example output:
```
card 1: Device [USB Audio Device], device 0: USB Audio [USB Audio]
```

This means the device ID is `hw:1,0` (card 1, device 0).

### 3. Set Audio Device via Admin Panel

1. Open the Next.js admin panel in browser
2. Find the "Pi Microphone Device" selector
3. Select the correct USB audio device
4. This will write to `/home/twistedtv/audio_device.conf`

Verify it was set:
```bash
cat /home/twistedtv/audio_device.conf
# Should show something like: hw:1,0
```

### 4. Test Raw Audio Capture

Before testing the full system, verify the microphone works:
```bash
cd /home/va55/code/cinema-chat/mcp
python3 test_pi_audio.py
```

This will:
- List all audio devices
- Record 5 seconds of audio
- Analyze the recording
- Play it back

If you hear your voice clearly, the microphone is working!

### 5. Test the Pi Daily Client

Start the backend server (on the server or Pi):
```bash
cd /home/va55/code/cinema-chat/cinema-bot-app/backend
python3 src/cinema-bot/server.py
```

In another terminal, start the Pi Daily client:
```bash
cd /home/va55/code/cinema-chat/mcp
export BACKEND_URL="http://192.168.1.143:8765/api"
python3 pi_daily_client_rtvi.py
```

Look for these log messages:
```
Using audio device from config file: hw:1,0
Joining room: https://...
Audio device: hw:1,0
✅ Joined Daily.co room
🎤 Streaming phone audio to bot
```

### 6. Verify Audio is Being Sent

While the Pi client is running, speak into the microphone and watch for:

**In the Pi client logs:**
- No specific audio indication (Daily SDK handles this internally)
- But you should NOT see any errors about audio devices

**In the backend logs:**
- Look for transcription messages
- Should see `👤 User said: [your speech]`

**In the admin panel:**
- `userIsSpeaking` indicator should light up when you speak
- Transcription should appear in the conversation log
- Bot should respond with a video clip

## Troubleshooting

### No audio devices found
```bash
# Check if USB device is recognized
lsusb

# Check ALSA configuration
cat /proc/asound/cards
```

### Audio device permission errors
```bash
# Add user to audio group
sudo usermod -a -G audio twistedtv

# Reboot or re-login for changes to take effect
```

### Wrong audio device selected
```bash
# Manually set the device
echo "hw:1,0" > /home/twistedtv/audio_device.conf

# Or use environment variable
export AUDIO_DEVICE="hw:1,0"
```

### Daily SDK errors about microphone
Check the Daily SDK logs for specific errors. Common issues:
- Device ID format wrong (should be `hw:CARD,DEVICE` or `default`)
- Device doesn't exist or is in use by another application
- Permission denied accessing the device

### Still no transcription

If audio device is working but no transcription:
1. Check backend is running and accessible
2. Verify Whisper STT is initialized properly
3. Check OpenAI API key is valid
4. Look for errors in backend logs about Whisper or STT

## Expected Behavior

When everything is working:
1. Pi client joins Daily room successfully
2. Microphone captures audio from phone
3. Daily SDK sends audio to backend via WebRTC
4. Backend receives audio stream
5. Whisper transcribes speech to text
6. LLM processes the text
7. Bot responds by playing a video clip
8. Video plays on the TV

The entire loop should take 2-5 seconds from speech to video playback.

## Key Configuration Files

- `/home/twistedtv/audio_device.conf` - Audio device selected via admin panel
- `mcp/pi_daily_client_rtvi.py` - Pi Daily client (updated)
- `cinema-bot-app/frontend-next/components/PiAudioDeviceSelector.tsx` - Admin panel selector
- `cinema-bot-app/frontend-next/pages/api/pi/audio-device.ts` - API to set device
- `cinema-bot-app/frontend-next/pages/api/pi/audio-devices.ts` - API to list devices

## Next Steps After Testing

Once audio is confirmed working:
1. Set up the Pi to auto-start the client on boot
2. Configure the phone input hardware properly
3. Test the full installation setup (phone → Pi → backend → TV)
4. Tune audio levels and quality settings
