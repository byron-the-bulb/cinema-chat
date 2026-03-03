-- 002_clips.sql — Add clips table for curated dialog + visual clips.
--
-- Clips reference existing scenes and captions but do not modify them.
-- Dialog clips get their own dedicated embedding (not blended with IV2).
-- Visual clips are Lighthouse-identified highlights from non-speech gaps.

CREATE TABLE IF NOT EXISTS clips (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,

    -- Clip type and source linkage
    clip_type VARCHAR(16) NOT NULL CHECK (clip_type IN ('dialog', 'visual')),
    source_scene_id INTEGER REFERENCES scenes(id) ON DELETE SET NULL,
    source_caption_id INTEGER REFERENCES captions(id) ON DELETE SET NULL,

    -- Playback boundaries
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    duration REAL GENERATED ALWAYS AS (end_time - start_time) STORED,

    -- Human-readable: spoken text for dialog clips, IV2 description for visual
    label TEXT NOT NULL DEFAULT '',
    salience_score REAL DEFAULT 0.5,

    -- Embeddings
    dialog_embedding vector(768),      -- e5-base-v2 of spoken words (dialog clips)
    visual_embedding vector(1024),     -- InternVL keyframe (visual clips)
    clip_embedding vector(512),        -- CLIP ViT-B/32 keyframe (both types)
    audio_embedding vector(512),       -- CLAP audio (both types)

    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(video_id, clip_type, start_time, end_time)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_clips_video_id ON clips(video_id);
CREATE INDEX IF NOT EXISTS idx_clips_type ON clips(clip_type);
CREATE INDEX IF NOT EXISTS idx_clips_video_type ON clips(video_id, clip_type);

-- Vector indexes (HNSW for fast approximate search)
CREATE INDEX IF NOT EXISTS idx_clips_dialog_emb ON clips
    USING hnsw (dialog_embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_clips_clip_emb ON clips
    USING hnsw (clip_embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_clips_visual_emb ON clips
    USING hnsw (visual_embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_clips_audio_emb ON clips
    USING hnsw (audio_embedding vector_cosine_ops);
