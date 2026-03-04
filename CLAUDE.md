# TwistedTV — AI Context

This is **TwistedTV**, an art installation where visitors speak into a vintage rotary phone and an AI responds exclusively through old movie clips displayed on a TV. There is no text-to-speech — the bot "speaks" only through video.

## Architecture — What Runs Where

**IMPORTANT:** Video ingestion runs in the CLOUD (temporary RunPod GPU pods), NOT on the server. The server only runs the bot, search API, and video streaming.

### Server (192.168.1.106, Fedora Linux)
Runs permanently. All services managed by systemd or Docker.

| Service | Port | How |
|---------|------|-----|
| TwistedTV FastAPI (bot + WebRTC) | 8765 | systemd: `twistedtv-server.service` |
| Video Streaming (Flask) | 9000 | systemd: `twistedtv-video-server.service` |
| GoodCLIPS Go API (semantic search) | 8080 | Docker Compose |
| PostgreSQL + pgvector | 5432 | Docker Compose |
| Redis | 6379 | Docker Compose |

### Raspberry Pi (192.168.1.109)
Runs permanently at the installation site. User-level systemd services.

| Service | Port | How |
|---------|------|-----|
| Video Playback (MPV on HDMI) | 5000 | systemd user: `video-player.service` |
| Next.js Dashboard | 3000 | systemd user: `frontend.service` |
| Pi Daily Client (audio/WebRTC) | — | Spawned on demand by dashboard |

### Cloud — RunPod (temporary)
Only used during movie ingestion. Spins up a GPU pod, processes a movie into scene embeddings, exports the database to the server, then terminates.

Script: `cloud-ingestion/process-movie.sh`

## Key Paths

- Project root: `/home/twistedtv/cinema-chat`
- Python venv: `twistedtv-server/venv/` (Python 3.12)
- Server .env: `twistedtv-server/cinema_bot/.env`
- Videos: `data/videos/`
- Docker Compose: `docker-compose.yml` (GoodCLIPS stack)
- Ingestion script: `cloud-ingestion/process-movie.sh`
- Systemd services: `/etc/systemd/system/twistedtv-*.service`

## Known Gotchas

1. **SELinux on Fedora**: Systemd cannot execute binaries from home directories. All `ExecStart` lines must be wrapped: `ExecStart=/bin/bash -c '/path/to/venv/bin/python script.py'`

2. **Python version**: Use Python 3.12, not 3.14 (too new for daily-python, ctranslate2) and not 3.11 (not available on Fedora 43).

3. **Docker image timm/torchvision mismatch**: The GoodCLIPS API container (CPU runtime) has torch 2.4.0 but pip pulls in incompatible timm/torchvision. After `docker compose up`, run: `docker exec goodclips-api pip uninstall -y timm torchvision`

4. **RunPod TCP proxy doesn't work for PostgreSQL**: The `*.proxy.runpod.net` URLs are HTTP-only proxies. For `pg_dump`, you MUST use the pod's direct public IP and mapped port. The `process-movie.sh` script handles this automatically.

5. **SSH to Pi**: The SSH key lives on the local machine (not the server). Use agent forwarding: `ssh -A twistedtv@192.168.1.106` then `ssh twistedtv@192.168.1.109`.

## Reinstall Guide

If the server is wiped, follow the "Server Reinstall Guide" section in `TWISTEDTV.md`. It has exact commands for every step.
