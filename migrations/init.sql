-- GoodCLIPS Database Schema
-- PostgreSQL with pgvector extension for semantic video search

-- Enable pgvector extension for vector similarity search
CREATE EXTENSION IF NOT EXISTS vector;

-- Enable uuid extension for unique identifiers
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Videos table - stores metadata for each video file
CREATE TABLE videos (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,
    filename VARCHAR(512) NOT NULL,
    filepath VARCHAR(1024) NOT NULL,
    file_hash CHAR(64) UNIQUE NOT NULL,
    title VARCHAR(256),
    duration REAL NOT NULL DEFAULT 0,
    scene_count INTEGER DEFAULT 0,
    caption_count INTEGER DEFAULT 0,
    embedding_model VARCHAR(64) DEFAULT 'openai/clip-vit-base-patch32',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_processed_at TIMESTAMP WITH TIME ZONE,
    tags JSONB DEFAULT '[]'::jsonb,
    status VARCHAR(32) DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'error', 'deleted')),
    metadata JSONB DEFAULT '{}'::jsonb,
    error_message TEXT
);

-- Scenes table - stores individual scene data with embeddings
CREATE TABLE scenes (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    scene_index INTEGER NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    duration REAL GENERATED ALWAYS AS (end_time - start_time) STORED,
    has_captions BOOLEAN DEFAULT FALSE,
    caption_count INTEGER DEFAULT 0,
    
    -- Vector embeddings (768 dimensions for CLIP-large, 512 for base)
    visual_embedding vector(768),
    text_embedding vector(768), 
    combined_embedding vector(768),
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Ensure scene_index is unique within each video
    UNIQUE(video_id, scene_index)
);

-- Captions/Subtitles table - stores extracted text with timing
CREATE TABLE captions (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    scene_id INTEGER REFERENCES scenes(id) ON DELETE CASCADE,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    duration REAL GENERATED ALWAYS AS (end_time - start_time) STORED,
    text TEXT NOT NULL,
    language VARCHAR(10) DEFAULT 'en',
    confidence REAL DEFAULT 1.0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Processing jobs table - tracks background processing tasks
CREATE TABLE processing_jobs (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,
    video_id INTEGER REFERENCES videos(id) ON DELETE CASCADE,
    job_type VARCHAR(50) NOT NULL CHECK (job_type IN ('video_ingestion', 'scene_detection', 'caption_extraction', 'embedding_generation')),
    status VARCHAR(32) DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    progress INTEGER DEFAULT 0 CHECK (progress >= 0 AND progress <= 100),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for performance

-- Videos indexes
CREATE INDEX idx_videos_status ON videos(status);
CREATE INDEX idx_videos_created_at ON videos(created_at DESC);
CREATE INDEX idx_videos_file_hash ON videos(file_hash);
CREATE INDEX idx_videos_tags ON videos USING GIN(tags);
CREATE INDEX idx_videos_metadata ON videos USING GIN(metadata);

-- Scenes indexes
CREATE INDEX idx_scenes_video_id ON scenes(video_id);
CREATE INDEX idx_scenes_start_time ON scenes(video_id, start_time);
CREATE INDEX idx_scenes_has_captions ON scenes(has_captions) WHERE has_captions = true;

-- Vector similarity indexes (using IVFFlat for approximate nearest neighbor)
-- Note: These will be created after we have some data, as they require training
-- CREATE INDEX idx_scenes_visual_embedding ON scenes USING ivfflat (visual_embedding vector_cosine_ops) WITH (lists = 100);
-- CREATE INDEX idx_scenes_text_embedding ON scenes USING ivfflat (text_embedding vector_cosine_ops) WITH (lists = 100);  
-- CREATE INDEX idx_scenes_combined_embedding ON scenes USING ivfflat (combined_embedding vector_cosine_ops) WITH (lists = 100);

-- Captions indexes
CREATE INDEX idx_captions_video_id ON captions(video_id);
CREATE INDEX idx_captions_scene_id ON captions(scene_id);
CREATE INDEX idx_captions_start_time ON captions(video_id, start_time);
CREATE INDEX idx_captions_text_search ON captions USING gin(to_tsvector('english', text));

-- Processing jobs indexes
CREATE INDEX idx_processing_jobs_video_id ON processing_jobs(video_id);
CREATE INDEX idx_processing_jobs_status ON processing_jobs(status);
CREATE INDEX idx_processing_jobs_created_at ON processing_jobs(created_at DESC);

-- Functions for updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers to automatically update timestamps
CREATE TRIGGER update_videos_updated_at 
    BEFORE UPDATE ON videos 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Views for common queries

-- Video summary view with calculated statistics
CREATE VIEW video_summary AS
SELECT 
    v.*,
    COALESCE(s.scene_count, 0) as actual_scene_count,
    COALESCE(c.caption_count, 0) as actual_caption_count,
    COALESCE(s.avg_scene_duration, 0) as avg_scene_duration,
    CASE 
        WHEN v.status = 'completed' AND s.embeddings_count > 0 THEN true
        ELSE false
    END as has_embeddings
FROM videos v
LEFT JOIN (
    SELECT 
        video_id,
        COUNT(*) as scene_count,
        AVG(duration) as avg_scene_duration,
        COUNT(visual_embedding) as embeddings_count
    FROM scenes 
    GROUP BY video_id
) s ON v.id = s.video_id
LEFT JOIN (
    SELECT video_id, COUNT(*) as caption_count
    FROM captions 
    GROUP BY video_id
) c ON v.id = c.video_id;

-- Database statistics view
CREATE VIEW database_stats AS
SELECT
    (SELECT COUNT(*) FROM videos) as total_videos,
    (SELECT COUNT(*) FROM videos WHERE status = 'completed') as completed_videos,
    (SELECT COUNT(*) FROM scenes) as total_scenes,
    (SELECT COUNT(*) FROM scenes WHERE visual_embedding IS NOT NULL) as scenes_with_embeddings,
    (SELECT COUNT(*) FROM captions) as total_captions,
    (SELECT COALESCE(SUM(duration), 0) FROM videos WHERE status = 'completed') as total_duration_seconds,
    (SELECT COUNT(*) FROM processing_jobs WHERE status = 'running') as active_jobs;

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO goodclips;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO goodclips;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO goodclips;

-- Insert initial data
INSERT INTO videos (filename, filepath, file_hash, title, duration, status, metadata) VALUES 
('sample-video.mkv', '/data/videos/sample-video.mkv', 'sample_hash_123', 'Sample Video', 120.5, 'pending', '{"sample": true}'::jsonb);

-- Success message
DO $$
BEGIN
    RAISE NOTICE 'GoodCLIPS database schema created successfully!';
    RAISE NOTICE 'Total tables created: %', (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('videos', 'scenes', 'captions', 'processing_jobs'));
    RAISE NOTICE 'Total indexes created: %', (SELECT COUNT(*) FROM pg_indexes WHERE schemaname = 'public');
END $$;