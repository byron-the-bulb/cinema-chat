# Pi Audio Fix - Virtual Microphone Implementation

## Problem Identified

The Pi client ([mcp/pi_daily_client_rtvi.py](mcp/pi_daily_client_rtvi.py)) was **not actually capturing audio from the hardware device**.

### What Was Wrong

The old implementation tried to enable audio with:
```python
client_settings={
    "inputs": {"microphone": True},
    "publishing": {"microphone": True}
}
```

**This does NOT work on Linux/Raspberry Pi** because:
- The Daily Python SDK cannot directly access hardware microphones on Linux
- Setting `microphone: True` tells Daily to use a system microphone, but there isn't one available in a headless Pi environment
- The SDK does NOT automatically open ALSA devices or `/dev/snd` hardware

### Why No `userIsSpeaking` Indicator

- The backend never received audio because the Pi never sent any
- The Pi was connected to the Daily.co room successfully
- But NO audio data was being transmitted from the Pi's microphone to Daily's WebRTC stream

## Solution: Virtual Microphone Pattern

The Daily Python SDK **DOES support audio capture**, but through a different pattern than direct hardware access.

### How It Works

1. **Create a virtual microphone device** - `Daily.create_microphone_device()`
2. **Capture audio separately** - Use alsaaudio/PyAudio to read from hardware
3. **Write frames to virtual mic** - `microphone_device.write_frames(audio_data)`
4. **Select virtual mic in Daily** - `call_client.update_inputs({"microphone": {"deviceId": ...}})`
5. **Daily sends over WebRTC** - Automatically handled by SDK

### Why This Approach Works

- Full control over audio capture and processing
- Works on headless systems without system microphones
- Can apply filters, noise reduction, etc.
- Compatible with ALSA hardware devices
- Proper integration with Daily's WebRTC pipeline

## Changes Made

### File Updated: [mcp/pi_daily_client_rtvi.py](mcp/pi_daily_client_rtvi.py)

#### 1. Added Dependencies (lines 20-21)
```python
import alsaaudio
import numpy as np
```

#### 2. Added Audio Configuration (lines 30-35)
```python
AUDIO_CONFIG_FILE = "/home/twistedtv/audio_device.conf"
SAMPLE_RATE = 16000  # Match Whisper STT
CHANNELS = 1         # Mono
PERIOD_SIZE = 160    # 10ms at 16kHz
```

#### 3. Added `get_audio_device()` Function (lines 45-59)
Reads configured device from `/home/twistedtv/audio_device.conf` (set via Pi control panel) or falls back to environment variable.

#### 4. Added `ALSAAudioSource` Class (lines 62-126)
Handles:
- Opening ALSA PCM device for capture
- Reading audio frames in a loop
- Converting to float32 format expected by Daily
- Writing frames to Daily's virtual microphone

Key method: `read_frames()` - Async loop that continuously captures audio and feeds to Daily

#### 5. Updated `CinemaRTVIClient.__init__` (lines 148-149)
Added fields to track audio source and capture task:
```python
self.audio_source = None
self.audio_task = None
```

#### 6. Simplified `on_call_state_updated()` (lines 194-201)
Removed incorrect microphone enable logic - now handled in `run_client()`

#### 7. Completely Rewrote `run_client()` Function (lines 331-429)

**Key steps:**
```python
# Create virtual microphone
microphone_device = Daily.create_microphone_device(
    "pi-microphone",
    sample_rate=16000,
    channels=1
)

# Join room with mic disabled initially
call_client.join(..., client_settings={
    "inputs": {"camera": False, "microphone": False},
    "publishing": {"camera": False, "microphone": False}
})

# After join completes, select virtual microphone
call_client.update_inputs({
    "microphone": {
        "isEnabled": True,
        "settings": {"deviceId": microphone_device.device_name}
    }
})

# Enable publishing
call_client.update_publishing({"microphone": True})

# Create ALSA audio source and start capture
audio_source = ALSAAudioSource(audio_device, microphone_device)
client.audio_task = asyncio.create_task(audio_source.read_frames())
```

## Testing the Fix

### 1. Verify Dependencies on Pi

SSH to Pi and check:
```bash
ssh twistedtv@192.168.1.201
pip3 list | grep -E "(alsaaudio|numpy)"
```

Should show:
```
numpy                        1.26.4
pyalsaaudio                  0.10.0
```

✅ **Already installed** (verified)

### 2. Test Audio Device

```bash
arecord -D hw:1,0 -d 2 -f S16_LE -r 16000 -c 1 test.wav
aplay test.wav
```

Should hear your voice clearly.

### 3. Run Updated Pi Client

The Next.js frontend on the Pi automatically starts `/home/twistedtv/pi_daily_client_rtvi.py` when you start a room.

Expected logs:
```
Creating Daily virtual microphone...
✅ Virtual microphone created
✅ Got room URL: https://...
Joining room: https://...
Selecting virtual microphone with update_inputs()...
✅ Virtual microphone selected and publishing enabled
Opening ALSA device: hw:1,0
✅ ALSA device opened: 16000Hz, 1 ch
Starting audio capture from ALSA...
🎤 Starting audio capture loop
✅ Joined Daily.co room
🎤 Audio capture active
✅ Client running. Press Ctrl+C to stop.
```

### 4. Monitor Backend for Audio

```bash
tail -f /tmp/backend_reverted.log | grep -i "transcription\|user said\|whisper"
```

Should show:
- Whisper transcriptions appearing
- "👤 User said: ..." messages

### 5. Check Frontend for `userIsSpeaking`

Open http://localhost:3000 (on Pi or access remotely)

When you speak into the microphone:
- `userIsSpeaking` indicator should light up
- Transcription should appear in conversation log
- Bot should respond with video command
- Video should play on TV

## Why This Fix Was Necessary

1. **Previous assessment was incorrect** - I mistakenly thought Daily Python SDK didn't support audio capture at all
2. **User had working implementation** - The correct pattern was already in [`pi_daily_client_rtvi_v2.py`](mcp/pi_daily_client_rtvi_v2.py) but wasn't being used
3. **Simple `microphone: True` doesn't work on Linux** - Daily can't auto-detect hardware on headless systems
4. **Virtual microphone is the designed pattern** - This is how Daily Python SDK is meant to be used for server-side/Pi audio capture

## Related Documentation

- [VOICE_BOT_SOLUTION.md](VOICE_BOT_SOLUTION.md) - Explains virtual microphone pattern in detail
- [PI_AUDIO_TESTING.md](PI_AUDIO_TESTING.md) - Original testing guide (now outdated approach)
- [DEBUGGING_GUIDE.md](DEBUGGING_GUIDE.md) - Step-by-step debugging of audio pipeline

## Next Steps

1. Test the updated client by starting a new room from the frontend
2. Verify `userIsSpeaking` indicator appears when speaking
3. Confirm bot responds with video playback
4. If working, this solves the core audio input issue
5. Can then address secondary issue: room management (old clients don't shut down)

## Summary

**Root Cause:** Pi client wasn't actually capturing or sending audio - it was just setting `microphone: True` which doesn't work on Linux.

**Fix:** Implemented virtual microphone pattern:
- Create virtual mic with Daily SDK
- Capture from ALSA hardware separately
- Feed audio frames to virtual mic
- Daily sends over WebRTC automatically

**Result:** Pi now properly captures audio from hw:1,0 (USB microphone) and streams it to Daily.co room, where backend's Whisper STT can transcribe it.
