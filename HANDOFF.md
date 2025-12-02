# TwistedTV - Project Handoff Documentation

**Date:** 2025-11-30
**Status:** Ready for deployment and testing

---

## Executive Summary

TwistedTV is an art installation where users speak into a vintage phone and receive responses via old movie clips displayed on a TV. The system uses:
- **Speech-to-Text** (Whisper)
- **LLM** (OpenAI GPT-4) for conversation
- **Semantic Video Search** (GoodCLIPS API)
- **WebRTC** (Daily.co) for audio transport
- **Raspberry Pi** for local I/O (phone audio input, TV video output)

**Key Point:** The bot "speaks" exclusively through video clips - there is no text-to-speech.

---

## Repository Structure

```
cinema-chat/
├── README.md                      # GoodCLIPS API docs (Massimo's work)
├── TWISTEDTV_README.md            # Quick start guide
├── TWISTEDTV.md                   # Comprehensive technical docs
├── HANDOFF.md                     # This file
│
├── cmd/                           # GoodCLIPS API (Go) - Massimo's
├── internal/                      # GoodCLIPS internals - Massimo's
├── migrations/                    # Database migrations - Massimo's
├── docker-compose.yml             # GoodCLIPS services - Massimo's
│
├── twistedtv-server/              # ✅ Bot Server (Python/FastAPI)
│   ├── cinema_bot/                # Bot logic, Whisper STT, LLM
│   ├── mcp_server/                # MCP tools for video search
│   ├── Dockerfile                 # GPU-enabled container
│   ├── build.sh                   # Docker build script
│   └── README.md
│
├── twistedtv-pi-client/           # ✅ Raspberry Pi Components
│   ├── pi_daily_client/           # Audio capture & Daily.co client
│   ├── video_playback/            # MPV video player
│   ├── frontend/                  # Next.js dashboard
│   ├── scripts/                   # Utilities
│   └── README.md
│
└── twistedtv-video-server/        # ✅ Video Storage & Streaming
    ├── videos/                    # Video files
    ├── streaming_server.py        # Flask HTTP server
    └── README.md
```

---

## System Architecture

### High-Level Flow

```
Phone → Pi (Audio) → Daily.co WebRTC → TwistedTV Server (Cloud GPU)
                                              ↓
                                     Whisper STT → LLM
                                              ↓
                                  MCP Client (video search tool)
                                              ↓
                                  GoodCLIPS API (semantic search)
                                              ↓
                                      Video HTTP Server
                                              ↓
                                 Pi MPV Player → TV Output
```

### Component Responsibilities

**TwistedTV Server (Cloud GPU):**
- FastAPI backend (port 8765)
- Whisper STT for speech transcription
- OpenAI GPT-4 for conversation logic
- Pipecat SDK for audio pipeline orchestration
- MCP client for video selection
- Daily.co WebRTC for audio transport

**Raspberry Pi Client:**
- Next.js dashboard (port 3000) - monitoring interface
- Pi Daily Client - ALSA audio capture, WebRTC client
- MPV Video Service (port 5000) - video playback on TV
- Systemd service auto-starts frontend on boot

**Video Server (Installation Computer):**
- Flask HTTP server (port 9000)
- Serves video files to Pi player
- Hosts video library

