# Cinema Chat - Startup Guide

This document explains how to start and stop Cinema Chat services in different environments.

## Quick Start

### Local Development

Start all services locally (recommended for development):

```bash
./start-local.sh
```

This will start:
- MCP Mock Server (keyword-based video search)
- Video Playback Service (HTTP server for ffmpeg)
- Cinema Bot Backend (FastAPI + Whisper + OpenAI)
- Next.js Frontend (monitoring interface)

All services run in the background with logs in `logs/` directory.

**Stop services:**

```bash
./stop-local.sh
```

Or press `Ctrl+C` if you're watching the startup script output.

### Cloud Deployment

Deploy all services using Docker containers:

```bash
# First time or after code changes - rebuild images
./start-cloud.sh --build

# Subsequent starts (use cached images)
./start-cloud.sh

# Development mode (uses mock MCP server)
./start-cloud.sh --dev
```

This will start:
- GoodCLIPS API stack (Postgres, Redis, Go API)
- MCP Server (real or mock, depending on mode)
- Cinema Bot Backend (in Docker container)
- Next.js Frontend (in Docker container or npm dev mode)

**Stop services:**

```bash
# Stop all Docker containers
docker stop cinema-bot cinema-mcp cinema-frontend

# Stop GoodCLIPS stack
docker-compose down

# Or stop everything at once
docker stop cinema-bot cinema-mcp cinema-frontend && docker-compose down
```

## Prerequisites

### Local Development

1. **Python 3.11+** with pip and venv
2. **Node.js 20+** with npm
3. **ffmpeg** (for video playback)
4. **API Keys** (see Environment Configuration below)

### Cloud Deployment

1. **Docker** and **docker-compose**
2. **NVIDIA GPU** (optional, for faster Whisper STT)
3. **API Keys** (see Environment Configuration below)

## Environment Configuration

### Required Environment Files

1. **Cinema Bot Backend**: `cinema-bot-app/backend/src/cinema-bot/.env`

```bash
# Copy from example
cp cinema-bot-app/backend/src/cinema-bot/.env.example cinema-bot-app/backend/src/cinema-bot/.env

# Edit and add your API keys
nano cinema-bot-app/backend/src/cinema-bot/.env
```

Required variables:
- `OPENAI_API_KEY` - For GPT-4.1 LLM
- `DAILY_API_KEY` - For WebRTC audio transport
- `WHISPER_DEVICE` - `cuda` or `cpu` (default: `cuda`)

2. **MCP Server** (optional for mock mode): `mcp/.env`

```bash
cp mcp/.env.example mcp/.env
```

Only needed for real GoodCLIPS integration:
- `GOODCLIPS_API_URL` - GoodCLIPS API endpoint (default: `http://localhost:8080`)

3. **Root Directory** (for cloud deployment): `.env`

```bash
cp .env.example .env
```

For GoodCLIPS API configuration (Postgres, Redis, etc.)

## Service Details

### MCP Mock Server

**Port**: stdio (communicates via stdin/stdout)
**Location**: `mcp/mock_server.py`
**Purpose**: Keyword-based video search without GoodCLIPS API

Uses hardcoded scene mappings for testing. Has 5 test videos from educational films.

### Video Playback Service

**Port**: 5000
**Location**: `mcp/video_playback_service.py`
**Purpose**: HTTP API for playing video clips via ffmpeg

Endpoints:
- `POST /play` - Play a video clip
- `POST /stop` - Stop current playback
- `GET /status` - Get playback status

### Cinema Bot Backend

**Port**: 7860
**Location**: `cinema-bot-app/backend/src/cinema-bot/server.py`
**Purpose**: FastAPI server orchestrating the conversation

Features:
- Whisper STT for speech-to-text
- OpenAI GPT-4.1 for conversation
- MCP client for video selection
- Daily.co WebRTC for audio transport
- Two-conversation architecture

### Next.js Frontend

**Port**: 3000
**Location**: `cinema-bot-app/frontend-next/`
**Purpose**: Web interface for monitoring conversation state

Shows:
- Conversation history
- Selected video clips
- Bot status and debugging info

## Logs

### Local Development

Logs are written to `logs/` directory:
- `logs/mcp-server.log` - MCP Server
- `logs/video-playback.log` - Video Playback Service
- `logs/cinema-bot.log` - Cinema Bot Backend
- `logs/frontend.log` - Next.js Frontend

### Cloud Deployment

View Docker container logs:

