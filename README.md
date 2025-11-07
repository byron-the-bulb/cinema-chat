# GoodCLIPS: Multi‑Modal Video Scene Search

GoodCLIPS is a Dockerized Go + Python system for per‑scene, multi‑modal semantic search over videos. It computes and stores scene embeddings for:

- Visual (InternVL3.5/InternVideo2)
- Visual (text‑aligned CLIP ViT‑B/32)
- Audio (LAION‑CLAP HTSAT)
- Text (captions via e5‑base‑v2)

Embeddings are stored in Postgres using pgvector and searched via cosine distance. Long‑running work (scene detection, caption extraction, embeddings) runs asynchronously on a worker backed by Redis.


## High‑Level Architecture

```mermaid
flowchart LR
  subgraph Client
    UI[Frontend / CLI]
  end

  UI -->|HTTP| API

  subgraph Server
    API[goodclips-api (Go/Gin)]
    Worker[goodclips-worker (Go)]
    RQ[(Redis)]
    DB[(Postgres + pgvector)]
  end

  API --> DB
  API --> RQ
  Worker --> RQ
  Worker --> DB

  subgraph PyRunners[Python Runners]
    IV2[iv2_runner.py \n InternVL/IV2 per-scene visual]
    CLIP[clip_runner.py \n CLIP ViT-B/32 per-scene image]
    CLAP[audio_embed_runner.py \n LAION-CLAP HTSAT]
  end

  Worker -. invokes .-> IV2
  Worker -. invokes .-> CLIP
  Worker -. invokes .-> CLAP

  subgraph Storage
    VFS[/./data/videos -> /data/videos/]
  end

  Worker --- VFS
  API --- VFS
```


## Data Model (pgvector)

Tables (see `migrations/init.sql`):

- `videos`: basic video metadata, file path, status.
- `scenes`: one row per detected scene.
  - `visual_embedding vector(1024)` – InternVL3.5 scene embedding.
  - `text_embedding vector(768)` – aggregated scene caption embedding (e5‑base‑v2).
  - `audio_embedding vector(512)` – scene audio embedding (CLAP).
  - `visual_clip_embedding vector(512)` – scene image embedding (CLIP ViT‑B/32).
  - `combined_embedding vector(768)` – reserved for future fusion.
  - Unique `(video_id, scene_index)`.
- `captions`: subtitle text segments with timestamps.
- `processing_jobs`: background job bookkeeping.

GORM models live in `internal/models/models.go`. DAO helpers in `internal/database/database.go` provide setters and search utilities.


## Processing Pipeline

- **Video ingestion**: create a `videos` row; metadata extracted via FFmpeg when available.
- **Scene detection**: `internal/scenedetect` wraps `PySceneDetect` to compute contiguous time ranges.
- **Caption extraction**: `internal/ffmpeg/ffmpeg.go` uses FFmpeg to export SRT (when subtitle streams exist).
- **Embedding generation**: `internal/processor/processor.go` orchestrates runners per video:
  - Visual (InternVL/IV2) via `internal/embeddings/iv2_runner.py`.
  - Text (e5‑base‑v2) via `internal/embeddings/text_embed_runner.py` (aggregated per scene).
  - CLIP image (ViT‑B/32) via `internal/embeddings/clip_runner.py` (open‑clip preferred, safetensors).
  - CLAP audio via `internal/embeddings/audio_embed_runner.py` (librosa windows per scene).

All runners perform L2‑normalization and communicate using newline‑free JSON on STDIN/STDOUT for robust IPC.


## Design Decisions

- **Two visual embeddings**:
  - InternVL3.5 provides strong scene‑to‑scene visual similarity (1024‑D).
  - CLIP ViT‑B/32 (512‑D) aligns images with text to support text‑to‑image retrieval and fusion.
- **Audio modality**: CLAP (512‑D) captures non‑speech acoustic context, complementary to captions.
- **Text modality**: e5‑base‑v2 (768‑D) robust for sentence/paragraph similarity on captions.
- **Weighted fusion (planned)**: combine similarity from multiple modalities with user‑supplied weights.
- **Isolation of ML code**: all deep learning is contained in Python runners so the Go system remains small, portable, and testable.
- **Safety & supply chain**: prefer `safetensors` models, use open‑clip where possible, and pin PyTorch/CUDA wheels in the container.


## Repository Layout

- `cmd/` – API server main (`cmd/main.go`).
- `internal/database/` – GORM DB, pgvector, DAO helpers.
- `internal/ffmpeg/` – FFmpeg client and SRT extraction.
- `internal/scenedetect/` – scene detection glue around PySceneDetect.
- `internal/embeddings/` – Python runners: `iv2_runner.py`, `clip_runner.py`, `audio_embed_runner.py`, `text_embed_runner.py`.
- `internal/processor/` – worker logic; job handlers for ingestion, scenes, captions, embeddings.
- `migrations/init.sql` – schema + pgvector.
- `docker-compose.yml` – all services.
- `Dockerfile` – multi‑stage build (Go binary + GPU runtime with ML deps).
- `data/videos/` – host folder bound into containers at `/data/videos`.


