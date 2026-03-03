-- Add text_embedding column for e5 embeddings of IV2 visual descriptions (visual clips).
-- Separate from dialog_embedding which holds e5 embeddings of spoken text (dialog clips).
ALTER TABLE clips ADD COLUMN IF NOT EXISTS text_embedding vector(768);

CREATE INDEX IF NOT EXISTS idx_clips_text_emb
    ON clips USING hnsw (text_embedding vector_cosine_ops);
