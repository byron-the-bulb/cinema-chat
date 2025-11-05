# GoodCLIPS Project Status Journal

## 2025-11-03T03:50:17-08:00

- **CLIP embeddings persisted for video 6**
  - Rebuilt GPU worker with `open-clip-torch`, `pillow`, `safetensors`, and PyTorch 2.5.1 CUDA 12.1.
  - Ran embedding_generation for video 6; logs show: "Persisted 61/61 CLIP embeddings for video 6".
  - Verified in Postgres: `visual_clip_embedding` populated for 61 scenes, `audio_embedding` remains 0.
  - Next: implement LAION-CLAP audio runner and weighted multi-modal search endpoint.

## 2025-11-03T02:08:22-08:00

- **CLIP ViT-B/32 integration for scene embeddings**
  - Added `internal/embeddings/clip_runner.py` to compute per-scene CLIP image embeddings (ViT-B/32), L2-normalized, JSON I/O.
  - Updated worker `ProcessEmbeddingGeneration()` to call `clip_runner.py` and persist to `scenes.visual_clip_embedding` via `UpdateSceneVisualClipEmbeddingByIndex()`.
  - Relaxed validation in `cmd/main.go` `searchScenesByAnchor` to avoid strict bind errors; endpoint verified working.
  - Schema already ALTERed to include `visual_clip_embedding` (vector(512)). Next: re-run embedding_generation for video 6 to populate CLIP vectors.

## 2025-11-03T01:26:18-08:00

- **DB schema & worker runtime updates**
  - Added new scene columns in `migrations/init.sql`: `audio_embedding vector(512)`, `visual_clip_embedding vector(512)`.
  - Updated models in `internal/models/models.go` and DAO setters in `internal/database/database.go` for audio/CLIP embeddings.
  - Updated worker Dockerfile runtime-gpu stage to install `scenedetect` (fixes `ModuleNotFoundError`).
  - Rebuilt and restarted containers; ran jobs:
    - Caption extraction on `ginger.mp4` (video 6): no subtitle streams found (no SRT produced).
    - Embedding generation on video 6: persisted 61/61 InternVL visual embeddings; 0 text embeddings (no captions).
  - Next: apply ALTER TABLE on running DB (if needed), implement CLAP/CLIP runners, extend worker for multi-modal, and add weighted search API.

## 2025-11-02T23:55:14-08:00

- **Text semantic search (captions-based) implemented**
  - Added e5-base-v2 runner: `internal/embeddings/text_embed_runner.py` with JSON I/O and L2-normalized vectors.
  - DB (`internal/database/database.go`): added `UpdateSceneTextEmbeddingByIndex()` and `SearchScenesByTextVector()` (pgvector `<=>` on `scenes.text_embedding`).
  - API (`cmd/main.go`): implemented `searchSemantic()` to embed query and search; added `embedTextQuery()` helper and imports.
  - Worker (`internal/processor/processor.go`): extended `ProcessEmbeddingGeneration()` to aggregate per-scene captions and persist `scenes.text_embedding` via runner.
  - Next: add CLAP audio and CLIP visual text-aligned embeddings, DB columns, and weighted multi-modal search endpoint.

## 2025-11-02T23:17:18-08:00

- **Approved multi-modal semantic search plan (video+audio+captions with weighted fusion)**
  - Modalities per scene to persist:
    - Visual (text-aligned) via CLIP ViT-B/32 → `scenes.visual_clip_embedding vector(512)`.
    - Audio (non-speech semantics) via LAION-CLAP → `scenes.audio_embedding vector(512)`.
    - Captions (text semantics) via e5-base-v2 → `scenes.text_embedding vector(768)`.
  - Query-time weighted fusion in SQL: `score = wv*(visual_clip <=> qv) + wa*(audio <=> qa) + wt*(text <=> qt)`.
  - InternVL (existing 1024-D) remains for scene-to-scene visual similarity (`/api/v1/search/scenes`) and optional re-ranking.
  - No ASR required: sources (MKV/DVD) ship with captions; we’ll aggregate per-scene.
  
  - Next steps:
    - DB: add columns `audio_embedding vector(512)` and `visual_clip_embedding vector(512)`; DAO setters and weighted search method.
    - Runners: `text_embed_runner.py` (e5), `audio_embed_runner.py` (CLAP), `clip_embed_runner.py` (CLIP) with JSON I/O.
    - Worker: extend `ProcessEmbeddingGeneration()` to compute/persist scene-level CLIP/CLAP/e5 embeddings.
    - API: implement `POST /api/v1/search/semantic` with weights and optional anchor re-ranking.
    - Indexing later (pgvector IVFFlat/HNSW) after data scales.