## Build & Run (Docker Compose)

Requirements:

- Docker + Docker Compose v2
- NVIDIA GPU and container toolkit (recommended). CPU fallback is possible but slow.

Environment:

- Create `.env` (optional) and set `HUGGINGFACE_HUB_TOKEN` if using gated models:

```bash
export HUGGINGFACE_HUB_TOKEN=xxxxxxxx
```

Build and start:

```bash
# from repo root
docker-compose up -d --build

# follow logs
docker-compose logs -f goodclips-api
# or
docker-compose logs -f goodclips-worker
```

Volumes:

- Place videos on host at `./data/videos/yourfile.ext`. Containers read them at `/data/videos/yourfile.ext`.


## Configuration (selected)

Set via `docker-compose.yml` environment on `goodclips-worker`:

- `EMBEDDING_BACKEND=internvl35` – InternVL3.5 visual embedder (defaults to IV2 if unset).
- `IV2_MODEL_ID=OpenGVLab/InternVL3_5-2B`, `IV2_FRAMES=8`, `IV2_STRIDE=4`, `IV2_RES=448`, `IV2_DEVICE=cuda:0`.
- `CLIP_MODEL_ID=openai/clip-vit-base-patch32`, `CLIP_DEVICE=cuda:0`.
- `HUGGINGFACE_HUB_TOKEN` – optional for gated models (also used by IV2/InternVL runners).

Database/Redis:

- `DB_*` vars for Postgres; `REDIS_URL` for job queue.


## API Endpoints (confirmed)

- `GET /api/v1/stats` – database stats summary.
- `GET /api/v1/jobs?type=&limit=` – list jobs.
- `GET /api/v1/jobs/:id` – get job by ID.
- `POST /api/v1/jobs` – enqueue a job.
- `POST /api/v1/search/scenes` – search top‑K scenes similar to an anchor scene (by visual embedding).

Example: search by anchor

```bash
curl -sS -X POST http://localhost:8080/api/v1/search/scenes \
  -H 'Content-Type: application/json' \
  -d '{"anchor":{"video_id":6,"scene_index":0},"k":5}' | jq .
```

Example: enqueue embedding generation for an existing video row

```bash
curl -sS -X POST http://localhost:8080/api/v1/jobs \
  -H 'Content-Type: application/json' \
  -d '{"type":"embedding_generation","payload":{"video_id":6}}' | jq .
```

Other job types supported by the worker:

- `scene_detection`
- `caption_extraction`
- `video_ingestion`
- `embedding_generation`


## Current Status

- Worker environment now includes `scenedetect`, `open-clip-torch`, `librosa`, `safetensors` with PyTorch 2.5.1 CUDA 12.1.
- Schema extended with `scenes.audio_embedding` and `scenes.visual_clip_embedding` and DAO setters added.
- Embedding pipeline persists:
  - Visual (InternVL3.5): 61/61 for `video_id=6`.
  - CLIP ViT‑B/32: 61/61 for `video_id=6`.
  - Audio CLAP: 60/60 for `video_id=6` (one scene had no decodable audio window).
- Known issue: `video_id=1` points to `/data/videos/sample-video.mkv` which does not exist on the host; add the file or update the DB row.
- Next: implement weighted multi‑modal search endpoint combining text/CLIP/audio similarities.

See `project_status.md` for a timestamped activity log.


## Troubleshooting

- "No such file or directory" during caption extraction:
  - Ensure the file exists on host under `./data/videos/` and the path in `videos.filepath` begins with `/data/videos/`.
- `ModuleNotFoundError: scenedetect`:
  - The worker image now installs `scenedetect`. Rebuild if you changed the Dockerfile: `docker-compose up -d --build goodclips-worker`.
- CLIP torch.load vulnerability message:
  - We prefer open‑clip and safetensors; image pins PyTorch to 2.5.1 CUDA 12.1 which works with open‑clip.
- GPU not used:
  - Set `IV2_DEVICE=cuda:0` and `CLIP_DEVICE=cuda:0`; ensure NVIDIA runtime is available. Otherwise runners will fall back to CPU.


## Development Notes

- Go modules and binaries are built in a separate stage; runtime image is CUDA‑enabled with Python ML deps.
- Python runners must:
  - Read a single JSON blob from STDIN and emit a single JSON object on STDOUT.
  - Avoid printing to STDOUT (redirect to STDERR) to keep JSON parseable by the worker.


## License

TBD.
