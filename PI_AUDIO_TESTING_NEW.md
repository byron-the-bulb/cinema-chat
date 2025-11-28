# Raspberry Pi Audio Testing Guide (HTTP Transcription Approach)

## Problem
Daily Python library (v0.16.1) does not support local audio capture on Raspberry Pi Linux. When we enable microphone via `call_client.update_inputs({"microphone": True})`, the library reports it as enabled but never actually opens the ALSA audio device.

## Solution
Bypass Daily.co for audio input using HTTP-based transcription:

1. **Pi captures audio** from USB microphone (hw:1,0) using PyAudio
2. **Pi sends audio to backend** `/transcribe` endpoint via HTTP
3. **Backend transcribes** using existing Whisper STT model
4. **Pi receives text back** and injects into conversation
5. **Pi still uses Daily.co** for receiving video playback commands

## Architecture

```
Pi Microphone (hw:1,0)
    ↓
PyAudio capture (3-second chunks)
    ↓
Convert to WAV format
    ↓
HTTP POST to /transcribe endpoint
    ↓
Backend Whisper STT
    ↓
Text returned to Pi
    ↓
[TODO: Inject text into conversation]
    ↓
Daily.co app messages → Video playback
```

## Files Created

### Backend Changes
- **`cinema-bot-app/backend/src/cinema-bot/server.py`**
  - Added `/transcribe` endpoint (line 824)
  - Accepts audio file uploads
  - Uses existing Whisper model
  - Returns transcribed text as JSON

### Pi Client Files
- **`mcp/test_audio_transcribe.py`**
  - Simple test script to verify audio capture and transcription
  - Records 3 seconds of audio
  - Sends to /transcribe endpoint
  - Prints transcribed text

- **`mcp/pi_daily_client_transcribe.py`**
  - Full Pi client with HTTP-based transcription
  - Captures audio in 3-second chunks using PyAudio
  - Transcribes via /transcribe endpoint
  - Joins Daily.co room (without publishing audio)
  - Receives video playback commands via app messages
  - **TODO**: Inject transcribed text into conversation

## Testing Steps

### Step 1: Test Audio Capture and Transcription

On the Raspberry Pi, run the simple test script:

```bash
ssh twistedtv@192.168.1.201
cd /home/twistedtv
python3 test_audio_transcribe.py
```

Expected output:
```
============================================================
Audio Capture and Transcription Test
============================================================
Backend: http://192.168.1.143:8765
Audio device: hw:1,0
Sample rate: 16000 Hz
Duration: 3 seconds
============================================================
Found audio device: ... at index 1
Opening audio stream...
Recording 3 seconds...
SPEAK NOW!
Recording complete
Creating WAV file...
WAV file size: ... bytes
Sending to http://192.168.1.143:8765/transcribe...
============================================================
SUCCESS!
============================================================
Transcribed text: [what you said]
Language: en
============================================================
```

### Step 2: Run Full Pi Client (when ready)

```bash
cd /home/twistedtv
python3 pi_daily_client_transcribe.py
```

Expected behavior:
1. Pi connects to backend /api/connect
2. Pi joins Daily.co room
3. Bot joins room
4. Pi starts capturing audio in 3-second chunks
5. Each chunk is transcribed
6. Transcribed text is logged
7. [TODO: Text injected into conversation]
8. Bot responds with video playback command
9. Pi plays video

## Current Status

✅ **Completed:**
- Backend `/transcribe` endpoint implemented
- Test script created for audio capture validation
- Full Pi client with audio capture loop
- Audio converted to WAV format
- HTTP transcription working
- Files copied to Pi

❌ **TODO:**
1. Test `test_audio_transcribe.py` on Pi to verify audio capture works
2. Figure out how to inject transcribed text into Pipecat pipeline
3. Test full end-to-end flow: speech → transcription → bot response → video
4. Verify "user is speaking" indicator appears in admin panel
5. Verify conversation progresses beyond initial greeting

## Technical Details

### Audio Configuration
- **Device**: hw:1,0 (USB microphone, card 1, device 0)
- **Sample Rate**: 16000 Hz (optimal for Whisper)
- **Channels**: 1 (mono)
- **Format**: 16-bit PCM WAV
- **Chunk Size**: 3 seconds (48000 samples)

### Whisper Model
- Model: "base" (same as Pipecat pipeline)
- Device: Configured via `WHISPER_DEVICE` env var (CUDA or CPU)
- Lazy-loaded on first transcription request
- Shared across all transcription requests

### Daily.co Settings
- **Microphone**: Disabled (we handle audio separately)
- **Camera**: Disabled
- **App Messages**: Enabled (for video playback commands)

## Known Issues

1. **Daily Python library limitation**: Cannot capture local audio on Linux
   - Workaround: HTTP-based transcription (current approach)

2. **Text injection not implemented**: Need to figure out how to push transcribed text into Pipecat pipeline
   - Option A: Create `/inject_text` endpoint that pushes text into bot's pipeline
   - Option B: Use Daily app messages to simulate user speech
   - Option C: Modify Pipecat pipeline to accept external text input

3. **Continuous audio capture**: Current implementation captures in 3-second chunks
   - Might miss beginning/end of speech if it spans chunk boundaries
   - Consider voice activity detection (VAD) for better segmentation

## Next Steps

1. **Test audio capture** on Pi using `test_audio_transcribe.py`
2. **Implement text injection** mechanism
3. **Test full client** with complete conversation flow
4. **Optimize chunk duration** based on testing
5. **Add error handling** for network failures, transcription errors
6. **Add reconnection logic** if Daily.co connection drops

## Troubleshooting

### PyAudio not installed
```bash
ssh twistedtv@192.168.1.201
pip3 install pyaudio
```

### Permission errors accessing audio device
```bash
sudo usermod -a -G audio twistedtv
# Then reboot or re-login
```

### Backend /transcribe endpoint not responding
```bash
# Check backend is running
curl http://192.168.1.143:8765/health

# Check backend logs
tail -f /tmp/backend_*.log
```

### Audio quality issues
- Adjust sample rate (currently 16000 Hz)
- Adjust chunk duration (currently 3 seconds)
- Check microphone volume levels with `alsamixer`