## 2025-11-02T22:20:01-08:00

- **Scene Similarity Search API implemented and wiring fixed**
  - Added `POST /api/v1/search/scenes` in `cmd/main.go` (`searchScenesByAnchor`) to return top-K nearest scenes by pgvector cosine distance, excluding the anchor and supporting optional `filter_video_ids`.
  - Database (`internal/database/database.go`): added `GetSceneByVideoAndIndex()` and `SearchSimilarScenesByAnchor()`; restored `GetScenesByVideoID()`; ensured `CreateScene()` upsert updates `end_time` and derived `duration`; added `CreateCaption()` and restored `CreateProcessingJob()`.
  - Fixed Python runner stdout redirection in `internal/embeddings/iv2_runner.py` so HF warnings go to stderr and JSON on stdout remains parseable.
  - Repaired `cmd/main.go` structure after prior patch drift: restored clean `runWorker()`, moved job helper fns to top-level, added `getStats()` handler, and restored `listJobs()`/`getJob()`.
  - Next: rebuild API/worker images, restart services, and validate search with an anchor scene that has `visual_embedding`.

## 2025-11-02T20:33:25-08:00

- **InternVL3.5 backend integrated; DB migrated to 1024-D**
  - Added `internvl35` backend in `internal/embeddings/iv2_runner.py` using `model.vision_model` pooler_output averaged across frames.
  - Updated `internal/processor/processor.go` to pass `backend`, set InternVL3.5 defaults, and persist when dim=1024.
  - Pinned deps in `Dockerfile` (transformers==4.52.1, einops, accelerate).
  - Switched compose env to `EMBEDDING_BACKEND=internvl35`, `IV2_MODEL_ID=OpenGVLab/InternVL3_5-2B`, frames=8, res=448.
  - Migrated DB column `scenes.visual_embedding` to `vector(1024)` and updated GORM tag in `models.go` and `migrations/init.sql`.
  - One job failed due to stale `IV2_MODEL_ID` (old local path). Next: rebuild worker, restart, verify env, re-run job.

## 2025-11-02T20:12:46-08:00

- **InternVL3.5-2B embedding probe (Option C) successful**
  - Loaded `OpenGVLab/InternVL3_5-2B` in worker (added `einops`, `accelerate` for runtime).
  - Probed `model.vision_model` (InternVisionModel) with 8 sampled frames from `ginger.mp4` at 448px.
  - Obtained `pooler_output` per frame and averaged across frames → scene vector.
  - Observed `embedding_dim = 1024`.
  - Next steps proposed: add `internvl35` backend in `iv2_runner.py`, pin deps in Dockerfile (transformers>=4.52.1, einops, accelerate), set `EMBEDDING_BACKEND=internvl35` and `IV2_MODEL_ID=OpenGVLab/InternVL3_5-2B`, and ALTER DB `scenes.visual_embedding` to `vector(1024)` before persisting.

## 2025-11-02T19:57:04-08:00

- **Option C (InternVL3.5-2B) quick check started**
  - Attempted lightweight load of `OpenGVLab/InternVL3_5-2B` inside worker.
  - Installed `einops`; model then requested `accelerate` for `device_map="auto"`.
  - FlashAttention2 not installed (warning only); not required for the check.
  - Next: install `accelerate` in worker and retry model load to probe for embedding-friendly interfaces.
  - No manual model download required; Transformers will fetch weights on first load.

