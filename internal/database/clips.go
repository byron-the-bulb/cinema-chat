package database

import (
	"goodclips-server/internal/models"

	"github.com/pgvector/pgvector-go"
	"gorm.io/gorm/clause"
)

// CreateClip inserts a clip, upserting on (video_id, clip_type, start_time, end_time).
func (db *DB) CreateClip(clip *models.Clip) error {
	return db.DB.Clauses(
		clause.OnConflict{
			Columns: []clause.Column{
				{Name: "video_id"},
				{Name: "clip_type"},
				{Name: "start_time"},
				{Name: "end_time"},
			},
			DoUpdates: clause.Assignments(map[string]interface{}{
				"label":            clip.Label,
				"salience_score":   clip.SalienceScore,
				"source_scene_id":  clip.SourceSceneID,
				"source_caption_id": clip.SourceCaptionID,
				"metadata":         clip.Metadata,
			}),
		},
	).Create(clip).Error
}

// GetClipsByVideoID retrieves all clips for a video.
func (db *DB) GetClipsByVideoID(videoID uint) ([]models.Clip, error) {
	var clips []models.Clip
	err := db.Where("video_id = ?", videoID).Order("start_time ASC").Find(&clips).Error
	return clips, err
}

// GetClipByID returns a single clip by primary key.
func (db *DB) GetClipByID(id uint) (*models.Clip, error) {
	var c models.Clip
	if err := db.First(&c, id).Error; err != nil {
		return nil, err
	}
	return &c, nil
}

// DeleteClipsByVideoID removes all clips for a video (for re-generation).
func (db *DB) DeleteClipsByVideoID(videoID uint) error {
	return db.Where("video_id = ?", videoID).Delete(&models.Clip{}).Error
}

// ClipSearchResult is a single result from any clip search lane.
type ClipSearchResult struct {
	Clip     models.Clip
	Distance float64
	Lane     string // "dialog", "clip", "visual"
}

// SearchClipsByDialogVector searches dialog_embedding (e5-base-v2 of spoken text).
func (db *DB) SearchClipsByDialogVector(vec []float32, k int, filterVideoIDs []uint) ([]ClipSearchResult, error) {
	return db.searchClipsByVector("dialog_embedding", vec, k, filterVideoIDs, []string{"dialog"}, "dialog")
}

// SearchClipsByClipVector searches clip_embedding (CLIP ViT-B/32 keyframe) across all clip types.
func (db *DB) SearchClipsByClipVector(vec []float32, k int, filterVideoIDs []uint) ([]ClipSearchResult, error) {
	return db.searchClipsByVector("clip_embedding", vec, k, filterVideoIDs, nil, "clip")
}

// SearchClipsByVisualVector searches visual_embedding (InternVL) on visual clips.
func (db *DB) SearchClipsByVisualVector(vec []float32, k int, filterVideoIDs []uint) ([]ClipSearchResult, error) {
	return db.searchClipsByVector("visual_embedding", vec, k, filterVideoIDs, []string{"visual"}, "visual")
}

// UpdateClipDialogEmbedding sets the dialog_embedding for a clip by ID.
func (db *DB) UpdateClipDialogEmbedding(clipID uint, vec []float32) error {
	v := pgvector.NewVector(vec)
	return db.Model(&models.Clip{}).Where("id = ?", clipID).Update("dialog_embedding", v).Error
}

// UpdateClipClipEmbedding sets the clip_embedding (CLIP ViT-B/32) for a clip by ID.
func (db *DB) UpdateClipClipEmbedding(clipID uint, vec []float32) error {
	v := pgvector.NewVector(vec)
	return db.Model(&models.Clip{}).Where("id = ?", clipID).Update("clip_embedding", v).Error
}

// UpdateClipAudioEmbedding sets the audio_embedding (CLAP) for a clip by ID.
func (db *DB) UpdateClipAudioEmbedding(clipID uint, vec []float32) error {
	v := pgvector.NewVector(vec)
	return db.Model(&models.Clip{}).Where("id = ?", clipID).Update("audio_embedding", v).Error
}

// UpdateClipVisualEmbedding sets the visual_embedding (InternVL) for a clip by ID.
func (db *DB) UpdateClipVisualEmbedding(clipID uint, vec []float32) error {
	v := pgvector.NewVector(vec)
	return db.Model(&models.Clip{}).Where("id = ?", clipID).Update("visual_embedding", v).Error
}

// UpdateClipTextEmbedding sets the text_embedding (e5 of IV2 description) for a clip by ID.
func (db *DB) UpdateClipTextEmbedding(clipID uint, vec []float32) error {
	v := pgvector.NewVector(vec)
	return db.Model(&models.Clip{}).Where("id = ?", clipID).Update("text_embedding", v).Error
}

// UpdateClipLabel updates the label text for a clip by ID.
func (db *DB) UpdateClipLabel(clipID uint, label string) error {
	return db.Model(&models.Clip{}).Where("id = ?", clipID).Update("label", label).Error
}

// SearchClipsByTextVector searches text_embedding (e5 of IV2 descriptions) on visual clips.
func (db *DB) SearchClipsByTextVector(vec []float32, k int, filterVideoIDs []uint) ([]ClipSearchResult, error) {
	return db.searchClipsByVector("text_embedding", vec, k, filterVideoIDs, []string{"visual"}, "text")
}

// searchClipsByVector is the shared implementation for all clip vector searches.
func (db *DB) searchClipsByVector(embeddingCol string, vec []float32, k int, filterVideoIDs []uint, clipTypes []string, lane string) ([]ClipSearchResult, error) {
	v := pgvector.NewVector(vec)

	type row struct {
		ID              uint
		UUID            string
		VideoID         uint
		ClipType        string
		SourceSceneID   *uint
		SourceCaptionID *uint
		StartTime       float64
		EndTime         float64
		Duration        float64
		Label           string
		SalienceScore   float64
		Distance        float64 `gorm:"column:distance"`
	}

	q := db.Table("clips").
		Select("id, uuid, video_id, clip_type, source_scene_id, source_caption_id, start_time, end_time, duration, label, salience_score, "+embeddingCol+" <=> ? as distance", v).
		Where(embeddingCol + " IS NOT NULL")

	if len(clipTypes) > 0 {
		q = q.Where("clip_type IN ?", clipTypes)
	}
	if len(filterVideoIDs) > 0 {
		q = q.Where("video_id IN ?", filterVideoIDs)
	}

	var rows []row
	if err := q.Order("distance ASC").Limit(k).Scan(&rows).Error; err != nil {
		return nil, err
	}

	results := make([]ClipSearchResult, 0, len(rows))
	for _, r := range rows {
		results = append(results, ClipSearchResult{
			Clip: models.Clip{
				ID:              r.ID,
				UUID:            r.UUID,
				VideoID:         r.VideoID,
				ClipType:        r.ClipType,
				SourceSceneID:   r.SourceSceneID,
				SourceCaptionID: r.SourceCaptionID,
				StartTime:       r.StartTime,
				EndTime:         r.EndTime,
				Duration:        r.Duration,
				Label:           r.Label,
				SalienceScore:   r.SalienceScore,
			},
			Distance: r.Distance,
			Lane:     lane,
		})
	}
	return results, nil
}
