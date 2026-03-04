# TwistedTV - Project Handoff Documentation

**Date:** 2026-02-25
**Status:** Deployed and operational

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
Phone → Pi (Audio) → Daily.co WebRTC → Server (192.168.1.106)
                                              ↓
                                     Whisper STT → GPT-4
                                              ↓
                                  MCP Server (video search tool)
                                              ↓
                                  GoodCLIPS API (semantic search)
                                              ↓
                                      Video HTTP Server :9000
                                              ↓
                                 Pi MPV Player → TV Output
```

**Note:** Video ingestion runs in the cloud (RunPod), NOT on the server. See `cloud-ingestion/process-movie.sh`.

### Component Responsibilities

**Server (192.168.1.106, Fedora):**
- FastAPI backend (port 8765) — bot orchestration, Whisper STT, GPT-4
- GoodCLIPS Go API (port 8080) — semantic video search (Docker)
- PostgreSQL + pgvector (port 5432) — scene embeddings (Docker)
- Redis (port 6379) — job queue (Docker)
- Flask video streaming (port 9000) — serves .mp4 files to Pi
- Managed by: systemd services + Docker Compose

**Raspberry Pi (192.168.1.109):**
- Next.js dashboard (port 3000) — monitoring interface
- Pi Daily Client — ALSA audio capture, WebRTC client
- MPV Video Service (port 5000) — video playback on TV
- Managed by: user-level systemd (video-player.service, frontend.service)

**Cloud — RunPod (temporary, during ingestion only):**
- Temporary GPU pods for processing movies into embeddings
- Script: `cloud-ingestion/process-movie.sh`
- Creates pod → processes movie → exports DB → imports locally → terminates pod

---

## Current Deployment State

### Server Configuration (192.168.1.106)

**OS:** Fedora Linux
**User:** `twistedtv`

**Active Services:**
- `twistedtv-server.service` — FastAPI bot (port 8765), system-level systemd
- `twistedtv-video-server.service` — Flask video streaming (port 9000), system-level systemd
- Docker Compose stack: goodclips-api (8080), postgres (5432), redis (6379)

**Key Paths:**
- Project: `/home/twistedtv/cinema-chat`
- Python venv: `twistedtv-server/venv/` (Python 3.12)
- .env: `twistedtv-server/cinema_bot/.env`
- Videos: `data/videos/`
- Systemd services: `/etc/systemd/system/twistedtv-*.service`
- Logs: `/tmp/twistedtv-server.log`, `/tmp/twistedtv-video-server.log`

**Server Reinstall:** See "Server Reinstall Guide" in `TWISTEDTV.md` for step-by-step instructions.

### Raspberry Pi Configuration (192.168.1.109)

**User:** `twistedtv`

**Directory Structure on Pi:**
```
/home/twistedtv/
├── twistedtv-pi-client/
│   ├── pi_daily_client/
│   │   └── pi_daily_client.py
│   ├── video_playback/
│   │   └── video_playback_service_mpv.py
│   └── frontend/                   # Next.js dashboard
│       ├── .next/                  # Production build
│       ├── .env                    # Server URL + API keys
│       └── pages/
├── venv_daily/                     # Python virtual environment
├── videos/                         # Local video files (static.mp4)
└── audio_device.conf               # Auto-detected audio device
```

**Active Services (user-level systemd):**
- `video-player.service` — MPV playback on HDMI (port 5000)
- `frontend.service` — Next.js dashboard (port 3000)

**Dashboard URL:** http://192.168.1.109:3000

**Process Management:**
- Video player and frontend are always-on systemd user services
- Pi Daily Client is **spawned on demand** by the dashboard's `/api/start_pi_client` route
- Cleanup on session end via `/api/cleanup_pi`

**SSH Access:** Requires agent forwarding from local machine: `ssh -A twistedtv@192.168.1.106`, then `ssh twistedtv@192.168.1.109`

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

### Server Reinstall

See the detailed step-by-step guide in **`TWISTEDTV.md` → "Server Reinstall Guide"**. It covers:
1. System dependencies (Python 3.12, Docker, psql)
2. Python venv and pip install
3. .env configuration
4. Docker Compose (GoodCLIPS stack) + timm fix
5. Systemd services (with SELinux workaround)
6. Movie ingestion via RunPod
7. Verification tests

### Pi Client (already deployed)

The Pi at 192.168.1.109 should already be set up. If you need to update it:

```bash
# SSH to Pi (requires agent forwarding from local machine)
ssh -A twistedtv@192.168.1.106
ssh twistedtv@192.168.1.109