## 2025-11-02T17:19:45-08:00

- **Temporary local IV2 model path**
  - Pointed `IV2_MODEL_ID` to `/models/InternVideo2-stage2_1b-224p-f4` and mounted `./models` into worker.
  - Note: AutoModel requires a full model directory (config.json + modeling code + weights), not a single .pt file.
  - TODO: Replace local path with proper HF snapshot after accepting gated access, or vendor OpenGVLab code into the image and load weights directly.

## 2025-11-02T01:07:59-07:00

- **GPU runtime online + IV2 runner implemented**
  - Configured NVIDIA Container Toolkit; `docker info` shows `nvidia` runtime; `nvidia-smi` works on host; `torch.cuda.is_available()` true inside worker.
  - Implemented `internal/embeddings/iv2_runner.py`: loads IV2 via Transformers (`AutoModel` with `trust_remote_code=True`), decodes mid-scene clips via `decord`, normalizes frames, and calls `model.get_vid_feat(...)` on GPU.
  - Updated `internal/processor/processor.go` to persist embeddings when `embedding_dim=768` using `db.UpdateSceneVisualEmbeddingByIndex()` and set `video.EmbeddingModel`.
  - Added `UpdateSceneVisualEmbeddingByIndex()` and DB helpers in `internal/database/database.go`.
  - Added `IV2_DEVICE=cuda:0` and `HUGGINGFACE_HUB_TOKEN` passthrough in `docker-compose.yml`.
  - First run failed due to gated HF repo; awaiting token, then re-run embeddings for video id=6.

## 2025-11-01T23:17:21-07:00

- **Processor Build Fixes**
  - Closed function scope in `internal/processor/processor.go` and added `return nil` to end `ProcessCaptionExtraction()`.
  - Implemented missing DB helpers in `internal/database/database.go`: `GetVideoByID()`, `UpdateVideo()`.
  - Ready to rebuild GPU worker image and proceed with IV2 runner testing.

## 2025-11-01T23:09:36-07:00

- **Compose GPU Fix**
  - Replaced unsupported `gpus: all` with `runtime: nvidia` for `goodclips-worker` in `docker-compose.yml` to support docker-compose v1.
  - Added `NVIDIA_VISIBLE_DEVICES=all` and `NVIDIA_DRIVER_CAPABILITIES=compute,utility,video` envs.
  - Kept `target: runtime-gpu` build stage for the worker.

- **Next**
  - Rebuild worker and verify GPU availability via `torch.cuda.is_available()` inside container.
  - Implement real InternVideo2 inference in `iv2_runner.py` and persist embeddings.

## 2025-11-01T22:49:58-07:00

- **GPU Embeddings Pipeline (start)**
  - Added `internal/embeddings/iv2_runner.py` scaffold defining JSON I/O for InternVideo2 embeddings.
  - Updated `internal/processor/processor.go` to call IV2 runner from `ProcessEmbeddingGeneration()` with batched scene ranges; parses output and logs.
  - Extended `Dockerfile` with a `runtime-gpu` stage based on PyTorch CUDA; installed decord/av/opencv/transformers/timm/huggingface-hub.
  - Updated `docker-compose.yml` to build worker with `target: runtime-gpu`, added IV2 env vars, and requested NVIDIA GPU.

- **Notes**
  - IV2 runner currently returns a scaffold response (no real vectors yet). Next: implement model load, frame sampling, and inference.
  - DB rebuild is acceptable during dev; we will set pgvector dimension to match the chosen IV2 checkpoint once confirmed.

- **Next**
  - Verify GPU inside worker container (torch.cuda.is_available()).
  - Implement real IV2 inference in the runner and return vectors + dimension.
  - Persist embeddings and optionally add a pgvector index.

## 2025-11-01T22:21:55-07:00

