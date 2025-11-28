# Debugging Guide: Pi Audio → Transcription → Daily Room

This guide shows how to debug each step of the audio pipeline to see where things might be failing.

## Architecture Overview

```
1. Pi Microphone → PyAudio
2. PyAudio → HTTP POST to /transcribe (with room_url)
3. /transcribe → Whisper STT
4. /transcribe → Daily REST API (send-app-message)
5. Daily Room → Bot receives message
6. Bot → Processes message → Video command
7. Video command → Pi receives via Daily app message
8. Pi → Plays video
```

## Step-by-Step Debugging

### Step 1: Test Audio Capture on Pi

**Test**: Can we capture audio from the microphone?

```bash
ssh twistedtv@192.168.1.201
cd /home/twistedtv
python3 test_audio_transcribe.py
```

**Expected Output:**
```
Recording 3 seconds...
SPEAK NOW!
Recording complete
Creating WAV file...
WAV file size: 96000 bytes
Sending to http://192.168.1.143:8765/transcribe...
SUCCESS!
Transcribed text: hello this is a test
Language: en
```

**If this fails:**
- Check microphone is plugged in: `arecord -l`
- Test with `arecord -D hw:1,0 -d 2 -f cd -c 1 test.wav`
- Check PyAudio is installed: `pip3 list | grep PyAudio`

---

### Step 2: Test Backend /transcribe Endpoint

**Test**: Can the backend transcribe audio?

```bash
# From your machine (not Pi)
cd /home/va55/code/cinema-chat

# Record a test audio file
arecord -d 3 -f cd -c 1 -r 16000 test.wav

# Send to transcribe endpoint (without room_url for testing)
curl -X POST http://localhost:8765/transcribe \
  -F "file=@test.wav" \
  | jq
```

**Expected Output:**
```json
{
  "text": "your speech here",
  "language": "en",
  "sent_to_room": false
}
```

**Monitor Backend Logs:**
```bash
# Watch backend logs in real-time
tail -f /tmp/backend_*.log | grep -i transcrib
```

**If this fails:**
- Check backend is running: `ps aux | grep "python3 server.py"`
- Check Whisper model loaded: Look for "Whisper model loaded" in logs
- Check for errors in backend logs

---

### Step 3: Test Transcribe + Room Injection

**Test**: Can we send transcription to a Daily room?

First, get a room URL by starting a session:

```bash
# Start the backend
cd cinema-bot-app/backend/src/cinema-bot
python3 server.py

# In another terminal, create a session
curl -X POST http://localhost:8765/api/connect \
  -H "Content-Type: application/json" \
  -d '{"config":[]}' \
  | jq

# Copy the room_url from the response
```

Then test with room_url:

```bash
curl -X POST http://localhost:8765/transcribe \
  -F "file=@test.wav" \
  -F "room_url=https://your-daily-domain.daily.co/room-name" \
  | jq
```

**Expected Output:**
```json
{
  "text": "your speech here",
  "language": "en",
  "sent_to_room": true
}
```

**Monitor Backend Logs:**
```bash
tail -f /tmp/backend_*.log | grep -E "(Transcribed|Sent transcription|Failed to send)"
```

**You should see:**
```
Transcribed: your speech here
✅ Sent transcription to room: your speech here
```

**If sent_to_room is false:**
- Check `DAILY_API_KEY` is set: `echo $DAILY_API_KEY`
- Check room_url format is correct
- Look for errors in backend logs about Daily API

---

### Step 4: Test Pi Client Audio Loop

**Test**: Does Pi client capture and send audio continuously?

```bash
ssh twistedtv@192.168.1.201
cd /home/twistedtv

# Run the transcribe client
python3 pi_daily_client_transcribe.py 2>&1 | tee /tmp/pi_client.log
```

**Expected Output (initial):**
```
============================================================
🎬 Cinema Chat - Raspberry Pi Transcribe Client
============================================================
Backend: http://192.168.1.143:8765
Video Service: http://localhost:5000
Audio Device: hw:1,0
============================================================
Connecting to backend...
✅ Got room URL: https://...
Joining room: https://...
📞 Call state: joined
✅ Joined Daily.co room
🎤 Starting local audio capture and transcription
🎤 Audio capture loop started
```

**Expected Output (when you speak):**
```
Capturing 3s audio chunk...
Sending audio for transcription...
✅ Transcription sent to Daily room: hello
👤 Transcribed and sent to room: hello
```

