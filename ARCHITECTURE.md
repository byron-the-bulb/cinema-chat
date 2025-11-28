# Cinema-Chat Architecture

## Overview

Cinema-Chat is an art installation where users speak into a phone and the system responds with old movie clips displayed on a TV. The system uses semantic search to find contextually appropriate video clips.

## Complete Architecture

```
┌──────────────────────────────────────────────────┐
│         Raspberry Pi (Installation Site)          │
│         IP: 192.168.1.201 (local network)         │
├──────────────────────────────────────────────────┤
│                                                  │
│  1. Phone (connected to audio input)             │
│     ↓                                             │
│  2. Headless Daily.co Client (Python)            │
│     - Captures audio from phone                   │
│     - Sends to Daily.co WebRTC                    │
│     - Receives video commands                     │
│     - Calls localhost:5000                        │
│     ↓                                             │
│  3. Video Playback Service (port 5000)           │
│     - Plays videos via mpv on HDMI                │
│     - Manages display blanking                    │
│     ↓                                             │
│  4. TV (HDMI output)                             │
│     - Shows video clips                           │
│     - Blanks between clips (NO SIGNAL)            │
│                                                  │
│  Optional: Next.js Dashboard (port 3000)         │
│     - Web UI for monitoring/config                │
│     - Accessible from other devices               │
│                                                  │
└──────────────────────────────────────────────────┘
                      ↕
             Daily.co WebRTC Cloud
          (Audio up, Commands down)
                      ↕
┌──────────────────────────────────────────────────┐
│    Server (Cloud or Local, different network)    │
├──────────────────────────────────────────────────┤
│                                                  │
│  1. FastAPI Backend (port 7860)                  │
│     - Receives audio via Daily.co WebRTC          │
│     - DailyTransport (Pipecat)                    │
│     ↓                                             │
│  2. Whisper STT (GPU accelerated)                │
│     - Transcribes phone audio to text             │
│     ↓                                             │
│  3. OpenAI GPT-4.1 LLM                           │
│     - Understands conversation                    │
│     - Calls MCP tools                             │
│     ↓                                             │
│  4. MCP Server (stdio)                           │
│     - search_video_clips (semantic search)        │
│     - play_video_by_params (select clip)          │
│     - Returns video metadata to LLM               │
│     ↓                                             │
│  5. Backend sends video command                  │
│     - Via Daily.co app message or RTVI            │
│     - To Pi headless client                       │
│                                                  │
└──────────────────────────────────────────────────┘
```

## Data Flow

### 1. Audio Input (Pi → Server)
```
Phone mic → Pi audio input → Headless Daily client
    → Daily.co WebRTC (audio stream)
    → Server DailyTransport → Pipecat pipeline
    → Whisper STT → Text transcription
```

### 2. Conversation Processing (Server)
```
User text → LLM context
    → LLM thinks about response
    → LLM calls function: search_video_clips(description)
    → MCP server finds matching clips
    → LLM analyzes options
    → LLM calls function: play_video_by_params(video_id, ...)
    → MCP returns video metadata
```

### 3. Video Playback Command (Server → Pi)
```
Server receives MCP result with video params
    → Backend sends app message via Daily.co
    → Daily.co cloud routes to Pi client
    → Pi headless client receives message
    → Client calls: POST http://localhost:5000/play
    → Video service plays clip on HDMI
    → TV displays video
    → Video service blanks display after playback
```

## Components

### Raspberry Pi Components

#### 1. Headless Daily.co Client
**File**: `/home/twistedtv/pi_daily_client.py`
**Purpose**: Bridge between Daily.co and local services
**Functions**:
- Capture audio from phone input (ALSA device)
- Connect to Daily.co WebRTC room
- Stream audio to server
- Listen for video playback commands
- Call local video service

**Technology**: Python, daily-python SDK, PyAudio

#### 2. Video Playback Service
**File**: `/home/twistedtv/video_playback_service.py`
**Purpose**: Play video clips on HDMI output
**Functions**:
- HTTP API (Flask) on port 5000
- Play video clips with start/end times
- mpv with DRM/KMS rendering
- VT switching and framebuffer blanking

**Endpoints**:
- `POST /play` - Play a video clip
- `POST /stop` - Stop current playback
- `GET /status` - Get playback status
- `GET /health` - Health check

**Technology**: Python, Flask, mpv, subprocess

#### 3. Next.js Dashboard (Optional)
**Directory**: `/home/twistedtv/frontend-next/`
**Purpose**: Web UI for monitoring and configuration
**Functions**:
- Show conversation transcript
- Display selected videos
- Configure settings (server URL, etc.)
- Monitor system status

**Access**: `http://192.168.1.201:3000` from any browser on network

**Technology**: Next.js, React, TypeScript

### Server Components

#### 1. FastAPI Backend
**Directory**: `/home/va55/code/cinema-chat/cinema-bot-app/backend/`
**Purpose**: Main conversation orchestration
**Functions**:
- Daily.co WebRTC connection via DailyTransport
- Audio pipeline: input → STT → LLM → output
- MCP client integration
- Send video commands to Pi

**Technology**: Python, FastAPI, Pipecat, Daily.co

#### 2. Whisper STT
**Model**: whisper-large-v3 (Hugging Face)
**Device**: CUDA (GPU) or CPU
**Purpose**: Convert phone audio to text

#### 3. OpenAI LLM
**Model**: GPT-4.1
**Purpose**: Conversation understanding and video selection
**Tools**: search_video_clips, play_video_by_params