- **Decisions**
  - Back-compat/migrations: not required; DB can be rebuilt during dev.
  - Keep a dev-time switch for embeddings backend (CLIP vs InternVideo2), but target a single backend for prod.
  - Start directly with multi-frame mid-scene sampling for InternVideo2 (no single-frame stopgap needed).

- **InternVideo2 Inputs (Answer to Q)**
  - InternVideo2 consumes tensors of video frames (shape ~ [B, T, C, H, W]). It does not directly operate on a raw video file handle.
  - We will feed a video filepath to the Python runner, which will decode frames internally (e.g., via Decord/PyAV/FFmpeg) for each scene clip and pass the frames to the model.

- **Plan Update**
  - IV2: Implement mid-scene clip extraction in runner (T frames, stride f4/f8, 224p), batched per video.
  - CLIP: Use existing keyframes per scene as the baseline path; we can later add a ClipKIT-based selector if needed.
  - Single set of pgvector columns sized to the chosen backend during dev; DB can be dropped/rebuilt if we switch.

- **TODO**
  - Caption idempotency (unique index + upsert) similar to scenes.
  - Implement `iv2_runner.py`, probe embedding dimension, and wire `ProcessEmbeddingGeneration()` to the runner.
  - Add `EMBEDDING_BACKEND` env switch and minimal GPU-enabled runtime for IV2 (with CPU CLIP fallback).

- **Next Steps**
  - Create IV2 runner interface: input (video path + scene time ranges), output (per-scene vectors).
  - Determine embedding dimension from the chosen IV2 checkpoint and set pgvector size accordingly (rebuilt DB acceptable).
  - Wire Go processor to call runner once per video; store embeddings and add search hooks.

## 2025-11-01T21:39:19-07:00

- **Scene Idempotency**
  - Added composite unique index on `scenes (video_id, scene_index)` in `internal/models/models.go`.
  - Upsert on insert via `CreateScene()` in `internal/database/database.go` using `OnConflict` to update timing/count fields only.
  - Verified: re-running scene detection keeps scene count stable and avoids duplicates.

- **Queue Robustness**
  - Reordered `Enqueue()` in `internal/queue/queue.go` to `HSET` before `LPUSH` to avoid `redis: nil` on worker start.
  - Pending verify after rebuild: ensure no `redis: nil` when new jobs start.

- **Embeddings Generation Plan**
  - Will implement a pluggable embeddings backend with a Python runner (CLIP baseline, InternVideo2 as preferred target).
  - Short-term: wire `ProcessEmbeddingGeneration()` to call runner per-scene using existing keyframes.
  - Medium-term: add video-clip support for models requiring temporal context.

- **TODO**
  - Caption idempotency (unique index + upsert) similar to scenes.

- **Next**
  - Research InternVideo2 vs CLIP and propose adopting InternVideo2 for video embeddings.
  - Add GPU-enabled runtime (PyTorch + CUDA) for InternVideo2 inference, with fallback to CLIP on CPU.

## 2025-11-01T17:08:46-07:00

- **Runtime & Scene Detection Fixed**
  - Switched to Debian slim runtime with PySceneDetect and OpenCV; added `sd_runner.py` to avoid local module shadowing (`internal/scenedetect/scenedetect.py`).
  - `internal/scenedetect/scenedetect.go` now calls `/root/internal/scenedetect/sd_runner.py`.
  - Verified: runner outputs JSON; worker processed `scene_detection` for ginger.mp4; keyframes extracted.

- **DB Model Fix**
  - `internal/models/models.go`: changed `Scene` embedding fields to pointer types (`*pgvector.Vector`) so inserts use NULL instead of `[]`.
  - Resolved pgvector error: `vector must have at least 1 dimension`.

- **Queue Race Fix**
  - `internal/queue/queue.go`: reorder `Enqueue` to `HSET` job data before `LPUSH` to avoid worker `UpdateJobStatus` hitting `redis: nil`.

- **Verification**
  - Direct runner: 61 scenes detected for `/data/videos/ginger.mp4`.
  - Worker job succeeded; Postgres shows 61 scenes for video_id=6; worker extracts all keyframes to `/data/videos/video_6_keyframes/`.

