# Cloud Ingestion Pipeline

RunPod-based video ingestion pipeline for processing movies with GPU acceleration.

## Overview

This creates temporary GPU pods on RunPod that:
1. Download a movie from a URL
2. Detect scenes with PySceneDetect
3. Generate visual embeddings (SigLIP) and text embeddings (e5-base-v2)
4. Generate captions for each scene
5. Export the database to the local server via `pg_dump`
6. Terminate the pod

The Docker image is all-in-one: PostgreSQL 14 + pgvector, Redis, GoodCLIPS worker, CUDA 12.1 runtime.

## Quick Start

### Process a Movie (fully automated)

```bash
export RUNPOD_API_KEY=your_key
./cloud-ingestion/process-movie.sh \
  'https://archive.org/download/carnival_of_souls/carnival_of_souls.mp4' \
  'carnival_of_souls.mp4'
```

This handles everything: pod creation, processing, database export, local import, video download, pod termination.

**Prerequisites:**
- `RUNPOD_API_KEY` environment variable set
- Local PostgreSQL running (`docker compose up -d` from project root)
- `psql` client installed (`sudo dnf install -y postgresql`)

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RUNPOD_API_KEY` | (required) | Your RunPod API key |
| `GPU_TYPE` | `NVIDIA RTX A4000` | GPU type for the pod |
| `KEEP_POD` | `false` | Set to `true` to keep pod running after completion |

## Files

- `process-movie.sh` — End-to-end automated pipeline (main script)
- `Dockerfile` — All-in-one RunPod image
- `entrypoint.sh` — Pod startup: starts PostgreSQL, Redis, GoodCLIPS worker
- `build.sh` — Build and push Docker image to Docker Hub
- `download-and-process.sh` — Download video and trigger processing (runs on pod)
- `export-db.sh` — Export database for syncing to local server (runs on pod)

## Build and Push Image

```bash
DOCKER_USERNAME=yourusername ./cloud-ingestion/build.sh
```

## Important: RunPod TCP Proxy Limitation

RunPod's `*.proxy.runpod.net` URLs are **HTTP-only proxies**. They do NOT pass through raw TCP connections like PostgreSQL.

**DO NOT use proxy URLs for `pg_dump`:**
```bash
# WRONG — will time out:
pg_dump -h <pod-id>-5432.proxy.runpod.net ...

# CORRECT — use direct IP from RunPod API:
pg_dump -h <direct-ip> -p <mapped-port> ...
```

The `process-movie.sh` script handles this automatically by extracting the pod's direct public IP and mapped port from the RunPod GraphQL API.

## Manual RunPod Setup (if not using process-movie.sh)

1. Create GPU pod with image `va55/goodclips-runpod:latest`
2. **Expose ports: `8080/http` AND `5432/tcp`** (both are required)
3. Set environment variables:
   - `AUTO_DOWNLOAD_URL` — Video URL to download on startup
   - `AUTO_DOWNLOAD_FILENAME` — Filename to save as
4. Wait for processing to complete (monitor via `GET <pod-api>/api/v1/jobs`)
5. Get the pod's direct IP from RunPod API (NOT the proxy URL)
6. Run `pg_dump` using the direct IP and mapped port
7. Import into local PostgreSQL
8. Terminate the pod