# Update server URL if IP changed
nano ~/twistedtv-pi-client/frontend/.env
# Set NEXT_PUBLIC_API_URL=http://<new-server-ip>:8765

# Rebuild and restart
cd ~/twistedtv-pi-client/frontend
npm run build
systemctl --user restart frontend
```

---

## Testing Procedures

### 1. Test Audio Capture on Pi

```bash
ssh twistedtv@192.168.1.109
arecord -l  # List audio devices
arecord -D plughw:1,0 -f cd test.wav  # Record test
aplay test.wav  # Playback test
```

### 2. Test Video Playback on Pi

```bash
ssh twistedtv@192.168.1.109
mpv http://192.168.1.XXX:9000/videos/test.mp4
```

### 3. Test Full System Flow

1. **Start Video Server** (installation computer)
   ```bash
   cd twistedtv-video-server
   python streaming_server.py
   ```

2. **Verify Pi Dashboard** (http://192.168.1.109:3000)
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
     ssh twistedtv@192.168.1.109
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
ssh twistedtv@192.168.1.109
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
ssh twistedtv@192.168.1.109
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
ssh twistedtv@192.168.1.109
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

## Known Issues & Gotchas

1. **SELinux on Fedora** — Systemd cannot execute binaries from `/home`. Wrap `ExecStart` in `/bin/bash -c '...'`. Copy (not symlink) service files to `/etc/systemd/system/`.

2. **Python 3.12 required** — Python 3.14 is too new (missing wheels), Python 3.11 not on Fedora 43. Install: `sudo dnf install -y python3.12 python3.12-devel`

3. **Docker image timm/torchvision mismatch** — After `docker compose up`, run: `docker exec goodclips-api pip uninstall -y timm torchvision`

4. **RunPod TCP proxy is HTTP-only** — Cannot use `proxy.runpod.net` for pg_dump. Use pod's direct public IP. `process-movie.sh` handles this automatically.

5. **`data/videos/` may be root-owned** — Docker creates it as root. Fix: `sudo chown -R twistedtv:twistedtv data/`

6. **Docker group needs re-login** — After `usermod -aG docker`, log out and back in.

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
2. Sync to Pi: `rsync -av --exclude node_modules twistedtv-pi-client/ twistedtv@192.168.1.109:~/twistedtv-new/`
3. Rebuild frontend: `ssh twistedtv@192.168.1.109 'cd ~/twistedtv-new/frontend && npm run build'`
4. Restart service: `ssh twistedtv@192.168.1.109 'sudo systemctl restart cinema-dashboard.service'`

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
- Server IP: `192.168.1.106`
- Pi IP: `192.168.1.109`
- Server API port: `8765`
- GoodCLIPS API port: `8080`
- Video server port: `9000`
- Pi video playback port: `5000`
- Pi dashboard port: `3000`

**Important Notes:**
- Server .env at `twistedtv-server/cinema_bot/.env` (API keys — not in git)
- Pi .env at `~/twistedtv-pi-client/frontend/.env`
- Server systemd services use `/bin/bash -c` wrapper (SELinux requirement)
- Pi user-level systemd: `video-player.service`, `frontend.service`

---

## Project Status

✅ **Complete:**
- Server deployed on 192.168.1.106 (Fedora) with systemd services
- GoodCLIPS API integrated and working (semantic search via e5-base-v2 text embeddings)
- Cloud ingestion pipeline working (`process-movie.sh`)
- Carnival of Souls ingested (288 scenes with embeddings)
- Pi client deployed on 192.168.1.109 with video playback working
- End-to-end tested: semantic search → video streaming → Pi playback
- Documentation updated with reinstall guide

⏳ **Possible future work:**
- Ingest more movies
- Test full voice conversation flow (phone → Whisper → GPT-4 → video)
- Add curator mode for manual clip selection
- Add more robust error recovery

---

**Last Updated:** 2026-02-25