- **Next**
  - Rebuild API/worker images with queue fix and verify no `redis: nil` on resubmitted jobs.

## 2025-11-01T16:31:41-07:00

- **Host Volume & Test Clip**
  - Fixed host perms for `data/` and copied `resources/ginger.mp4` to `data/videos/`.
  - Verified `/data/videos/ginger.mp4` visible in both API and worker.
  - Created scene detection job for video id 6; failed with `exit status 1` (as expected pre-runtime switch).

- **Runtime Update**
  - Switched Docker runtime to Debian slim with `ffmpeg`, `opencv-python-headless`, `numpy`, `scenedetect` in `Dockerfile`.
  - Goal: fix PySceneDetect failures on Alpine.

- **Next Verify Plan**
  - Rebuild & restart: `docker-compose up -d --build goodclips-api goodclips-worker`.
  - Re-run scene detection job for video id 6 and monitor worker logs.
  - Note: `ProcessEmbeddingGeneration()` remains a stub.

## 2025-11-01T15:38:45-07:00

- **Completed**
  - Added `goodclips-worker` service in `docker-compose.yml` with shared volume.
  - Mounted `./data/videos:/data/videos` on API and worker.
  - Increased scene detection/keyframe timeouts and made them configurable via env (`SCENEDETECT_TIMEOUT_SECS`, `KEYFRAME_TIMEOUT_SECS`).
  - Implemented env vars in compose for API and worker.

- **Files Changed**
  - `docker-compose.yml`: added worker service, volumes, and timeout env vars.
  - `internal/scenedetect/scenedetect.go`: refactored to restore structure and added configurable timeouts.

- **Quick Verify Plan**
  - Build and start worker: `docker-compose up -d --build goodclips-worker`.
  - Check services: `docker-compose ps`.
  - Verify volume mounts: `docker-compose exec -T goodclips-api ls -ld /data/videos` and same for worker.
  - Verify env vars:
    - API: `docker-compose exec -T goodclips-api sh -lc 'echo $SCENEDETECT_TIMEOUT_SECS $KEYFRAME_TIMEOUT_SECS'`
    - Worker: `docker-compose exec -T goodclips-worker sh -lc 'echo $SCENEDETECT_TIMEOUT_SECS $KEYFRAME_TIMEOUT_SECS'`

## 2025-11-01T15:03:14-07:00

- **Quick Verify Results**
  - Build/restart OK (`docker-compose up -d --build goodclips-api`).
  - `/health`: `database=ok`, `queue=ok`, stats present.
  - `/api/v1/videos`: returns 5 videos as expected.

## 2025-11-01T15:03:14-07:00

- **Completed (Step 1 & 2)**
  - Worker now consumes from all job queues via `DequeueAny()`.
  - Health check uses Redis `Ping()` instead of updating a non-existent job.
  - Processor now accepts `jobQueue` and enqueues follow-up jobs: `scene_detection`, `caption_extraction`, `embedding_generation`.
  - Minor fixes to ensure build (queue ping return, scene detection handler).

- **Files Changed**
  - `internal/queue/queue.go`: added `DequeueAny()` and `Ping()`.
  - `cmd/main.go`: pass `jobQueue` to `processor.NewVideoProcessor()`, worker uses `DequeueAny(nil)`, health check uses `Ping()`, fixed response map.
  - `internal/processor/processor.go`: added `jobQueue` field, updated constructor, implemented `createSubsequentJobs()`, fixed `ProcessSceneDetection()`.

- **Quick Verify Plan**
  - Rebuild and restart API: `docker-compose up -d --build goodclips-api`.
  - Health: `curl -sS http://localhost:8080/health | jq .` (queue should be `ok`).
  - Videos: `curl -sS http://localhost:8080/api/v1/videos | jq .`.

- **Next (coming up)**
  - Add `goodclips-worker` service to compose and mount `/data/videos` volume.
  - Increase scene detection timeouts.