**Monitor in Separate Terminal:**
```bash
ssh twistedtv@192.168.1.201
tail -f /tmp/pi_client.log | grep -E "(Transcribed|sent to room|ERROR)"
```

**If you don't see transcriptions:**
- Check audio capture: Look for "Capturing 3s audio chunk"
- Check HTTP requests: Look for "Sending audio for transcription"
- Check responses: Look for errors from transcribe endpoint

---

### Step 5: Monitor Backend Receipt of Messages

**Test**: Does the backend receive the Daily app message?

In the backend logs, you should see the bot processing the message:

```bash
tail -f /tmp/backend_*.log | grep -E "(user-transcription|Transcribed|Function call)"
```

**Expected to see:**
- Receipt of user-transcription message
- Function calls to search_video_clips
- Function calls to play_video_by_params

**If bot doesn't respond:**
- Check bot received the app message (look for "user-transcription" type)
- Check LLM is processing it
- Check MCP tools are being called

---

### Step 6: Monitor Video Playback Commands

**Test**: Does Pi receive video playback commands?

In the Pi client logs:

```bash
ssh twistedtv@192.168.1.201
tail -f /tmp/pi_client.log | grep -E "(video-playback-command|Video started)"
```

**Expected Output:**
```
📨 Received message from bot-user-id
✅ MATCHED video-playback-command!
✅ MATCHED action=play, calling play_video()
✅ Video started: PID 12345
```

**If no video commands:**
- Check bot is calling video playback tools
- Check app messages are being sent from bot
- Check Pi client's `on_app_message` handler

---

## Common Issues and Solutions

### Issue: No transcription happening

**Debug steps:**
1. Check Pi can capture audio: Run `test_audio_transcribe.py`
2. Check backend /transcribe works: Use curl to test directly
3. Check Pi is sending requests: Look for HTTP POST in Pi logs
4. Check backend is receiving: Look for "TRANSCRIBE ENDPOINT CALLED" in backend logs

### Issue: Transcription works but not sent to room (sent_to_room: false)

**Debug steps:**
1. Check `DAILY_API_KEY` is set in backend environment
2. Check room_url is being passed correctly from Pi
3. Check Daily API response in backend logs
4. Verify room URL format: `https://domain.daily.co/room-name`

### Issue: Bot doesn't respond to transcription

**Debug steps:**
1. Check bot received the app message (search logs for "user-transcription")
2. Check bot's LLM is processing the message
3. Check bot's function calls are working
4. Test with browser client to ensure bot works normally

### Issue: Pi doesn't receive video commands

**Debug steps:**
1. Check Pi is still connected to Daily room
2. Check bot is sending app messages (backend logs)
3. Check Pi's `on_app_message` handler is working
4. Test by manually sending app message via Daily REST API

---

## Monitoring Commands

### Monitor Everything at Once

**Terminal 1 - Backend:**
```bash
cd cinema-bot-app/backend/src/cinema-bot
python3 server.py 2>&1 | tee /tmp/backend_debug.log
```

**Terminal 2 - Pi Client:**
```bash
ssh twistedtv@192.168.1.201
python3 /home/twistedtv/pi_daily_client_transcribe.py 2>&1 | tee /tmp/pi_debug.log
```

**Terminal 3 - Backend Logs:**
```bash
tail -f /tmp/backend_debug.log | grep --line-buffered -E "(Transcribed|sent to room|user-transcription|video-playback)"
```

**Terminal 4 - Pi Logs:**
```bash
ssh twistedtv@192.168.1.201
tail -f /tmp/pi_debug.log | grep --line-buffered -E "(Transcribed|Video started|ERROR)"
```

---

## Success Indicators

When everything is working, you should see this flow:

**Pi Client:**
```
Capturing 3s audio chunk...
Sending audio for transcription...
✅ Transcription sent to Daily room: hello
👤 Transcribed and sent to room: hello
📨 Received message from bot-xyz
✅ Video started: PID 12345
```

**Backend:**
```
Transcribed: hello
✅ Sent transcription to room: hello
[Bot processing user message: hello]
[Function call: search_video_clips]
[Function call: play_video_by_params]
[Sending video command to room]
```

**Expected Timeline:**
1. Pi captures audio (3 seconds)
2. Pi sends to /transcribe (~100ms)
3. Backend transcribes (~500ms)
4. Backend sends to Daily room (~100ms)
5. Bot receives and processes (~1-2 seconds)
6. Bot sends video command (~100ms)
7. Pi plays video (~500ms)

**Total: ~5-6 seconds from speech to video**
