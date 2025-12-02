# TwistedTV - Cinema Chat Installation

**Art installation where users speak into a vintage phone and receive responses via old movie clips displayed on a TV.**

---

## Project Structure

This repository contains both **Massimo's GoodCLIPS API** (Go-based semantic video search) and the **TwistedTV system** (Python/TypeScript voice bot that uses GoodCLIPS).

```
cinema-chat/
├── README.md                       # GoodCLIPS API documentation (Massimo's work)
├── TWISTEDTV.md                    # Comprehensive TwistedTV documentation
├── TWISTEDTV_README.md             # This file - Quick start guide
│
├── cmd/                            # GoodCLIPS API server (Go)
├── internal/                       # GoodCLIPS internals (Go)
├── migrations/                     # Database migrations (Go)
├── docker-compose.yml              # GoodCLIPS services (Postgres, Redis, API)
│
├── twistedtv-server/               # TwistedTV Bot Server (Python)
│   ├── cinema_bot/                 # FastAPI bot with Whisper STT + LLM
│   ├── mcp_server/                 # MCP tools for video search/playback
│   ├── Dockerfile                  # Server container with GPU support
│   ├── build.sh                    # Docker build script
│   └── README.md                   # Server-specific documentation
│
├── twistedtv-pi-client/            # Raspberry Pi Client Components
│   ├── pi_daily_client/            # Daily.co audio client
│   ├── video_playback/             # MPV video playback service
│   ├── frontend/                   # Next.js dashboard (runs on Pi)
│   ├── scripts/                    # Pi-specific utilities
│   └── README.md                   # Pi client documentation
│
└── twistedtv-video-server/         # Video Storage & Streaming
    ├── videos/                     # Video file storage
    ├── streaming_server.py         # Flask HTTP video server
    └── README.md                   # Video server documentation
```

---

## System Components

### 1. **TwistedTV Server** (`twistedtv-server/`)
- FastAPI backend with Whisper STT (speech-to-text)
- OpenAI GPT-4 for conversation
- MCP (Model Context Protocol) client for video selection
- Pipecat SDK for audio pipeline orchestration
- Daily.co WebRTC for audio transport
- Runs on RunPod cloud GPU instances or local GPU

### 2. **Raspberry Pi Client** (`twistedtv-pi-client/`)
- **Next.js Frontend**: Dashboard for monitoring conversations (port 3000)
- **Pi Daily Client**: Audio capture and WebRTC client
- **Video Playback Service**: MPV-based player for TV output
- **Audio Capture**: ALSA audio input from phone microphone
- Runs on-site on Raspberry Pi connected to phone and TV

### 3. **Video Server** (`twistedtv-video-server/`)
- Flask HTTP server streaming video files
- Serves videos to Pi video playback service
- Runs on installation computer (port 9000)

### 4. **GoodCLIPS API** (Root directory - Massimo's work)
- Go + Postgres + Redis semantic search backend
- Multi-modal video embeddings (visual, audio, text)
- Provides `/api/v1/search/scenes` endpoint
- Used by MCP server to find matching video clips

---

## How It Works

```
Phone → Pi (Audio Input) → Daily.co WebRTC → TwistedTV Server (Cloud)
                                                      ↓
                                           Whisper STT → LLM
                                                      ↓
                                          MCP Client (video search)
                                                      ↓
                                          GoodCLIPS API (semantic search)
                                                      ↓
                                          Video HTTP Server
                                                      ↓
                                    Pi MPV Player → TV Output
```

**Conversation Flow:**
1. User speaks into vintage phone
2. Pi captures audio via ALSA
3. Audio sent to cloud server via Daily.co WebRTC
4. Whisper transcribes speech to text
5. LLM processes conversation and generates semantic video description
6. MCP server searches GoodCLIPS for matching clip
7. Video streamed to Pi and played on TV

**No TTS**: The bot "speaks" exclusively through video clips - there is no text-to-speech.

---

## Quick Start

### Prerequisites
- **Development machine**: Docker, Node.js, Python 3.11+
- **Raspberry Pi**: Raspbian OS, audio input device, HDMI TV
- **Cloud GPU** (optional): RunPod account with GPU instance
- **API Keys**: OpenAI, Daily.co

### Setup

#### 1. Clone Repository
```bash
git clone https://github.com/byron-the-bulb/cinema-chat.git
cd cinema-chat
```

#### 2. Server Setup
See [twistedtv-server/README.md](twistedtv-server/README.md) for:
- Docker build instructions
- Environment variable configuration
- RunPod deployment

**Local Server Installation (with CUDA):**
```bash
cd twistedtv-server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# IMPORTANT: Run CUDA setup script to fix library version mismatch
./setup_cuda.sh
```

The `setup_cuda.sh` script creates symbolic links for CUDA libraries. This is required because PyTorch CUDA 11.8 expects CUDA 12 library names, but the installed packages provide CUDA 11 libraries.

#### 3. Pi Client Setup
See [twistedtv-pi-client/README.md](twistedtv-pi-client/README.md) for:
- Audio device configuration
- Frontend deployment
- Systemd service setup

