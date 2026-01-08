# Cloud Ingestion Pipeline

RunPod-based video ingestion pipeline for processing movies with GPU acceleration.

## Overview

This creates an all-in-one Docker image with:
- PostgreSQL 14 + pgvector
- Redis
- GoodCLIPS worker (Go binary + Python ML scripts)
- CUDA 12.1 runtime

## Files

- `Dockerfile` - All-in-one RunPod image
- `entrypoint.sh` - Starts PostgreSQL, Redis, and GoodCLIPS worker
- `build.sh` - Build and push Docker image to Docker Hub
- `process-movie.sh` - End-to-end: create pod, process movie, sync DB locally
- `download-and-process.sh` - Download video and trigger processing (runs on pod)
- `export-db.sh` - Export database for syncing to local server

## Quick Start

### Build and Push Image

```bash
DOCKER_USERNAME=yourusername ./cloud-ingestion/build.sh
```

### Process a Movie

```bash
export RUNPOD_API_KEY=your_key
./cloud-ingestion/process-movie.sh \
  'https://archive.org/download/night_of_the_living_dead_dvd/Night.mp4' \
  'notld.mp4'
```

### Manual RunPod Setup

1. Create GPU pod with image `yourusername/goodclips-runpod:latest`
2. Expose ports: `8080/http`, `5432/tcp`
3. Set environment variables:
   - `AUTO_DOWNLOAD_URL` - Video URL to download on startup
   - `AUTO_DOWNLOAD_FILENAME` - Filename to save as
   - `HUGGINGFACE_HUB_TOKEN` - For model downloads

### Sync Database After Processing

```bash
PGPASSWORD=goodclips_dev_password pg_dump \
  -h <pod-id>-5432.proxy.runpod.net \
  -U goodclips -d goodclips --no-owner --no-acl | \
  psql -h localhost -U goodclips -d goodclips
```