## 2025-11-01T14:42:49-07:00

- **Smoke Check Summary**
  - Stack healthy: Postgres (pgvector), Redis (PING=PONG), pgAdmin running. API reachable.
  - DB schema present: tables `videos`, `scenes`, `captions`, `processing_jobs` verified via `\dt`.
  - API `/health`: database ok; queue shows `error: failed to get job data: redis: nil` (expected due to current health check design).
  - `GET /api/v1/videos`: 5 videos returned; most with status `pending` and no scenes yet; sample video has duration 120.5s.

- **Next**
  - Start addressing findings: fix worker dequeue, enqueue follow-up jobs, add worker service to compose, add storage volume, and improve queue health check.

## 2025-11-01T14:30:01-07:00

- **Update**
  - Created append-only `project_status.md` journal. Starting smoke check.
- **Action Taken**
  - Attempted `docker compose up -d postgres redis pgadmin`; encountered CLI mismatch: `unknown shorthand flag: 'd' in -d`.
- **Next Step**
  - Use `docker-compose` to bring up services and verify DB/Redis, then start API for `/health` and `/api/v1/videos`.

## 2025-11-01T14:30:01-07:00

- **Summary**
  - Initialized a status journal to track progress with append-only entries.
  - Reviewed architecture plan in `microservices_database_plan.md` and current implementation.

- **Current State Snapshot**
  - **Orchestration**: `docker-compose.yml` defines `postgres` (pgvector), `redis`, `pgadmin`, and `goodclips-api` (port 8080). Missing dedicated `goodclips-worker` service.
  - **Database**: SQL migrations at `migrations/init.sql` create `videos`, `scenes`, `captions`, `processing_jobs` with pgvector enabled and useful indexes/views. GORM access in `internal/database/` with CRUD + `GetStats()`.
  - **API**: `cmd/main.go` exposes `/api/v1/videos`, `/api/v1/jobs`, `/api/v1/search/*` (search endpoints stubbed). `/health` reports DB and queue status (queue may show error due to a synthetic update call).
  - **Queue**: Redis queue in `internal/queue/` with LPUSH/BRPOP per job-type. Enqueue works; Dequeue API consumes one queue name.
  - **Processing**: `internal/processor/processor.go` implements ingestion (FFmpeg metadata), scene detection via `internal/scenedetect/` (Python PySceneDetect + ffmpeg keyframes), caption extraction to SRT. Embedding generation stubbed.
  - **Docker**: Multi-stage `Dockerfile`. Final stage uses Alpine with `python3`, `ffmpeg`, and `pip install scenedetect` + script at `/root/internal/scenedetect/scenedetect.py`.

- **Gaps / Risks (to address next)**
  - **Worker consumption**: `runWorker()` dequeues from `jobs:` (empty) instead of per-type queues (`jobs:video_ingestion`, etc.).
  - **Follow-up jobs**: `createSubsequentJobs()` only logs; does not enqueue scene/caption/embedding jobs.
  - **PySceneDetect on Alpine**: Likely needs `opencv-python-headless` which is problematic on Alpine; prefer Debian slim base. Also remove `--break-system-packages` (not valid on Alpine).
  - **Storage mount**: No `/data/videos` volume for containers; API expects valid `filepath` inside container.
  - **Timeouts**: Scene detection (30s) likely too short for real videos.

- **Immediate Next Steps**
  - Do a smoke check: bring up docker stack, verify Postgres (tables), Redis (PING), API `/health` and basic `/api/v1/videos`.
  - Then fix worker queue consumption and enqueue follow-up jobs; adjust Docker base image and mounts.

- **Smoke Check Plan**
  - `docker compose up -d --build`
  - Check services: `docker compose ps`
  - API health: `curl http://localhost:8080/health`
  - Postgres schema: `docker compose exec -T postgres psql -U goodclips -d goodclips -c "\dt"`
  - Redis health: `docker compose exec -T redis redis-cli ping`