#### 4. MCP Server
**File**: `/home/va55/code/cinema-chat/mcp/mock_server.py`
**Purpose**: Video search and metadata
**Modes**:
- Mock mode: Keyword matching with hardcoded scenes
- Future: GoodCLIPS API semantic search

**Technology**: Python, MCP SDK, stdio communication

## Communication Protocols

### Daily.co WebRTC
- **Audio**: Bidirectional WebRTC streams
- **Control**: App messages or RTVI protocol
- **Connection**: Persistent WebSocket
- **Room**: Created via Daily.co API

### HTTP (Local on Pi)
- **Video Service**: `POST http://localhost:5000/play`
- **Dashboard**: `http://192.168.1.201:3000` (from network)

### MCP (stdio)
- **Transport**: stdin/stdout
- **Format**: JSON-RPC
- **Tools**: search_video_clips, play_video_by_params

## Network Requirements

### Internet (Required)
- Daily.co WebRTC cloud service
- OpenAI API
- Daily.co API (room creation)

### Local Network (Pi)
- Video playback service: localhost:5000
- Dashboard (optional): accessible on LAN at :3000
- Headless client: connects outbound to Daily.co

### Firewall Considerations
- **Pi**: Only needs outbound connections to Daily.co (no inbound!)
- **Server**: Only needs outbound connections to Daily.co and OpenAI
- **No direct server→Pi connection needed** (that's why we use Daily.co!)

## Environment Variables

### Raspberry Pi

```bash
# Headless Daily Client
DAILY_ROOM_URL=https://example.daily.co/room-name
DAILY_API_KEY=your_daily_api_key  # If creating rooms
VIDEO_SERVICE_URL=http://localhost:5000
AUDIO_DEVICE=default  # ALSA device for phone input

# Video Service (already configured)
# None needed - uses defaults
```

### Server

```bash
# OpenAI
OPENAI_API_KEY=sk-...

# Daily.co
DAILY_API_KEY=your_daily_api_key
DAILY_API_URL=https://api.daily.co/v1

# Whisper
WHISPER_DEVICE=cuda  # or cpu
REPO_ID=openai/whisper-large-v3
MOUNT_POINT=/mnt/models  # Optional

# MCP (not needed - server doesn't call Pi directly)
# VIDEO_PLAYBACK_URL is NOT used

# CloudWatch (optional)
CLOUDWATCH_LOG_GROUP=/cinema-chat/backend
AWS_REGION=us-east-1
```

## Deployment

### Pi Deployment

1. **Video Playback Service** (already running ✅)
```bash
sudo systemctl status video-playback
sudo systemctl status hdmi-off  # Display blanking on boot
```

2. **Headless Daily Client** (needs deployment)
```bash
# Copy client to Pi
scp /home/va55/code/cinema-chat/mcp/pi_daily_client.py twistedtv@192.168.1.201:/home/twistedtv/

# Install dependencies
ssh twistedtv@192.168.1.201
pip3 install daily-python httpx pyaudio

# Create systemd service
sudo nano /etc/systemd/system/cinema-daily-client.service
```

Service file:
```ini
[Unit]
Description=Cinema Chat Headless Daily.co Client
After=network.target

[Service]
Type=simple
User=twistedtv
WorkingDirectory=/home/twistedtv
ExecStart=/usr/bin/python3 /home/twistedtv/pi_daily_client.py
Restart=always
RestartSec=10
Environment="DAILY_ROOM_URL=https://example.daily.co/room"
Environment="VIDEO_SERVICE_URL=http://localhost:5000"
Environment="AUDIO_DEVICE=default"

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable cinema-daily-client
sudo systemctl start cinema-daily-client
```

3. **Dashboard** (optional)
- Follow instructions in DEPLOYMENT.md

### Server Deployment

See DEPLOYMENT.md for full instructions.

**Key point**: Server does NOT need `VIDEO_PLAYBACK_URL` environment variable because it doesn't call the Pi's video service directly!

## Testing

### 1. Test Video Service (Pi)
```bash
curl -X POST http://192.168.1.201:5000/play \
  -H 'Content-Type: application/json' \
  -d '{"video_path":"test.mp4","start":0,"end":5}'
```

### 2. Test Headless Client (Pi)
```bash
# Check logs
sudo journalctl -u cinema-daily-client -f

# Should see:
# - "Starting headless Daily.co client for room: ..."
# - "Joined Daily.co room"
# - "Now streaming audio from phone to server..."
```

### 3. Test Complete Flow
1. Start all services (Pi + Server)
2. Speak into phone
3. Check server logs: Should see Whisper transcription
4. Check server logs: Should see LLM function calls
5. Check Pi logs: Should see video playback command received
6. Check TV: Should display video clip
7. After clip: TV should show NO SIGNAL (blanked)

## Troubleshooting

### No audio from phone
- Check ALSA device: `arecordlist -L`
- Test recording: `arecord -D default -d 5 test.wav`
- Check headless client logs for audio capture errors

### Video commands not received
- Check Daily.co connection in logs
- Verify room URL matches between Pi and server
- Check if app messages are being sent/received

### Video not playing
- Test video service directly (curl command above)
- Check mpv logs: `ls -lt ~/mpv_*.log | head -1`
- Verify framebuffer blanking/unblanking

## Future Enhancements

1. **GoodCLIPS Integration**: Replace keyword matching with semantic search
2. **Dynamic Room Creation**: Auto-create Daily.co rooms per session
3. **Multiple Installations**: Support multiple Pi installations from one server
4. **Analytics Dashboard**: Track conversations, popular clips, user engagement
5. **Curator Mode**: Manual video selection override
6. **Audio Quality**: Noise reduction, echo cancellation
