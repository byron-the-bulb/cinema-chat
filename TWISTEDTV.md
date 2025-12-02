# TwistedTV Documentation

**Last Updated:** 2025-11-30

## Table of Contents

1. [Project Overview](#project-overview)
2. [System Architecture](#system-architecture)
3. [Directory Structure](#directory-structure)
4. [Component Details](#component-details)
5. [Setup & Installation](#setup--installation)
6. [Deployment Guide](#deployment-guide)
7. [Operation & Usage](#operation--usage)
8. [Debugging & Troubleshooting](#debugging--troubleshooting)
9. [Development Guidelines](#development-guidelines)
10. [PR Preparation](#pr-preparation)

---

## Project Overview

**TwistedTV** is an art installation where visitors speak into a vintage rotary phone and converse with an AI that responds exclusively through old movie clips displayed on a TV. The system uses semantic search to find contextually appropriate video clips that serve as the bot's "voice."

### Key Features

- **No Text-to-Speech**: All responses are video clips from classic films
- **Real-time Conversation**: Whisper STT for speech recognition, GPT-4 for understanding
- **Semantic Video Search**: Uses GoodCLIPS API for multi-modal video embeddings
- **Distributed Architecture**: Server runs in cloud/local, Pi runs at installation site
- **WebRTC Transport**: Daily.co for audio between phone and server

### Hardware Components

- **Vintage Rotary Phone**: Audio input device
- **Raspberry Pi**: On-site client for audio capture and video playback
- **TV**: Display for video clips (HDMI from Pi)
- **Server**: Cloud or local machine for AI processing

---

## System Architecture

### High-Level Data Flow

```
┌──────────────────────────────────────────────────┐
│         Raspberry Pi (Installation Site)          │
│         IP: 192.168.1.201 (local network)         │
├──────────────────────────────────────────────────┤
│                                                  │
│  1. Phone (connected to audio input)             │
│     ↓                                             │
│  2. Pi Daily.co Client (Python)                  │
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
│  1. FastAPI Backend (port 8765)                  │
│     - Receives audio via Daily.co WebRTC          │
│     - DailyTransport (Pipecat)                    │
│     ↓                                             │
│  2. Whisper STT (GPU accelerated)                │
│     - Transcribes phone audio to text             │
│     ↓                                             │
│  3. OpenAI GPT-4                                 │
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
│     - To Pi client                                │
│                                                  │
└──────────────────────────────────────────────────┘
```

### Conversation Flow

1. **User speaks into phone** → Audio captured by Pi microphone
2. **Pi Daily client** → Sends audio to Daily.co WebRTC room
3. **Server receives** → Audio transcribed by Whisper STT
4. **LLM processes** → GPT-4 generates response intent/meaning
5. **LLM calls MCP tool** → Requests video clip with semantic description
6. **MCP server queries** → GoodCLIPS API for matching scene
7. **MCP returns metadata** → Best matching clip identified
8. **Server sends command** → Via Daily.co to Pi client
9. **Pi plays video** → mpv displays clip on TV via HDMI
10. **Cycle repeats** → User responds to video

### Communication Protocols

- **Daily.co WebRTC**: Bidirectional audio + control messages
- **HTTP**: Local video playback service (Pi:5000), video streaming (server:9000)
- **MCP (stdio)**: JSON-RPC for LLM tool calling
- **RTVI Protocol**: Real-time Video Intelligence for bot control

---

## Directory Structure

The codebase is organized into three main directories based on deployment target:

```
cinema-chat/
├── cmd/                              # Massimo's GoodCLIPS Go API
├── internal/                         # Massimo's Go internals
├── migrations/                       # Massimo's DB migrations
├── docker-compose.yml               # Massimo's Docker config
│
├── twistedtv-server/                # SERVER-SIDE COMPONENTS
│   ├── cinema_bot/                  # Backend bot orchestration
│   │   ├── server.py               # FastAPI server entry point
│   │   ├── cinema_bot.py           # Main bot logic
│   │   ├── cinema_script.py        # Conversation flows
│   │   ├── mcp_client.py           # MCP client integration
│   │   ├── mcp_video_tools.py      # MCP video tools
│   │   ├── custom_flow_manager.py  # Flow state management
│   │   ├── status_utils.py         # Status updates
│   │   ├── cloudwatch_logger.py    # AWS CloudWatch logging
│   │   └── cleanup_daily_rooms.py  # Daily.co cleanup utility
│   │
│   ├── mcp_server/                  # MCP server for video search
│   │   ├── server.py               # Real MCP server (GoodCLIPS)
│   │   ├── mock_server.py          # Mock server (keyword search)
│   │   ├── config.py               # Configuration
│   │   ├── goodclips_client.py     # GoodCLIPS API client
│   │   └── video_player.py         # Video player utilities
│   │
│   ├── requirements.txt             # Python dependencies
│   ├── Dockerfile                   # Docker image for server
│   ├── build.sh                     # Build script
│   └── .env.example                # Environment variables template
│
├── twistedtv-pi-client/             # RASPBERRY PI COMPONENTS
│   ├── pi_daily_client/             # Daily.co client for Pi
│   │   ├── pi_daily_client.py      # Main RTVI client (active)
│   │   └── test_audio.py           # Audio testing utilities
│   │
│   ├── video_playback/              # Video playback service
│   │   ├── video_playback_service_mpv.py  # MPV playback (active)
│   │   ├── video_playback_service_vlc.py  # VLC alternative
│   │   └── video_player.py                # Shared utilities
│   │
│   ├── frontend/                    # Next.js UI (runs on Pi)
│   │   ├── pages/
│   │   │   ├── index.tsx            # Main page
│   │   │   └── api/                 # API routes
│   │   │       ├── connect_local.ts
│   │   │       ├── connect_runpod.ts
│   │   │       ├── start_pi_client.ts
│   │   │       └── cleanup_pi.ts
│   │   ├── components/
│   │   │   ├── ChatLog.tsx
│   │   │   ├── LoadingSpinner.tsx
│   │   │   └── AudioDeviceSelector.tsx
│   │   ├── styles/
│   │   ├── public/
│   │   └── package.json
│   │
│   ├── scripts/
│   │   ├── deploy_to_pi.sh         # Deployment script
│   │   └── generate-favicon.js     # Favicon generation
│   │
│   ├── requirements.txt             # Python dependencies for Pi
│   └── .env.example                # Environment variables template
│
└── twistedtv-video-server/          # VIDEO STORAGE & STREAMING
    ├── videos/                      # Video file storage
    ├── streaming_server.py          # Flask HTTP streaming server
    ├── threaded_server.py           # Alternative implementation
    └── requirements.txt             # Flask dependencies
```

### What Runs Where

**Server (Cloud/Local Machine):**
- `twistedtv-server/cinema_bot/server.py` - Main FastAPI backend
- `twistedtv-server/mcp_server/mock_server.py` or `server.py` - Video search
- `twistedtv-video-server/streaming_server.py` - Video file streaming

**Raspberry Pi (Installation Site):**
- `twistedtv-pi-client/pi_daily_client/pi_daily_client.py` - Daily.co client
- `twistedtv-pi-client/video_playback/video_playback_service_mpv.py` - Video playback
- `twistedtv-pi-client/frontend/` - Next.js dashboard (optional)

---

## Component Details

### 1. Cinema Bot Backend (Server)

**Location:** `twistedtv-server/cinema_bot/`

**Purpose:** Main conversation orchestration and LLM integration

**Key Technologies:**
- FastAPI - Web framework
- Pipecat - Audio pipeline framework
- Daily.co Python SDK - WebRTC transport
- OpenAI Whisper - Speech-to-text
- OpenAI GPT-4 - Conversation understanding
- MCP SDK - Tool calling protocol

**Key Features:**
- Two-conversation architecture:
  - User-facing: User input → Video description
  - Behind-the-scenes: User input → LLM reasoning → MCP tools → Video selection
- Function handlers for `search_video_clips` and `play_video_by_params`
- Status updates to frontend via RTVI protocol
- Conversation flow management with Pipecat-Flows
- CloudWatch logging integration

**Configuration:**
- Port: 8765 (default)
- Environment: `.env` file with API keys
- MCP: Communicates via stdio with mock_server.py

### 2. MCP Server (Server)

**Location:** `twistedtv-server/mcp_server/`

**Purpose:** Video search and clip selection via Model Context Protocol

**Two Modes:**

**Mock Mode (Development):**
- File: `mock_server.py`
- Keyword-based search with hardcoded scenes
- 5 test videos from educational films
- Fast, no external dependencies

**Production Mode (Future):**
- File: `server.py`
- Integrates with GoodCLIPS API
- Semantic multi-modal search
- Visual, audio, and text embeddings

**MCP Tools Exposed:**
- `search_video_clips(query, top_k)` - Search for matching clips
- `play_video_by_params(video_id, start, end)` - Select specific clip

**Communication:**
- Protocol: JSON-RPC over stdin/stdout
- Started as subprocess by cinema_bot
- No network ports needed

### 3. Video Playback Service (Pi)

**Location:** `twistedtv-pi-client/video_playback/video_playback_service_mpv.py`

**Purpose:** HTTP API for playing video clips on TV via mpv

**Endpoints:**
- `POST /play` - Play a video clip with start/end times
- `POST /stop` - Stop current playback
- `GET /status` - Get playback status
- `GET /health` - Health check

**Features:**
- DRM/KMS rendering for Raspberry Pi
- VT switching for framebuffer control
- Display blanking between clips
- Automatic cleanup on exit

**Configuration:**
- Port: 5000 (default)
- Display: HDMI output (primary or secondary)
- Player: mpv with hardware acceleration

### 4. Pi Daily.co Client (Pi)

**Location:** `twistedtv-pi-client/pi_daily_client/pi_daily_client.py`

**Purpose:** Bridge between Daily.co room and local Pi services

**Functions:**
- Capture audio from phone microphone
- Join Daily.co WebRTC room with token
- Stream audio to server
- Listen for video playback commands (RTVI messages)
- Call local video playback service

**Protocol Support:**
- RTVI (Real-Time Video Intelligence)
- Daily.co app messages
- VAD (Voice Activity Detection) for user speaking indicator

**Configuration:**
- Environment variables: `DAILY_ROOM_URL`, `DAILY_TOKEN`
- Backend URL: `BACKEND_URL` (for status updates)
- Video service: `VIDEO_SERVICE_URL` (default: http://localhost:5000)

### 5. Next.js Dashboard (Pi)

**Location:** `twistedtv-pi-client/frontend/`

**Purpose:** Web UI for monitoring and controlling the installation

**Features:**
- Start/stop conversation sessions
- View real-time transcription
- See selected video clips
- Monitor bot status
- Configure backend URL

**Access:**
- URL: `http://192.168.1.201:3000` (from local network)
- Port: 3000
- Mode: Development (`npm run dev`) or Production (`npm start`)

**API Routes:**
- `/api/connect_local` - Connect to local backend
- `/api/connect_runpod` - Connect to RunPod backend
- `/api/start_pi_client` - Spawn Pi Daily client process
- `/api/cleanup_pi` - Kill old Pi client processes

### 6. Video Streaming Server (Server)

**Location:** `twistedtv-video-server/streaming_server.py`

**Purpose:** HTTP server for streaming video files to Pi

**Features:**
- Serves video files over HTTP
- Support for range requests (seeking)
- Flask-based lightweight server
- CORS enabled for cross-origin access

**Configuration:**
- Port: 9000 (default)
- Video directory: `videos/`
- Supported formats: .mp4, .mkv, .avi, .mov

---

## Setup & Installation

### Prerequisites

**Server Machine:**
- Python 3.11+
- NVIDIA GPU (recommended for Whisper)
- Docker (optional, for containerized deployment)
- OpenAI API key
- Daily.co API key

**Raspberry Pi:**
- Raspberry Pi 4 or newer
- Raspberry Pi OS (64-bit recommended)
- Python 3.11+
- Node.js 18+
- Audio input device (USB sound card or HAT)
- HDMI output to TV

**Network:**
- Internet connection (for Daily.co WebRTC and OpenAI API)
- Local network for Pi communication (optional dashboard access)

### Server Setup

```bash
# Navigate to server directory
cd cinema-chat/twistedtv-server

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
nano .env  # Add your API keys

# Environment variables needed:
# OPENAI_API_KEY=sk-...
# DAILY_API_KEY=...
# DAILY_API_URL=https://api.daily.co/v1
# WHISPER_DEVICE=cuda  # or 'cpu'
# BACKEND_SERVER_URL=http://<your-ip>:8765
```

### Raspberry Pi Setup

```bash
# SSH to Pi
ssh pi@192.168.1.201

# Create twistedtv directory
mkdir -p ~/twistedtv-pi-client

# Copy files from server (run on server)
cd cinema-chat
./twistedtv-pi-client/scripts/deploy_to_pi.sh

# Or manually with rsync:
rsync -av twistedtv-pi-client/ pi@192.168.1.201:~/twistedtv-pi-client/

# On Pi - Install Python dependencies
cd ~/twistedtv-pi-client
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Install Node.js dependencies
cd frontend
npm install
npm run build  # For production

# Install system dependencies
sudo apt-get update
sudo apt-get install mpv python3-pyaudio portaudio19-dev
```

### Video Server Setup

```bash
# Navigate to video server directory
cd cinema-chat/twistedtv-video-server

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Add video files to videos/ directory
# Files should be named descriptively
```

---

## Deployment Guide

### Local Development Deployment

**Terminal 1 - MCP Server:**
```bash
cd twistedtv-server/mcp_server
python3 mock_server.py
```

**Terminal 2 - Cinema Bot Backend:**
```bash
cd twistedtv-server/cinema_bot
source ../venv/bin/activate
python3 server.py
```

**Terminal 3 - Video Streaming Server:**
```bash
cd twistedtv-video-server
source venv/bin/activate
python3 streaming_server.py
```

**Terminal 4 - Pi Dashboard (optional):**
```bash
# On Pi
cd ~/twistedtv-pi-client/frontend
npm run dev
```

### Production Deployment (Docker)

**Build Server Image:**
```bash
cd twistedtv-server
./build.sh
```

**Run Server Container:**
```bash
docker run -d \
  --name twistedtv-server \
  --gpus all \
  -p 8765:8765 \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  -e DAILY_API_KEY=$DAILY_API_KEY \
  -e WHISPER_DEVICE=cuda \
  twistedtv-server:latest
```

**Pi Services (systemd):**

Create `/etc/systemd/system/twistedtv-video.service`:
```ini
[Unit]
Description=TwistedTV Video Playback Service
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/twistedtv-pi-client/video_playback
ExecStart=/home/pi/twistedtv-pi-client/venv/bin/python3 video_playback_service_mpv.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Create `/etc/systemd/system/twistedtv-dashboard.service`:
```ini
[Unit]
Description=TwistedTV Dashboard
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/twistedtv-pi-client/frontend
ExecStart=/usr/bin/npm start
Restart=always
RestartSec=10
Environment="NODE_ENV=production"
Environment="PORT=3000"

[Install]
WantedBy=multi-user.target
```

Enable services:
```bash
sudo systemctl daemon-reload
sudo systemctl enable twistedtv-video
sudo systemctl enable twistedtv-dashboard
sudo systemctl start twistedtv-video
sudo systemctl start twistedtv-dashboard
```

### Cloud Deployment (RunPod)

```bash
# Build and push Docker image
cd twistedtv-server
docker build -t your-registry/twistedtv-server:latest .
docker push your-registry/twistedtv-server:latest

# Deploy on RunPod with GPU
# Use template with:
# - GPU: RTX 3090 or better
# - Expose port: 8765
# - Environment variables: OPENAI_API_KEY, DAILY_API_KEY
# - Docker image: your-registry/twistedtv-server:latest
```

---

## Operation & Usage

### Starting a Session

**1. Ensure Services Running:**
```bash
# Server
curl http://your-server:8765/health

# Pi video service
curl http://192.168.1.201:5000/health

# Pi dashboard (if using)
curl http://192.168.1.201:3000
```

**2. Start Session from Dashboard:**
- Open browser: `http://192.168.1.201:3000`
- Enter backend server URL: `http://your-server:8765/api`
- Click "Start Experience"
- Dashboard shows room URL and client PID

**3. Or Start Session via API:**
```bash
# Create room
curl -X POST http://your-server:8765/api/connect \
  -H "Content-Type: application/json" \
  -d '{"config":[]}' | jq

# Note the room_url and token

# Start Pi client (on Pi)
export DAILY_ROOM_URL="<room_url>"
export DAILY_TOKEN="<token>"
export BACKEND_URL="http://your-server:8765"
export VIDEO_SERVICE_URL="http://localhost:5000"
cd ~/twistedtv-pi-client/pi_daily_client
python3 pi_daily_client.py
```

**4. Monitor Logs:**
```bash
# Server logs
docker logs -f twistedtv-server

# Pi client logs
tail -f /tmp/pi_client.log

# Pi video logs
sudo journalctl -u twistedtv-video -f
```

**5. Use the Installation:**
- Speak into the phone
- Wait for transcription and LLM processing (~2-3 seconds)
- Video clip plays on TV
- TV blanks (NO SIGNAL) when waiting for next input

### Stopping a Session

**From Dashboard:**
- Click "Stop Experience" button
- Or refresh page (auto-cleanup on exit)

**Manually:**
```bash
# Kill Pi client
pkill -f pi_daily_client.py

# Or use cleanup script
bash ~/twistedtv-pi-client/scripts/cleanup_pi.sh
```

### Monitoring Status

**Check Conversation Status:**
```bash
curl http://your-server:8765/conversation-status/<identifier> | jq
```

**Response:**
```json
{
  "identifier": "uuid-here",
  "status": "active",
  "context": {
    "messages": [
      {"role": "user", "content": "hello"},
      {"role": "assistant", "content": "greeting"}
    ],
    "display_messages": [
      {"type": "video", "video_path": "hemo_1.mp4", "start": 0, "end": 5}
    ]
  }
}
```

---

## Debugging & Troubleshooting

### Common Issues

#### No Audio from Phone

**Symptoms:** Pi client joins room but server doesn't receive audio

**Debug:**
```bash
# On Pi - Test microphone
arecord -l  # List devices
arecord -D hw:1,0 -d 5 test.wav  # Record 5 seconds
aplay test.wav  # Play back

# Check Pi client logs
tail -f /tmp/pi_client.log | grep -i audio

# Check server logs
docker logs twistedtv-server | grep -i whisper
```

**Solutions:**
- Verify audio device in Pi client configuration
- Check USB sound card is connected and recognized
- Ensure Daily.co room has audio enabled
- Check firewall/network allows WebRTC

#### Video Commands Not Received

**Symptoms:** LLM selects video but Pi doesn't play it

**Debug:**
```bash
# Check Pi client receives messages
tail -f /tmp/pi_client.log | grep -i "video-playback-command"

# Check server sends commands
docker logs twistedtv-server | grep -i "Sending video command"

# Test video service directly
curl -X POST http://192.168.1.201:5000/play \
  -H 'Content-Type: application/json' \
  -d '{"video_url":"http://your-server:9000/videos/test.mp4","start":0,"end":5}'
```

**Solutions:**
- Verify Pi client is connected to Daily room
- Check RTVI message format is correct
- Ensure video playback service is running
- Check video URL is accessible from Pi

#### LLM Not Responding

**Symptoms:** User speaks, transcription works, but no LLM response

**Debug:**
```bash
# Check LLM API key
echo $OPENAI_API_KEY

# Check MCP server running
ps aux | grep mock_server

# Check server logs for errors
docker logs twistedtv-server | grep -i error

# Test OpenAI directly
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

**Solutions:**
- Verify OpenAI API key is valid
- Check MCP server process is running
- Review server logs for function call errors
- Ensure conversation context isn't too long

#### Video Playback Stuttering

**Symptoms:** Video plays but stutters or lags

**Debug:**
```bash
# Check Pi CPU/memory
top

# Check video file location
# Videos should be on Pi or fast network

# Check mpv logs
tail -f ~/mpv_*.log

# Test mpv directly
mpv --fs --no-audio <video_file>
```

**Solutions:**
- Use local video files on Pi (not streaming)
- Reduce video resolution/bitrate
- Enable hardware acceleration in mpv
- Close other processes on Pi

### Debug Logging

**Enable Verbose Logging:**

Server (.env):
```bash
LOG_LEVEL=DEBUG
PIPECAT_LOG_LEVEL=DEBUG
```

Pi Client:
```python
# In pi_daily_client.py
logging.basicConfig(level=logging.DEBUG)
```

**View All Logs:**
```bash
# Server
docker logs -f --tail 100 twistedtv-server

# Pi video service
sudo journalctl -u twistedtv-video -f --lines 100

# Pi dashboard
sudo journalctl -u twistedtv-dashboard -f --lines 100

# Pi client (if manual)
tail -f /tmp/pi_client.log
```

### Performance Monitoring

```bash
# Check server GPU usage
nvidia-smi -l 1

# Check Pi resources
htop

# Check network latency
ping 192.168.1.201

# Check Daily.co connection
# Look for "participant_joined" in server logs
# Look for "Successfully joined room" in Pi logs
```

---

## Development Guidelines

### Code Organization

**Server Code:**
- All server-side code in `twistedtv-server/`
- Separate bot logic from MCP server
- Use environment variables for configuration
- Never hardcode API keys

**Pi Code:**
- All Pi code in `twistedtv-pi-client/`
- Keep Pi client stateless (no persistent storage)
- Frontend is optional monitoring tool
- Video playback service should auto-recover

**Video Server:**
- All video files in `twistedtv-video-server/videos/`
- Use descriptive filenames
- Don't commit large video files to git

### Testing Strategy

**Unit Tests:**
- Test MCP tools independently
- Test conversation flows with mock LLM
- Test video playback service endpoints

**Integration Tests:**
- Test full flow: audio → transcription → LLM → video
- Test Pi client connection to Daily room
- Test video command delivery

**Hardware Tests:**
- Test with actual phone hardware
- Test on target Raspberry Pi model
- Test TV display and blanking
- Test in installation environment

### Import Paths

**Server imports:**
```python
from cinema_bot.server import CinemaBotServer
from cinema_bot.mcp_client import MCPClient
from mcp_server.mock_server import MockMCPServer
```

**Pi imports:**
```python
from pi_daily_client.pi_daily_client import PiDailyClient
from video_playback.video_playback_service_mpv import VideoPlaybackService
```

### Environment Management

**Never commit:**
- `.env` files with real API keys
- Large video files
- Temporary logs
- SSH keys

**Always provide:**
- `.env.example` with all required variables
- `requirements.txt` with pinned versions
- README.md with setup instructions
- Clear error messages

### File Synchronization

**CRITICAL: Always edit locally first, then sync to Pi**

```bash
# Edit files locally
vim twistedtv-pi-client/pi_daily_client/pi_daily_client.py

# Sync to Pi
rsync -av twistedtv-pi-client/ pi@192.168.1.201:~/twistedtv-pi-client/

# Restart service on Pi
ssh pi@192.168.1.201 'sudo systemctl restart twistedtv-video'

# Commit changes to git
git add twistedtv-pi-client/
git commit -m "Update Pi client"
```

**Never:**
- Edit files directly on Pi via SSH
- Make changes on Pi without syncing back
- Assume local and Pi files are in sync

---

## PR Preparation

### Repository Context

This codebase lives in Massimo's `cinema-chat` repository:
- **Owner:** Massimo (byron-the-bulb)
- **Primary Purpose:** GoodCLIPS semantic video search API (Go)
- **Our Addition:** TwistedTV art installation (Python)

**Massimo's Code (unchanged):**
- `cmd/` - Go API entry points
- `internal/` - Go API implementation
- `migrations/` - Database migrations
- `docker-compose.yml` - GoodCLIPS stack

**Our Code (new directories):**
- `twistedtv-server/` - Server-side bot + MCP
- `twistedtv-pi-client/` - Raspberry Pi client + frontend
- `twistedtv-video-server/` - Video storage + streaming

### PR Summary

**Title:** Add TwistedTV Art Installation Components

**Description:**

This PR adds the TwistedTV art installation to the cinema-chat repository. TwistedTV is a phone-based conversational AI that responds exclusively through old movie clips, using the GoodCLIPS semantic search API for video selection.

**What's Added:**

Three new top-level directories with complete separation from existing codebase:

1. **twistedtv-server/** - Server components (FastAPI bot + MCP server)
   - LLM conversation management (OpenAI GPT-4)
   - Whisper STT for speech-to-text
   - MCP server for video search (mock + real modes)
   - Integration with GoodCLIPS API
   - Daily.co WebRTC for audio transport

2. **twistedtv-pi-client/** - Raspberry Pi components (runs at installation)
   - Daily.co client for audio capture and video commands
   - Video playback service (mpv) for TV output
   - Next.js dashboard for monitoring (optional)

3. **twistedtv-video-server/** - Video storage and streaming
   - Flask HTTP server for video file delivery
   - Video file storage (not in git)

**What's NOT Changed:**
- Zero modifications to existing Go API code
- Zero modifications to existing infrastructure
- GoodCLIPS API can be used independently or with TwistedTV

**Architecture:**

Uses GoodCLIPS API for semantic video search via MCP (Model Context Protocol):
- LLM generates semantic descriptions ("person nodding in agreement")
- MCP server queries GoodCLIPS API `/api/v1/search/scenes`
- Returns best matching video clips
- Pi plays clips on TV via HDMI

**Documentation:**
- `TWISTEDTV.md` - Comprehensive documentation
- Individual README.md files in each directory
- Architecture diagrams and deployment guides

**Testing:**
- Tested with mock MCP server (keyword-based)
- Ready for GoodCLIPS integration (semantic search)
- Deployed and tested on Raspberry Pi 4

### Removed References

All code has been cleaned of previous project references:
- ❌ Sphinx (old project name)
- ❌ The Turning Point (reference project)
- ❌ Hume AI (emotion detection - not used)
- ❌ Cartesia/ElevenLabs TTS (replaced with video)

### Integration Points

**How TwistedTV uses GoodCLIPS:**

1. User speaks into phone → Transcribed by Whisper
2. LLM understands intent → Generates semantic description
3. MCP server calls: `POST /api/v1/search/scenes`
   ```json
   {
     "query": "person looking confused and scratching head",
     "top_k": 5,
     "modalities": ["visual", "text", "audio"]
   }
   ```
4. GoodCLIPS returns ranked video clips
5. Best match played on TV

**Benefits for GoodCLIPS:**
- Real-world usage example
- Demonstrates semantic search quality
- Provides test harness for API improvements
- Can be showcased as reference implementation

### Deployment Independence

Both systems can run independently:
- **GoodCLIPS alone:** Standard API deployment (no changes needed)
- **TwistedTV alone:** Uses mock MCP server for testing
- **Both together:** Full semantic video search integration

### Future Work

- [ ] Replace mock MCP server with real GoodCLIPS integration
- [ ] Add caching layer for frequently used clips
- [ ] Implement curator mode for manual clip selection
- [ ] Add analytics/metrics for popular clips
- [ ] Support multiple concurrent installations

---

## Appendix

### Port Reference

| Service | Port | Location |
|---------|------|----------|
| Cinema Bot Backend | 8765 | Server |
| Video Playback Service | 5000 | Pi |
| Next.js Dashboard | 3000 | Pi |
| Video Streaming Server | 9000 | Server |
| GoodCLIPS API | 8080 | Server |

### Environment Variables Reference

**Server (.env):**
```bash
# Required
OPENAI_API_KEY=sk-...
DAILY_API_KEY=...
DAILY_API_URL=https://api.daily.co/v1

# Optional
WHISPER_DEVICE=cuda
WHISPER_MODEL=base.en
LLM_MODEL=gpt-4o
BACKEND_SERVER_URL=http://localhost:8765
HOST=0.0.0.0
PORT=8765

# CloudWatch (optional)
CLOUDWATCH_LOG_GROUP=/twistedtv/backend
AWS_REGION=us-east-1
```

**Pi (.env.local in frontend):**
```bash
NEXT_PUBLIC_API_URL=http://your-server:8765/api
```

**Pi Client (environment variables):**
```bash
DAILY_ROOM_URL=https://your-domain.daily.co/room-name
DAILY_TOKEN=eyJhbGc...
BACKEND_URL=http://your-server:8765
VIDEO_SERVICE_URL=http://localhost:5000
```

### Network Requirements

**Outbound (Server):**
- api.openai.com:443 (OpenAI API)
- api.daily.co:443 (Daily.co API)
- *.daily.co:443 (Daily.co WebRTC)

**Outbound (Pi):**
- *.daily.co:443 (Daily.co WebRTC)
- your-server:8765 (Backend API)
- your-server:9000 (Video streaming)

**Inbound (Optional):**
- Pi:3000 (Dashboard, local network only)
- Pi:5000 (Video service, localhost only)

### Key Files Reference

**Most Important Files:**

| File | Purpose | Runs On |
|------|---------|---------|
| `twistedtv-server/cinema_bot/server.py` | Main FastAPI server | Server |
| `twistedtv-server/mcp_server/mock_server.py` | MCP video search | Server |
| `twistedtv-pi-client/pi_daily_client/pi_daily_client.py` | Daily.co client | Pi |
| `twistedtv-pi-client/video_playback/video_playback_service_mpv.py` | Video playback | Pi |
| `twistedtv-pi-client/frontend/pages/index.tsx` | Dashboard UI | Pi |
| `twistedtv-video-server/streaming_server.py` | Video HTTP server | Server |

### Version History

- **2025-11-30:** Restructured into three directories, comprehensive documentation
- **2025-11-24:** Direct spawn architecture, removed wrapper scripts
- **2025-11-20:** Initial implementation with mock MCP server
- **2025-11-12:** Project started, adapted from reference codebase

---

## Support & Contact

**For Issues:**
1. Check logs (see Debugging section)
2. Review conversation status API
3. Verify all services are running
4. Check environment variables
5. Test individual components

**Documentation:**
- This file: `TWISTEDTV.md` - Comprehensive reference
- Server: `twistedtv-server/README.md` - Server setup
- Pi: `twistedtv-pi-client/README.md` - Pi setup
- Video: `twistedtv-video-server/README.md` - Video server setup

**Repository:**
- https://github.com/byron-the-bulb/cinema-chat (Massimo's repo)
- GoodCLIPS API documentation (when available)

---

*Last updated: 2025-11-30*
