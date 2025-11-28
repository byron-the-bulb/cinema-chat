# Voice Bot Solution: Daily Python SDK DOES Work

## Summary

I was wrong about the Daily Python SDK not supporting audio capture. The SDK **DOES** support it through a virtual microphone pattern, and you already have a working implementation in [`pi_daily_client_rtvi_v2.py`](mcp/pi_daily_client_rtvi_v2.py).

## How Daily Python SDK Handles Audio

### The Virtual Microphone Pattern

The Daily Python SDK uses a **virtual microphone** approach that gives you MORE control than direct hardware capture:

1. **Create virtual microphone** - `Daily.create_microphone_device()`
2. **Capture audio separately** - Use PyAudio, alsaaudio, or any audio library
3. **Write frames to virtual mic** - `microphone_device.write_frames(audio_data)`
4. **Select virtual mic** - `call_client.update_inputs({"microphone": {"deviceId": ...}})`
5. **Daily SDK sends over WebRTC** - Automatically handled

### Why This is Better Than Direct Capture

- Full control over audio processing
- Can apply filters, noise reduction, etc.
- Works with any audio source (not just system microphones)
- No browser required (headless)
- Perfect for Raspberry Pi installations

## Your Working Implementation

File: **[`mcp/pi_daily_client_rtvi_v2.py`](mcp/pi_daily_client_rtvi_v2.py)**

### Key Components

**1. Virtual Microphone Creation (lines 222-229):**
```python
microphone_device = Daily.create_microphone_device(
    "pi-microphone",
    sample_rate=16000,  # Matches Whisper STT
    channels=1           # Mono
)
```

**2. ALSA Audio Capture (lines 63-76):**
```python
self.mic_device = alsaaudio.PCM(
    alsaaudio.PCM_CAPTURE,
    alsaaudio.PCM_NONBLOCK,
    channels=CHANNELS,
    rate=SAMPLE_RATE,
    format=alsaaudio.PCM_FORMAT_S16_LE,
    periodsize=PERIOD_SIZE,
    device=device  # hw:1,0 from config
)
```

**3. Audio Feed Loop (lines 84-97):**
```python
while self.running:
    # Read from ALSA
    length, data = self.mic_device.read()

    # Convert to numpy array
    audio_array = np.frombuffer(data, dtype=np.int16)

    # Convert to float32 [-1, 1] for Daily
    audio_float = audio_array.astype(np.float32) / 32768.0

    # Write to Daily virtual microphone
    self.daily_mic.write_frames(audio_float.tobytes())
```

**4. Microphone Selection (lines 269-276):**
```python
call_client.update_inputs({
    "microphone": {
        "isEnabled": True,
        "settings": {
            "deviceId": microphone_device.device_name
        }
    }
})
```

## Dependencies Installed

On the Raspberry Pi:
```bash
sudo apt-get install python3-alsaaudio python3-numpy
```

These packages are now installed and ready to use.

## Configuration

Audio device: **hw:1,0** (USB Audio Device)
- Configured in: `/home/twistedtv/audio_device.conf`
- Read by client in `get_audio_device()` function (lines 34-48)

## Why the `update_inputs()` Functions Exist

You asked: "Why are they there if you are saying that the SDK doesn't capture input?"

**Answer**: They exist because:
1. **Browser clients** use them to select system microphones (webcam mic, USB mic, etc.)
2. **Python clients** use them to select **virtual microphones** that you feed with custom audio
3. This is the DESIGNED pattern for server-side/headless audio capture

The confusion was:
- ❌ **Direct hardware capture**: SDK doesn't directly open `/dev/snd` or ALSA devices
- ✅ **Virtual device support**: SDK accepts audio from virtual microphones you control

## Architecture Comparison

### What I Incorrectly Suggested (HTTP Transcription)

```
Pi Microphone → PyAudio → HTTP POST → /transcribe → Daily room
                                     ↓
                                  Whisper STT
```

**Problems:**
- Extra network hop
- Latency from HTTP request/response
- Doesn't use Daily's optimized WebRTC audio streaming
- More complex error handling

### What You Already Have (Daily Virtual Microphone)

```
Pi Microphone → alsaaudio → Virtual Mic → Daily WebRTC → Backend
                                                        ↓
                                                    Whisper STT
```

**Benefits:**
- Direct WebRTC streaming (low latency)
- Uses Daily's built-in audio pipeline
- Simpler architecture
- Better audio quality (continuous streaming, no chunking)

## Next Steps

### 1. Ensure Backend is Running

```bash
# Check backend
curl http://localhost:8765/health

# If not running:
cd cinema-bot-app/backend
source venv/bin/activate
cd src/cinema-bot
python3 server.py
```

### 2. Test Pi Client

```bash
# SSH to Pi
ssh twistedtv@192.168.1.201

# Set backend URL
export BACKEND_URL="http://192.168.1.143:8765/api"
export VIDEO_SERVICE_URL="http://localhost:5000"

# Run the client
cd /home/twistedtv
python3 pi_daily_client_rtvi_v2.py
```

### 3. Expected Output

```
============================================================
🎬 Cinema Chat - Pi RTVI Client (Fixed Audio)
============================================================
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

### 4. Monitor Audio Flow

**Pi client logs:**
- Should show "🎤 Audio capture active"
- Should NOT show errors about ALSA or audio devices

**Backend logs:**
```bash
tail -f /tmp/backend_reverted.log | grep -i "transcription\|user said\|whisper"
```

Should show:
- Whisper transcriptions appearing
- "👤 User said: ..." messages

**Frontend (if running):**
- Open http://localhost:3000
- Watch for `userIsSpeaking` indicator
- Check conversation log for transcriptions

## Troubleshooting

### If ALSA errors occur:

```bash
# Check device exists
arecord -l

# Test recording
arecord -D hw:1,0 -d 2 -f S16_LE -r 16000 -c 1 test.wav
aplay test.wav

# Check permissions
groups twistedtv  # Should include 'audio'
```

### If no transcription appears:

1. Check backend Whisper is loaded (look for "Whisper model loaded" in logs)
2. Verify Daily room connection (look for "✅ Joined Daily.co room")
3. Check virtual microphone is selected (look for "Virtual microphone selected")
4. Monitor ALSA audio capture (look for "Starting audio capture loop")

### If video playback doesn't work:

1. Check video service is running on Pi (port 5000)
2. Verify bot sends video commands (backend logs)
3. Check Pi receives app messages (Pi client logs)

## Summary

**You were right to question my assessment.** The Daily Python SDK DOES support audio capture through virtual microphones, and your implementation in `pi_daily_client_rtvi_v2.py` is architecturally correct.

The issue is likely not with the Daily SDK but with:
1. Audio device configuration (now fixed with alsaaudio installed)
2. Audio permissions (check user is in 'audio' group)
3. Backend Whisper STT (verify it's loaded and working)
4. Network connectivity between Pi and backend

**Your Python implementation is BETTER than a JavaScript approach** for this use case because it:
- Runs headless (no browser needed)
- Gives full control over audio processing
- Integrates directly with ALSA hardware
- Is more suitable for a Raspberry Pi installation

I apologize for the confusion and for previously giving incorrect advice about switching from JavaScript to Python. The Python approach is correct; we just need to debug the specific issue preventing audio from reaching the backend.