#### 4. Video Server Setup
See [twistedtv-video-server/README.md](twistedtv-video-server/README.md) for:
- Video file management
- HTTP server configuration

---

## Configuration Files

### Server Environment (`.env` in `twistedtv-server/cinema_bot/`)
```bash
# LLM & STT
OPENAI_API_KEY=sk-...
WHISPER_DEVICE=cuda
REPO_ID=Systran/faster-distil-whisper-medium.en

# Daily.co WebRTC
DAILY_API_KEY=...

# AWS CloudWatch (optional logging)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
CLOUDWATCH_LOG_GROUP=/twistedtv
```

### Pi Frontend Environment (`.env` in `twistedtv-pi-client/frontend/`)
```bash
# Connection mode
NEXT_PUBLIC_API_ENDPOINT=/connect_local  # or /connect (for RunPod)

# RunPod configuration
NEXT_PUBLIC_RUNPOD_TEMPLATE_ID=...
RUNPOD_API_KEY=...

# API Keys
OPENAI_API_KEY=sk-...
DAILY_API_KEY=...

# Whisper STT
WHISPER_DEVICE=cuda
REPO_ID=Systran/faster-distil-whisper-medium.en

# CloudWatch
CLOUDWATCH_LOG_GROUP=/twistedtv
```

---

## Documentation

- **[TWISTEDTV.md](TWISTEDTV.md)** - Comprehensive system documentation
- **[twistedtv-server/README.md](twistedtv-server/README.md)** - Server component details
- **[twistedtv-pi-client/README.md](twistedtv-pi-client/README.md)** - Pi client setup
- **[twistedtv-video-server/README.md](twistedtv-video-server/README.md)** - Video server details
- **[README.md](README.md)** - GoodCLIPS API documentation (Massimo's)

---

## Development Workflow

### Local Testing
1. Start GoodCLIPS API: `docker-compose up -d`
2. Build server container: `cd twistedtv-server && ./build.sh`
3. Run server: `docker run --gpus all twistedtv-server:latest`
4. Start Pi frontend: `cd twistedtv-pi-client/frontend && npm run dev`

### Deployment
1. **Cloud**: Push server image to Docker Hub, deploy on RunPod
2. **Pi**: Sync code via rsync, restart systemd services
3. **Video Server**: Run Flask server on installation computer

---

## Testing

### Test Audio Capture on Pi
```bash
ssh twistedtv@192.168.1.201
arecord -l  # List audio devices
arecord -D plughw:1,0 -f cd test.wav  # Test recording
```

### Test Video Playback on Pi
```bash
ssh twistedtv@192.168.1.201
mpv http://192.168.1.XXX:9000/videos/test.mp4  # Test streaming
```

### Test Full Flow
1. Open Pi dashboard: `http://192.168.1.201:3000`
2. Click "Connect to Local Backend"
3. Speak into phone
4. Verify transcription appears
5. Verify video plays on TV

---

## Troubleshooting

### Pi Client Won't Connect
- Check Daily.co room URL is valid
- Verify backend is accessible from Pi
- Check firewall rules on cloud instance

### No Audio Capture
- Run `arecord -l` to verify audio device
- Check `/home/twistedtv/audio_device.conf`
- Verify Python client has correct `AUDIO_DEVICE` env var

### Video Won't Play
- Verify video server is running: `curl http://192.168.1.XXX:9000/ping`
- Check video file permissions
- Verify MPV is installed on Pi: `which mpv`

### Server Crashes
- Check CloudWatch logs (if configured)
- Check Docker logs: `docker logs <container_id>`
- Verify GPU is available: `nvidia-smi`

---

## Architecture Notes

### Why This Structure?
- **3 Directories**: Clean separation of server (cloud), Pi client (on-site), and video storage
- **MCP Protocol**: Standardized tool calling for video search/playback
- **Daily.co WebRTC**: Reliable audio transport with low latency
- **MPV Player**: Robust video playback with hardware acceleration
- **Systemd Services**: Pi components auto-start on boot

### Key Design Decisions
- **No TTS**: Videos serve as the bot's voice
- **Stateless Server**: Each conversation spawns new processes
- **Pi as Client**: Handles local I/O (audio, video) with cloud brain
- **MCP Mock Server**: Keyword-based fallback when GoodCLIPS unavailable

---

## Future Enhancements

- [ ] Integrate real GoodCLIPS API (currently using mock keyword search)
- [ ] Implement weighted multi-modal search
- [ ] Add curator mode for manual clip selection
- [ ] Emotion detection in user's voice (optional)
- [ ] Analytics dashboard for clip resonance tracking

---

## Contributing

This is a collaborative project between:
- **Massimo** - GoodCLIPS semantic search backend (Go)
- **TwistedTV Team** - Voice bot and installation components (Python/TypeScript)

Changes to GoodCLIPS components (`cmd/`, `internal/`, `migrations/`, `docker-compose.yml`, root `README.md`) should be coordinated with Massimo.

Changes to TwistedTV components (`twistedtv-*/`) can be made independently.

---

## License

TBD
