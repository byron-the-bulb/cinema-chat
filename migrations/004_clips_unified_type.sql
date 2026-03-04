-- Allow 'clip' as a clip_type value for the unified Lighthouse-only pipeline.
-- Old types ('dialog', 'visual') are kept for backwards compatibility.
ALTER TABLE clips DROP CONSTRAINT IF EXISTS clips_clip_type_check;
ALTER TABLE clips ADD CONSTRAINT clips_clip_type_check
    CHECK (clip_type IN ('dialog', 'visual', 'clip'));