**GoodCLIPS API (Massimo's Backend):**
- Go + Postgres + Redis
- Multi-modal semantic search (visual, audio, text embeddings)
- Endpoint: `/api/v1/search/scenes`

---

## Current Deployment State

### Raspberry Pi Configuration

**Location:** On-site at installation
**IP Address:** `192.168.1.201`
**User:** `twistedtv`

**Directory Structure on Pi:**
```
/home/twistedtv/
├── twistedtv-new/                  # NEW: Current active structure
│   ├── pi_daily_client/
│   │   └── pi_daily_client.py
│   ├── video_playback/
│   │   ├── video_playback_service_mpv.py
│   │   └── video_player.py
│   └── frontend/                   # Next.js dashboard
│       ├── .next/                  # Production build
│       ├── pages/
│       ├── components/
│       └── node_modules/
├── venv_daily/                     # Python virtual environment
├── audio_device.conf               # Auto-detected audio device
└── cleanup_pi.sh                   # Process cleanup script
```

**Active Services:**
- `cinema-dashboard.service` - Next.js frontend
  - Status: Running (PID 7338)
  - Working Directory: `/home/twistedtv/twistedtv-new/frontend`
  - Port: 3000
  - Auto-starts on boot

**Dashboard URL:** http://192.168.1.201:3000

**API Routes (Next.js):**
- `/api/start_pi_client` - Spawns Pi Daily client and video service
- `/api/cleanup_pi` - Terminates all Pi processes
- `/api/connect` - Connect to RunPod cloud backend
- `/api/connect_local` - Connect to local backend
- `/api/needs_help` - Trigger help request

**Process Management:**
- Pi client and video service are **spawned on demand** by `/api/start_pi_client`
- Not managed by systemd (only dashboard is)
- Cleanup on session end via `/api/cleanup_pi`

---

## Configuration

### Environment Variables

**Server (.env in `twistedtv-server/cinema_bot/`)**
```bash
# Required
OPENAI_API_KEY=sk-...
DAILY_API_KEY=...
WHISPER_DEVICE=cuda
REPO_ID=Systran/faster-distil-whisper-medium.en

# Optional - CloudWatch Logging
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-west-2
CLOUDWATCH_LOG_GROUP=/twistedtv

# Optional - Model Mount Point
MOUNT_POINT=/workspace
```

**Pi Frontend (.env in `twistedtv-pi-client/frontend/`)**
```bash
# Connection Mode
NEXT_PUBLIC_API_ENDPOINT=/connect_local  # or /connect for RunPod

# RunPod Configuration
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
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-west-2
```

### Hardware Configuration

**Phone Audio Input:**
- Device: Auto-detected ALSA device (stored in `/home/twistedtv/audio_device.conf`)
- Format: 16kHz, 1 channel, 16-bit PCM
- Detection: Run `arecord -l` to list devices, auto-configured on first run

**TV Video Output:**
- Connection: HDMI
- Player: MPV with hardware acceleration
- Port: HTTP server on port 5000

---

## Deployment Instructions

### 1. Server Deployment (RunPod/Cloud GPU)

```bash
cd twistedtv-server
./build.sh  # Builds twistedtv-server:latest

# Push to Docker Hub
docker tag twistedtv-server:latest yourusername/twistedtv-server:latest
docker push yourusername/twistedtv-server:latest

# Deploy on RunPod
# - Select GPU instance (A4000, RTX 4090, etc.)
# - Use template with image: yourusername/twistedtv-server:latest
# - Set environment variables
# - Expose port 8765
```

### 2. Pi Client Setup

**Initial Setup:**
```bash
ssh twistedtv@192.168.1.201

# Install dependencies
sudo apt-get update
sudo apt-get install -y mpv alsa-utils python3-venv npm

# Python virtual environment already set up at ~/venv_daily
source ~/venv_daily/bin/activate
pip install daily-python sounddevice

# Frontend already deployed at ~/twistedtv-new/frontend
cd ~/twistedtv-new/frontend
npm install
npm run build
```

**Systemd Service:**
```bash
# Service file: /etc/systemd/system/cinema-dashboard.service
sudo systemctl enable cinema-dashboard.service
sudo systemctl start cinema-dashboard.service
sudo systemctl status cinema-dashboard.service
```

**Update Code on Pi:**
```bash
# From development machine:
cd /home/va55/code/cinema-chat
rsync -av --exclude node_modules twistedtv-pi-client/ twistedtv@192.168.1.201:~/twistedtv-new/

# On Pi:
ssh twistedtv@192.168.1.201
cd ~/twistedtv-new/frontend
npm run build
sudo systemctl restart cinema-dashboard.service
```

### 3. Video Server Setup

```bash
cd twistedtv-video-server
pip install -r requirements.txt
python streaming_server.py  # Starts on port 9000
```

---

## Testing Procedures

### 1. Test Audio Capture on Pi

```bash
ssh twistedtv@192.168.1.201
arecord -l  # List audio devices
arecord -D plughw:1,0 -f cd test.wav  # Record test
aplay test.wav  # Playback test
```

### 2. Test Video Playback on Pi

```bash
ssh twistedtv@192.168.1.201
mpv http://192.168.1.XXX:9000/videos/test.mp4
```

### 3. Test Full System Flow

1. **Start Video Server** (installation computer)
   ```bash
   cd twistedtv-video-server
   python streaming_server.py
   ```

2. **Verify Pi Dashboard** (http://192.168.1.201:3000)
   - Should see "Cinema Chat" interface
   - "Connect to Local Backend" button available

3. **Start Server** (RunPod or local GPU)
   ```bash
   docker run --gpus all -p 8765:8765 \
     -e OPENAI_API_KEY=... \
     -e DAILY_API_KEY=... \
     twistedtv-server:latest
   ```

4. **Connect from Pi**
   - Click "Connect to Local Backend"
   - Verify processes start:
     ```bash
     ssh twistedtv@192.168.1.201
     ps aux | grep -E "(pi_daily_client|video_playback)"
     ```

5. **Test Conversation**
   - Speak into phone
   - Verify transcription appears in dashboard
   - Verify video plays on TV

---

## Troubleshooting

### Pi Client Won't Start

**Check Dashboard Service:**
```bash
ssh twistedtv@192.168.1.201
sudo systemctl status cinema-dashboard.service
journalctl -u cinema-dashboard.service -f
```

**Check Port 3000:**
```bash
lsof -i :3000
# Should show npm process from /home/twistedtv/twistedtv-new/frontend
```

### No Audio Capture

**Check Audio Device:**
```bash
ssh twistedtv@192.168.1.201
arecord -l  # List devices
cat /home/twistedtv/audio_device.conf  # Check configured device
```

**Test Recording:**
```bash
arecord -D plughw:1,0 -f cd test.wav  # Adjust device as needed
```

### Video Won't Play

**Check Video Service:**
```bash
curl http://192.168.1.XXX:9000/ping  # Should return "pong"
ls -la twistedtv-video-server/videos/  # Check video files exist
```

**Check MPV:**
```bash
which mpv  # Should be installed
mpv --version
```

### Processes Not Spawning

**Check API Logs:**
```bash
ssh twistedtv@192.168.1.201
tail -f /tmp/pi_client_*.log  # Pi client logs
tail -f /tmp/video_mpv.log    # Video service logs
```

**Manual Process Cleanup:**
```bash
bash /home/twistedtv/cleanup_pi.sh
```

### Server Crashes

**Check CloudWatch Logs** (if configured):
- Log Group: `/twistedtv`
- Search for errors

**Check Docker Logs:**
```bash
docker logs <container_id>
```

**Verify GPU:**
```bash
nvidia-smi  # Should show GPU usage
```

---

## Known Issues & Future Work

### Current Limitations

1. **Mock MCP Server:** Currently using keyword-based video search
   - **Future:** Integrate real GoodCLIPS API for semantic search

2. **Static Video Library:** Videos must be manually added
   - **Future:** Dynamic video library management interface

3. **No Curator Mode:** Automated clip selection only
   - **Future:** Manual override for clip selection

4. **Basic Error Handling:** Limited retry logic
   - **Future:** Robust error recovery and fallbacks

### Manual Cleanup Needed

**Permission-locked directories:**
```bash
# These directories have restrictive permissions and should be manually removed:
data/               # Contains video_2_keyframes with many locked files
models/             # Empty, root-owned
videos/             # Contains only test.mp4

# To remove (requires manual intervention):
sudo rm -rf data/ models/ videos/
```

---

##Documentation Files

1. **[TWISTEDTV_README.md](TWISTEDTV_README.md)** - Quick start guide
2. **[TWISTEDTV.md](TWISTEDTV.md)** - Comprehensive technical documentation
3. **[twistedtv-server/README.md](twistedtv-server/README.md)** - Server component details
4. **[twistedtv-pi-client/README.md](twistedtv-pi-client/README.md)** - Pi client setup
5. **[twistedtv-video-server/README.md](twistedtv-video-server/README.md)** - Video server details
6. **[README.md](README.md)** - GoodCLIPS API (Massimo's documentation)
7. **[HANDOFF.md](HANDOFF.md)** - This file (project handoff)

---

## Development Workflow

### Local Development

1. **Clone Repository:**
   ```bash
   git clone https://github.com/byron-the-bulb/cinema-chat.git
   cd cinema-chat
   ```

2. **Build Server:**
   ```bash
   cd twistedtv-server
   ./build.sh
   ```

3. **Run Server Locally:**
   ```bash
   docker run --gpus all -p 8765:8765 \
     -e OPENAI_API_KEY=... \
     -e DAILY_API_KEY=... \
     twistedtv-server:latest
   ```

4. **Test Pi Client Locally:**
   ```bash
   cd twistedtv-pi-client/frontend
   npm install
   npm run dev  # Runs on http://localhost:3000
   ```

### Code Changes

**Server Changes:**
1. Edit files in `twistedtv-server/`
2. Rebuild Docker image: `./build.sh`
3. Push to Docker Hub (if cloud deployment)
4. Redeploy on RunPod

**Pi Client Changes:**
1. Edit files in `twistedtv-pi-client/`
2. Sync to Pi: `rsync -av --exclude node_modules twistedtv-pi-client/ twistedtv@192.168.1.201:~/twistedtv-new/`
3. Rebuild frontend: `ssh twistedtv@192.168.1.201 'cd ~/twistedtv-new/frontend && npm run build'`
4. Restart service: `ssh twistedtv@192.168.1.201 'sudo systemctl restart cinema-dashboard.service'`

### Git Workflow

**Current Branch:** `twistedtv`
**Main Branch:** `main`

**Committing Changes:**
```bash
git add .
git commit -m "Description of changes"
git push origin twistedtv
```

**Creating PR for Massimo:**
- Base branch: `main` (Massimo's repo)
- Compare branch: `twistedtv`
- Focus on TwistedTV directories only (`twistedtv-*/`)
- No changes to GoodCLIPS components (`cmd/`, `internal/`, `migrations/`, root files)

---

## Contact & Handoff Notes

**Massimo's Components (Do Not Modify):**
- `cmd/` - Go API server
- `internal/` - Go internals
- `migrations/` - Database migrations
- `docker-compose.yml` - GoodCLIPS services
- `README.md` - GoodCLIPS documentation

**TwistedTV Components (Safe to Modify):**
- `twistedtv-server/` - Bot backend
- `twistedtv-pi-client/` - Raspberry Pi components
- `twistedtv-video-server/` - Video storage/streaming
- `TWISTEDTV*.md` - TwistedTV documentation

**Key Configuration:**
- Pi IP: `192.168.1.201`
- Video server port: `9000`
- Server API port: `8765`
- Pi dashboard port: `3000`

**Important Notes:**
- All environment variables contain real API keys (not shown in docs)
- Pi systemd service points to `/home/twistedtv/twistedtv-new/frontend`
- Old directories (`cinema-bot-app/`, `mcp/`) have been removed from repo
- Frontend build is production-ready and deployed on Pi

---

## Project Status

✅ **Complete:**
- Server Docker image built and tested
- Pi client deployed and running
- Frontend dashboard accessible at http://192.168.1.201:3000
- Systemd service configured for auto-start
- Audio device auto-detection working
- Video playback service functional
- All code cleaned up (no debug logging, no TODO comments)
- Documentation comprehensive and up-to-date

⏳ **Pending:**
- Integration with real GoodCLIPS API (currently using mock)
- End-to-end testing with actual phone and TV
- Video library population
- RunPod cloud deployment

🎯 **Ready for:**
- Full system testing
- PR submission to Massimo's repository
- Installation deployment

---

**Last Updated:** 2025-11-30
**Prepared By:** Claude Code
**For:** Massimo (GoodCLIPS) & TwistedTV Team