```bash
# Follow logs
docker logs -f cinema-bot
docker logs -f cinema-mcp
docker logs -f cinema-frontend

# View last 100 lines
docker logs --tail 100 cinema-bot
```

## Troubleshooting

### Services won't start

1. **Check environment files** - Ensure `.env` files exist with valid API keys
2. **Check ports** - Make sure ports 3000, 5000, 7860, 8080 are not in use
3. **Check logs** - Look in `logs/` directory or use `docker logs`

### MCP Server issues

- **"Connection refused"** - MCP server may not be running, check logs
- **"No videos found"** - Check that test videos exist in `data/videos/`
- **Infinite loop** - Fixed in latest version, update to latest code

### Video playback not working

- **Check ffmpeg** - Ensure `ffmpeg` and `ffplay` are installed
- **Check video files** - Ensure videos exist in `data/videos/`
- **Check video service** - Ensure it's running on port 5000

### Cinema Bot not responding

- **Check API keys** - Ensure `OPENAI_API_KEY` and `DAILY_API_KEY` are set
- **Check GPU** - If using GPU, ensure CUDA is installed and `WHISPER_DEVICE=cuda`
- **Check MCP connection** - Bot needs MCP server running via stdio

### Frontend not loading

- **Check port 3000** - Make sure nothing else is using it
- **Check npm dependencies** - Run `npm install` in `frontend-next/`
- **Check backend** - Frontend needs bot backend running on port 7860

## Development Tips

### Running individual services

You can start services manually for debugging:

```bash
# MCP Server
cd mcp
source venv/bin/activate
python3 mock_server.py

# Video Playback
cd mcp
source venv/bin/activate
python3 video_playback_service.py

# Cinema Bot
cd cinema-bot-app/backend/src/cinema-bot
source ../../venv/bin/activate
python3 server.py

# Frontend
cd cinema-bot-app/frontend-next
npm run dev
```

### Testing video playback

```bash
# Play a test clip
curl -X POST http://localhost:5000/play \
  -H 'Content-Type: application/json' \
  -d '{
    "video_path": "/home/va55/code/cinema-chat/data/videos/test_clip.mp4",
    "start": 0,
    "end": 5
  }'
```

### Checking service health

```bash
# Check if services are listening
nc -zv localhost 3000   # Frontend
nc -zv localhost 5000   # Video Playback
nc -zv localhost 7860   # Cinema Bot
nc -zv localhost 8080   # GoodCLIPS API

# Check processes
ps aux | grep -E "(mock_server|video_playback|server\.py|next)"
```

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│              Installation Computer               │
│                                                   │
│  ┌─────────────────────────────────────────┐    │
│  │  Phone Input → Browser (Daily.co)       │    │
│  └──────────────┬──────────────────────────┘    │
│                 │                                 │
│                 ▼                                 │
│  ┌─────────────────────────────────────────┐    │
│  │  Cinema Bot Backend (FastAPI)           │    │
│  │  - Whisper STT                           │    │
│  │  - OpenAI GPT-4.1                        │    │
│  │  - MCP Client                            │    │
│  └──────────────┬──────────────────────────┘    │
│                 │                                 │
│                 ▼                                 │
│  ┌─────────────────────────────────────────┐    │
│  │  MCP Server (stdio)                      │    │
│  │  - Video search (mock or GoodCLIPS)      │    │
│  └──────────────┬──────────────────────────┘    │
│                 │                                 │
│                 ▼                                 │
│  ┌─────────────────────────────────────────┐    │
│  │  Video Playback Service (HTTP:5000)      │    │
│  │  - ffmpeg/ffplay control                 │    │
│  └──────────────┬──────────────────────────┘    │
│                 │                                 │
│                 ▼                                 │
│            TV Output (HDMI)                       │
│                                                   │
│  ┌─────────────────────────────────────────┐    │
│  │  Frontend (Next.js:3000)                 │    │
│  │  - Monitoring & Debugging                │    │
│  └─────────────────────────────────────────┘    │
└───────────────────────────────────────────────────┘
```

## Next Steps

1. **Test locally** - Start with `./start-local.sh` to verify everything works
2. **Configure hardware** - Connect phone input and TV output
3. **Test end-to-end** - Make a test call and verify video playback
4. **Deploy to cloud** - Use `./start-cloud.sh --build` when ready
5. **Integrate GoodCLIPS** - Switch from mock server to real API

## Support

For issues or questions:
- Check [CLAUDE.md](CLAUDE.md) for detailed architecture docs
- Review logs in `logs/` directory
- Check Docker logs with `docker logs <container>`
- Verify all environment variables are set correctly
