# TwistedTV Documentation

**Last Updated:** 2026-03-01

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture — What Runs Where](#architecture--what-runs-where)
3. [Server Reinstall Guide](#server-reinstall-guide)
4. [Cloud Ingestion (RunPod)](#cloud-ingestion-runpod)
5. [Directory Structure](#directory-structure)
6. [Component Details](#component-details)
7. [Operation & Usage](#operation--usage)
8. [Debugging & Troubleshooting](#debugging--troubleshooting)
9. [Known Gotchas](#known-gotchas)

---

## Project Overview

**TwistedTV** is an art installation where visitors speak into a vintage rotary phone and converse with an AI that responds exclusively through old movie clips displayed on a TV. There is no text-to-speech — the bot "speaks" only through video.

### Conversation Flow

1. User speaks into phone → Audio captured by Pi microphone
2. Pi Daily client → Sends audio to Daily.co WebRTC room
3. Server receives → Audio transcribed by Whisper STT
4. LLM processes → GPT-4 generates semantic description of desired response
5. LLM calls MCP tool → Queries GoodCLIPS API for matching scene
6. Server sends command → Via Daily.co to Pi client
7. Pi plays video → MPV displays clip on TV via HDMI
8. TV returns to static → Waiting for next input

---

## Architecture — What Runs Where

There are three locations. **Do not confuse them.**

### Server (192.168.1.106, Fedora Linux)

Runs permanently. Handles the AI conversation, video search, and video streaming.

| Service | Port | Manager |
|---------|------|---------|
| TwistedTV FastAPI (bot + Whisper + GPT-4 + WebRTC) | 8765 | systemd: `twistedtv-server.service` |
| Video Streaming Server (Flask) | 9000 | systemd: `twistedtv-video-server.service` |
| GoodCLIPS Go API (semantic search) | 8080 | Docker Compose |
| PostgreSQL + pgvector | 5432 | Docker Compose |
| Redis | 6379 | Docker Compose |

### Raspberry Pi (192.168.1.109)

Runs permanently at the installation site. Handles audio I/O and video display.

| Service | Port | Manager |
|---------|------|---------|
| Video Playback Service (MPV on HDMI) | 5000 | systemd user: `video-player.service` |
| Next.js Dashboard | 3000 | systemd user: `frontend.service` |
| Pi Daily Client (audio capture + WebRTC) | — | Spawned on demand by dashboard API |

### Cloud — RunPod (temporary, only during ingestion)

**Video ingestion does NOT run on the server.** It runs on temporary RunPod GPU pods.

A GPU pod spins up, downloads the movie, transcribes the audio to an SRT subtitle file (Whisper large-v3), detects scenes, generates embeddings + captions, then exports the movie's database records to the server and terminates. This is fully automated by `cloud-ingestion/process-movie.sh`. For manual export from a running pod, use `cloud-ingestion/pull-from-pod.sh`.

### Data Flow Diagram

```
┌──────────────────────────────────────────────────────┐
│         Raspberry Pi (192.168.1.109)                  │
│         Installation site — audio I/O + display       │
├──────────────────────────────────────────────────────┤
│  Phone (audio input)                                  │
│    → Pi Daily Client (captures audio, sends WebRTC)   │
│    → Video Playback Service :5000 (plays clips on TV) │
│    → Next.js Dashboard :3000 (monitoring UI)          │
└──────────────────────────────────────────────────────┘
                        ↕
               Daily.co WebRTC Cloud
            (audio up, commands down)
                        ↕
┌──────────────────────────────────────────────────────┐
│         Server (192.168.1.106)                        │
│         Always-on — AI processing + data              │
├──────────────────────────────────────────────────────┤
│  FastAPI Backend :8765                                │
│    → Whisper STT (transcribes audio)                  │
│    → GPT-4 (understands conversation)                 │
│    → MCP Server (queries GoodCLIPS for video clips)   │
│                                                       │
│  GoodCLIPS API :8080 (semantic video search)          │
│  PostgreSQL :5432 (scene embeddings + metadata)       │
│  Redis :6379 (job queue)                              │
│  Video Streaming :9000 (serves .mp4 files to Pi)      │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│         RunPod Cloud (temporary)                      │
│         GPU pods — only during movie ingestion        │
├──────────────────────────────────────────────────────┤
│  process-movie.sh creates pod → downloads movie →     │
│  transcribes audio (Whisper) → detects scenes →       │
│  generates embeddings → exports DB + SRT to server →  │
│  terminates pod                                       │
└──────────────────────────────────────────────────────┘
```

---

## Server Reinstall Guide

If the server (192.168.1.106) is wiped, follow these steps exactly. Total time: ~30 minutes (plus ~30 minutes for movie ingestion).

### Prerequisites

- Fedora Linux with `twistedtv` user
- Internet access
- The Pi (192.168.1.109) should already be set up

### Step 1: Install System Dependencies

```bash
# Python 3.12 (NOT 3.14 — too new for daily-python/ctranslate2)
sudo dnf install -y python3.12 python3.12-devel

# Docker
sudo dnf install -y docker docker-compose
sudo systemctl enable --now docker
sudo usermod -aG docker twistedtv
# Log out and back in for group to take effect

# PostgreSQL client (for pg_dump during ingestion)
sudo dnf install -y postgresql

# lsof (used by systemd services)
sudo dnf install -y lsof
```

### Step 2: Clone the Repository

```bash
cd /home/twistedtv
git clone https://github.com/byron-the-bulb/cinema-chat.git
cd cinema-chat
git checkout thomas-updates  # or whatever the current branch is
```

### Step 3: Create Python Virtual Environment

```bash
cd /home/twistedtv/cinema-chat/twistedtv-server
python3.12 -m venv venv
source venv/bin/activate

# Install CPU PyTorch first (no GPU on this server)
pip install torch==2.4.0 --index-url https://download.pytorch.org/whl/cpu

# Install all dependencies
pip install -r requirements.txt

# Also install Flask for the video streaming server
pip install flask
```

### Step 4: Create .env File

```bash
cat > /home/twistedtv/cinema-chat/twistedtv-server/cinema_bot/.env << 'EOF'
OPENAI_API_KEY=<your-openai-key>
DAILY_API_KEY=<your-daily-key>
DAILY_API_URL=https://api.daily.co/v1
WHISPER_DEVICE=cpu
REPO_ID=Systran/faster-distil-whisper-medium.en
HOST=0.0.0.0
FAST_API_PORT=8765
BACKEND_SERVER_URL=http://192.168.1.106:8765
GOODCLIPS_API_URL=http://localhost:8080
VIDEO_SERVER_URL=http://192.168.1.106:9000
PLAYBACK_SERVICE_URL=http://192.168.1.109:5000
DB_HOST=localhost
DB_PORT=5432
DB_USER=goodclips
DB_PASSWORD=goodclips_dev_password
DB_NAME=goodclips
RUNPOD_API_KEY=<your-runpod-key>
MY_AWS_ACCESS_KEY_ID=<your-aws-key>
MY_AWS_SECRET_ACCESS_KEY=<your-aws-secret>
MY_AWS_REGION=us-west-2
CLOUDWATCH_LOG_GROUP=/twistedtv
EOF
```

**Where to get API keys:** Copy from the Pi's `.env` at `/home/twistedtv/twistedtv-pi-client/frontend/.env` (SSH to Pi first).

### Step 5: Start Docker Compose (GoodCLIPS Stack)

```bash
cd /home/twistedtv/cinema-chat
docker compose up -d

# Wait for services to be healthy
docker compose ps  # Should show postgres, redis, goodclips-api as "Up"

# Fix the torch/timm version mismatch in the API container
docker exec goodclips-api pip uninstall -y timm torchvision
```

**Why the timm fix?** The container has torch 2.4.0 but pip pulls in torchvision 0.25 (needs torch 2.6). This breaks the `transformers` model loading. Removing timm/torchvision is safe because the text embedding model (e5-base-v2) doesn't need them.

### Step 6: Create Systemd Services

**IMPORTANT:** On Fedora with SELinux, systemd cannot execute binaries from home directories directly. All `ExecStart` must be wrapped in `/bin/bash -c '...'`.

Create `/tmp/twistedtv-server.service`:
```ini
[Unit]
Description=TwistedTV Server (Cinema Bot)
After=network.target

[Service]
Type=exec
User=twistedtv
WorkingDirectory=/home/twistedtv/cinema-chat/twistedtv-server/cinema_bot
ExecStartPre=/bin/bash -c 'lsof -ti:8765 | xargs -r kill -9 || true'
ExecStart=/bin/bash -c '/home/twistedtv/cinema-chat/twistedtv-server/venv/bin/python server.py'
Restart=on-failure
RestartSec=10
StandardOutput=append:/tmp/twistedtv-server.log
StandardError=append:/tmp/twistedtv-server.log

[Install]
WantedBy=multi-user.target
```

Create `/tmp/twistedtv-video-server.service`:
```ini
[Unit]
Description=TwistedTV Video Streaming Server
After=network.target

[Service]
Type=exec
User=twistedtv
WorkingDirectory=/home/twistedtv/cinema-chat/twistedtv-video-server
ExecStartPre=/bin/bash -c 'lsof -ti:9000 | xargs -r kill -9 || true'
ExecStart=/bin/bash -c '/home/twistedtv/cinema-chat/twistedtv-server/venv/bin/python streaming_server.py'
Restart=on-failure
RestartSec=10
StandardOutput=append:/tmp/twistedtv-video-server.log
StandardError=append:/tmp/twistedtv-video-server.log

[Install]
WantedBy=multi-user.target
```

Install and start:
```bash
# Copy (not symlink — SELinux blocks symlinks too)
sudo cp /tmp/twistedtv-server.service /etc/systemd/system/
sudo cp /tmp/twistedtv-video-server.service /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now twistedtv-server
sudo systemctl enable --now twistedtv-video-server

# Verify
systemctl is-active twistedtv-server twistedtv-video-server
# Should print: active / active
```

### Step 7: Ingest a Movie

The database is empty after a fresh install. You need to ingest at least one movie using the cloud ingestion pipeline (RunPod GPU pod).

```bash
RUNPOD_API_KEY="<your-runpod-key>" \
  bash /home/twistedtv/cinema-chat/cloud-ingestion/process-movie.sh \
  'https://archive.org/download/carnival_of_souls/carnival_of_souls.mp4' \
  'carnival_of_souls.mp4'
```

This takes ~60–90 minutes (Whisper transcription + scene detection + embeddings). The script will:
1. Create a RunPod GPU pod
2. Pod downloads the movie, transcribes the audio with Whisper large-v3 → `carnival_of_souls.srt`
3. Pod runs scene detection + visual embeddings + IV2 captioning
4. Export the movie's DB records via `\copy` TSV over direct TCP PostgreSQL
5. Import into local PostgreSQL with ID remapping
6. Download the Whisper SRT sidecar from the pod via HTTP
7. Download the video file from the original Archive.org URL to `data/videos/`
8. Terminate the pod

### Step 8: Verify Everything Works

```bash
# Test semantic search
curl -s http://localhost:8080/api/v1/search/semantic \
  -H 'Content-Type: application/json' \
  -d '{"query": "a woman looking scared", "limit": 3}' | python3 -m json.tool

# Test video streaming
curl -s -I http://localhost:9000/carnival_of_souls.mp4 | head -3

# Test from the Pi
ssh twistedtv@192.168.1.109 \
  "curl -s http://192.168.1.106:8080/health"

# Test video playback on Pi
ssh twistedtv@192.168.1.109 \
  "curl -s -X POST http://localhost:5000/play \
    -H 'Content-Type: application/json' \
    -d '{\"video_path\": \"http://192.168.1.106:9000/carnival_of_souls.mp4\", \"start\": 100, \"end\": 105}'"
```

### Step 9: Update Pi Configuration (if server IP changed)

On the Pi, update the server URL in `/home/twistedtv/twistedtv-pi-client/frontend/.env`:
```
NEXT_PUBLIC_API_URL=http://<new-server-ip>:8765
```

Then rebuild and restart the frontend:
```bash
ssh twistedtv@192.168.1.109
cd ~/twistedtv-pi-client/frontend
npm run build
systemctl --user restart frontend
```

---

## Cloud Ingestion (RunPod)

### Overview

Movie ingestion requires a GPU for scene detection, embedding generation (SigLIP), and captioning. Since the server has no GPU, this runs on temporary RunPod pods.

### Automated Pipeline

The script `cloud-ingestion/process-movie.sh` handles everything:

```bash
RUNPOD_API_KEY="<key>" bash cloud-ingestion/process-movie.sh '<movie_url>' '<filename>'
```

**What it does:**
1. Creates a RunPod GPU pod (NVIDIA RTX A4000) with the `va55/goodclips-runpod:latest` Docker image
2. Exposes ports: `8080/http` (GoodCLIPS API) and `5432/tcp` (PostgreSQL)
3. Waits for the pod to be ready and the API to be healthy
4. Pod downloads the movie, then **transcribes the audio with Whisper large-v3** → writes `film.srt` alongside the video
5. Pod submits the video to GoodCLIPS for scene detection + embedding generation + IV2 captioning
6. `process-movie.sh` monitors progress (polls embedding job status); timeout: **150 minutes**
7. Calls `pull-from-pod.sh` to export the movie's data:
   - Exports `scenes`, `captions`, and `videos` rows via `\copy` TSV over **direct TCP** to the pod's PostgreSQL (not the HTTP proxy — see gotcha #4)
   - Imports into local PostgreSQL with ID remapping (so local IDs don't conflict with other movies)
   - Downloads the Whisper SRT sidecar via `GET /api/v1/files/film.srt` over HTTP
8. Downloads the video file to `data/videos/` from the original source URL
9. Terminates the pod

**Environment variables:**
- `RUNPOD_API_KEY` (required) — Your RunPod API key
- `GPU_TYPE` (optional) — Default: `NVIDIA RTX A4000`
- `KEEP_POD` (optional) — Set to `true` to keep pod running after completion
- `WHISPER_MODEL` (optional) — Whisper model size on the pod. Default: `large-v3`. Use `medium` to trade accuracy for ~3× speed.

### Manual Export from a Running Pod

If you've been working on a pod manually and want to pull the data without running the full pipeline:

```bash
# DB + SRT only (video already local or will be fetched separately)
RUNPOD_API_KEY=rpa_... ./cloud-ingestion/pull-from-pod.sh \
    <pod-id> carnival_of_souls.mp4

# DB + SRT + video fetched from Archive.org
RUNPOD_API_KEY=rpa_... ./cloud-ingestion/pull-from-pod.sh \
    <pod-id> carnival_of_souls.mp4 \
    'https://archive.org/download/carnival_of_souls/carnival_of_souls.mp4'
```

Find the pod ID in the RunPod dashboard. The script resolves the PostgreSQL direct IP and HTTP API URL automatically from the RunPod API.

### Important: RunPod TCP Proxy Limitation

RunPod's `*.proxy.runpod.net` URLs are **HTTP-only proxies**. They do NOT pass through raw TCP connections. This means you **cannot** use them for `pg_dump` or direct PostgreSQL connections.

The `process-movie.sh` script works around this by extracting the pod's direct public IP and mapped port from the RunPod API, instead of using the proxy URL.

### Adding More Movies

Good sources for public domain movies:
- [Internet Archive](https://archive.org/details/feature_films) — Public domain films
- Look for direct `.mp4` download links

Example movies that work well:
```bash
# Carnival of Souls (1962, horror)
'https://archive.org/download/carnival_of_souls/carnival_of_souls.mp4'

# Night of the Living Dead (1968, horror)
'https://archive.org/download/night_of_the_living_dead_dvd/Night.mp4'
```

---

## Directory Structure

```
cinema-chat/
├── CLAUDE.md                         # AI context (read this first)
├── TWISTEDTV.md                      # This file
├── HANDOFF.md                        # Project handoff docs
├── docker-compose.yml                # GoodCLIPS Docker stack
├── Dockerfile                        # GoodCLIPS API image
│
├── cmd/                              # GoodCLIPS Go API (Massimo's)
├── internal/                         # GoodCLIPS Go internals (Massimo's)
├── migrations/                       # DB migrations (Massimo's)
│
├── cloud-ingestion/                  # CLOUD: Movie ingestion pipeline
│   ├── process-movie.sh             # Main script — creates pod, processes, imports, terminates
│   ├── pull-from-pod.sh             # Standalone export: DB + SRT from any running pod
│   ├── transcribe.py                # Whisper audio transcription → SRT (runs on pod GPU)
│   ├── Dockerfile                   # All-in-one RunPod image
│   ├── entrypoint.sh               # Pod startup (starts DB, Redis, API, auto-download + transcribe)
│   ├── download-and-process.sh     # On-pod video processing
│   └── export-db.sh                # On-pod database export (manual use)
│
├── twistedtv-server/                 # SERVER: Bot + MCP
│   ├── cinema_bot/                  # FastAPI server, bot logic, Whisper, GPT-4
│   │   ├── server.py               # Entry point (port 8765)
│   │   ├── cinema_bot.py           # Main bot logic
│   │   ├── mcp_client.py           # MCP client integration
│   │   └── .env                    # API keys (not in git)
│   ├── mcp_server/                  # MCP server for video search
│   │   ├── server.py               # Real MCP server (GoodCLIPS)
│   │   └── mock_server.py          # Mock server (keyword search)
│   ├── venv/                        # Python 3.12 virtual environment
│   └── requirements.txt
│
├── twistedtv-video-server/           # SERVER: Video streaming
│   └── streaming_server.py          # Flask server (port 9000)
│
├── twistedtv-pi-client/              # PI: Audio + video + dashboard
│   ├── pi_daily_client/             # Daily.co WebRTC client
│   ├── video_playback/              # MPV playback service (port 5000)
│   └── frontend/                    # Next.js dashboard (port 3000)
│
└── data/
    └── videos/                      # Video files served by streaming server
```

### What Runs Where

| Component | Location | Entry Point |
|-----------|----------|-------------|
| FastAPI Backend | Server | `twistedtv-server/cinema_bot/server.py` |
| MCP Server | Server | `twistedtv-server/mcp_server/server.py` (spawned by bot) |
| Video Streaming | Server | `twistedtv-video-server/streaming_server.py` |
| GoodCLIPS API | Server | `docker-compose.yml` → `goodclips-api` container |
| PostgreSQL | Server | `docker-compose.yml` → `goodclips-postgres` container |
| Redis | Server | `docker-compose.yml` → `goodclips-redis` container |
| Daily Client | Pi | `twistedtv-pi-client/pi_daily_client/pi_daily_client.py` |
| Video Playback | Pi | `twistedtv-pi-client/video_playback/video_playback_service_mpv.py` |
| Dashboard | Pi | `twistedtv-pi-client/frontend/` |
| Movie Ingestion | Cloud (RunPod) | `cloud-ingestion/process-movie.sh` |

---

## Component Details

### 1. Cinema Bot Backend (Server, port 8765)

**Location:** `twistedtv-server/cinema_bot/`

FastAPI server that orchestrates the conversation:
- Receives audio via Daily.co WebRTC (Pipecat SDK)
- Transcribes with Whisper STT (CPU mode on this server)
- GPT-4 understands conversation intent
- MCP client calls `search_video_clips` tool
- MCP server queries GoodCLIPS API at `localhost:8080`
- Sends video playback command back to Pi via Daily.co

### 2. MCP Server (Server, spawned by bot)

**Location:** `twistedtv-server/mcp_server/`

Runs as a subprocess (stdio) of the cinema bot. Two modes:
- **`server.py`** (production): Queries GoodCLIPS API for semantic search, fetches captions from Postgres
- **`mock_server.py`** (development): Keyword-based search with hardcoded scenes

MCP tools exposed:
- `search_video_clips(query, top_k)` — Find matching video clips
- `play_video_by_params(video_id, start, end)` — Select a specific clip

### 3. GoodCLIPS API (Server, port 8080)

**Location:** Root `docker-compose.yml`

Go API for multi-modal semantic video search, backed by PostgreSQL + pgvector.

**Search endpoints:**
- `POST /api/v1/search/semantic` — Text query → scenes ranked by visual/scene description similarity (e5-base-v2 on IV2 captions + dialog mixed)
- `POST /api/v1/search/text` — Text query → scenes ranked by **dialog similarity only** (non-iv2 captions, i.e. Whisper transcriptions). Returns `clip_start`/`clip_end` tight around the matched dialog (caption boundaries ± 0.5s), ready to pass directly to the video player.
- `POST /api/v1/search/scenes` — Find visually similar scenes to an anchor scene (visual embeddings)

**Other endpoints:**
- `GET /api/v1/files/:filename` — Serve a file from the videos directory by name. Used by `pull-from-pod.sh` to download the Whisper SRT over HTTP.
- `GET /api/v1/stats` — Database statistics
- `GET /api/v1/jobs` — Job queue status
- `GET /health` — Health check

**Search response shape for `/search/text`:**
```json
{
  "results": [{
    "scene":       { "video_id": 3, "scene_index": 42, "start_time": 340.1, "end_time": 351.8, ... },
    "clip_start":  342.6,
    "clip_end":    349.1,
    "dialog_text": "Please, not me. I'm begging you, let me go.",
    "distance":    0.12
  }]
}
```
Use `clip_start`/`clip_end` (not `scene.start_time`/`scene.end_time`) when playing dialog clips.

### 4. Video Playback Service (Pi, port 5000)

**Location:** `twistedtv-pi-client/video_playback/video_playback_service_mpv.py`

Flask HTTP API that controls MPV on the Pi's HDMI output:
- `POST /play` — Play a clip: `{"video_path": "http://server:9000/movie.mp4", "start": 100, "end": 105}`
- `POST /stop` — Stop playback
- `GET /status` — Current playback state
- `GET /health` — Health check

Shows `static.mp4` (TV static) when idle. Uses DRM/KMS rendering for Raspberry Pi.

### 5. Video Streaming Server (Server, port 9000)

**Location:** `twistedtv-video-server/streaming_server.py`

Simple Flask server that serves video files from `data/videos/` over HTTP. The Pi's MPV player fetches clips from here via HTTP range requests.

### 6. Next.js Dashboard (Pi, port 3000)

**Location:** `twistedtv-pi-client/frontend/`

Web UI accessible at `http://192.168.1.109:3000`:
- Start/stop conversation sessions
- View real-time transcription
- Monitor bot status
- API routes spawn the Pi Daily Client on demand

---

## Operation & Usage

### Starting a Session

1. **Verify server services are running:**
   ```bash
   systemctl is-active twistedtv-server twistedtv-video-server
   curl -s http://localhost:8080/health | python3 -m json.tool
   ```

2. **Open Pi dashboard:** `http://192.168.1.109:3000`

3. **Click "Connect to Local Backend"** — This creates a Daily.co room, spawns the Pi Daily Client, and connects everything.

4. **Speak into the phone** — Video clips play on the TV.

### Monitoring

```bash
# Server logs
tail -f /tmp/twistedtv-server.log

# Video server logs
tail -f /tmp/twistedtv-video-server.log

# Docker logs (GoodCLIPS API)
docker compose logs -f goodclips-api

# Pi video playback status
curl -s http://192.168.1.109:5000/status

# Database stats
curl -s http://localhost:8080/api/v1/stats | python3 -m json.tool
```

### Stopping

- Click "Stop" on the Pi dashboard, or:
  ```bash
  ssh twistedtv@192.168.1.109 "pkill -f pi_daily_client"
  ```

---

## Debugging & Troubleshooting

### Semantic Search Returns Error

**Symptom:** `{"error": "Failed to embed query", "details": "...TimmWrapperConfig..."}`

**Cause:** Docker image has incompatible timm/torchvision versions.

**Fix:**
```bash
docker exec goodclips-api pip uninstall -y timm torchvision
```

### No Scenes in Database

**Symptom:** Search returns empty results, `GET /api/v1/stats` shows 0 scenes.

**Fix:** Run the ingestion pipeline (see [Cloud Ingestion](#cloud-ingestion-runpod)).

### Video Won't Play on Pi

**Debug:**
```bash
# Check video server is reachable from Pi
ssh twistedtv@192.168.1.109 "curl -s -I http://192.168.1.106:9000/carnival_of_souls.mp4 | head -3"

# Check video playback service on Pi
ssh twistedtv@192.168.1.109 "curl -s http://localhost:5000/health"

# Test playback directly
ssh twistedtv@192.168.1.109 "curl -X POST http://localhost:5000/play \
  -H 'Content-Type: application/json' \
  -d '{\"video_path\": \"http://192.168.1.106:9000/carnival_of_souls.mp4\", \"start\": 100, \"end\": 105}'"
```

### Systemd Service Won't Start (Exit Code 203)

**Cause:** SELinux blocking execution from home directory.

**Fix:** Ensure `ExecStart` is wrapped in `/bin/bash -c '...'` and that the service file is **copied** (not symlinked) to `/etc/systemd/system/`.

### pg_dump Times Out During Ingestion

**Cause:** Using `proxy.runpod.net` URL instead of direct IP.

**Fix:** The `process-movie.sh` script handles this automatically. If doing it manually, get the pod's direct IP from the RunPod API:
```bash
curl -s --request POST \
  --url "https://api.runpod.io/graphql?api_key=$RUNPOD_API_KEY" \
  --header 'content-type: application/json' \
  --data '{"query": "query { pod(input: {podId: \"<pod-id>\"}) { runtime { ports { ip isIpPublic privatePort publicPort } } } }"}' \
  | python3 -m json.tool
```
Use the `ip` and `publicPort` for the port with `privatePort: 5432`.

### No Audio from Phone

```bash
# On Pi — test microphone
ssh twistedtv@192.168.1.109
arecord -l                           # List devices
arecord -D plughw:1,0 -d 5 test.wav # Record 5 seconds
aplay test.wav                       # Play back
```

---

## Known Gotchas

1. **SELinux on Fedora** — Systemd cannot execute binaries from `/home`. Wrap `ExecStart` in `/bin/bash -c '...'`. Copy (not symlink) service files to `/etc/systemd/system/`.

2. **Python 3.12 required** — Python 3.14 is too new (missing wheels for daily-python, ctranslate2). Python 3.11 not available on Fedora 43. Install: `sudo dnf install -y python3.12 python3.12-devel`

3. **Docker timm/torchvision mismatch** — The GoodCLIPS API container's CPU runtime has `torch==2.4.0` but pip pulls in `torchvision==0.25.0` (needs torch 2.6). Fix: `docker exec goodclips-api pip uninstall -y timm torchvision`

4. **RunPod TCP proxy is HTTP-only** — `*.proxy.runpod.net` URLs only handle HTTP, not raw TCP. For `pg_dump`, use the pod's direct public IP. `process-movie.sh` handles this automatically.

5. **SSH to Pi requires agent forwarding** — The SSH key is on the local machine, not the server. SSH to the server with `ssh -A`, then SSH to the Pi.

6. **`data/videos/` may be root-owned** — Docker creates it as root. Fix: `sudo chown -R twistedtv:twistedtv /home/twistedtv/cinema-chat/data`

7. **Docker group needs re-login** — After `sudo usermod -aG docker twistedtv`, you must log out and back in. Until then, use `sg docker -c "docker compose up -d"`.

---

## Port Reference

| Service | Port | Location | Protocol |
|---------|------|----------|----------|
| TwistedTV FastAPI | 8765 | Server | HTTP |
| Video Streaming | 9000 | Server | HTTP |
| GoodCLIPS API | 8080 | Server | HTTP |
| PostgreSQL | 5432 | Server | TCP |
| Redis | 6379 | Server | TCP |
| Video Playback (MPV) | 5000 | Pi | HTTP |
| Next.js Dashboard | 3000 | Pi | HTTP |

## Environment Variables

**Server `.env`** (at `twistedtv-server/cinema_bot/.env`):

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI API key for GPT-4 and Whisper |
| `DAILY_API_KEY` | Yes | Daily.co API key for WebRTC rooms |
| `DAILY_API_URL` | Yes | `https://api.daily.co/v1` |
| `WHISPER_DEVICE` | Yes | `cpu` (this server has no GPU) |
| `BACKEND_SERVER_URL` | Yes | `http://192.168.1.106:8765` |
| `GOODCLIPS_API_URL` | Yes | `http://localhost:8080` |
| `VIDEO_SERVER_URL` | Yes | `http://192.168.1.106:9000` |
| `PLAYBACK_SERVICE_URL` | Yes | `http://192.168.1.109:5000` |
| `RUNPOD_API_KEY` | For ingestion | RunPod API key |

**Pi `.env`** (at `twistedtv-pi-client/frontend/.env`):

| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://192.168.1.106:8765` |
| `NEXT_PUBLIC_API_ENDPOINT` | `/connect_local` |
| `RUNPOD_API_KEY` | RunPod API key (for cloud connect mode) |

---

*Last updated: 2026-02-25*
