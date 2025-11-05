package models

import (
	"database/sql/driver"
	"encoding/json"
	"time"

	"github.com/pgvector/pgvector-go"
)

// Video represents a video file in the database
type Video struct {
	ID                uint           `json:"id" gorm:"primaryKey"`
	UUID              string         `json:"uuid" gorm:"type:uuid;default:uuid_generate_v4();unique;not null"`
	Filename          string         `json:"filename" gorm:"size:512;not null"`
	Filepath          string         `json:"filepath" gorm:"size:1024;not null"`
	FileHash          string         `json:"file_hash" gorm:"type:char(64);not null"`
	Title             *string        `json:"title" gorm:"size:256"`
	Duration          float64        `json:"duration" gorm:"default:0;not null"`
	SceneCount        int            `json:"scene_count" gorm:"default:0"`
	CaptionCount      int            `json:"caption_count" gorm:"default:0"`
	EmbeddingModel    string         `json:"embedding_model" gorm:"size:64;default:'openai/clip-vit-base-patch32'"`
	CreatedAt         time.Time      `json:"created_at"`
	UpdatedAt         time.Time      `json:"updated_at"`
	LastProcessedAt   *time.Time     `json:"last_processed_at"`
	Tags              JSONStringArray `json:"tags" gorm:"type:jsonb;default:'[]'"`
	Status            VideoStatus    `json:"status" gorm:"default:'pending'"`
	Metadata          JSONObject     `json:"metadata" gorm:"type:jsonb;default:'{}'"`
	ErrorMessage      *string        `json:"error_message"`
	
	// Relationships
	Scenes           []Scene           `json:"scenes,omitempty" gorm:"foreignKey:VideoID;constraint:OnDelete:CASCADE"`
	Captions         []Caption         `json:"captions,omitempty" gorm:"foreignKey:VideoID;constraint:OnDelete:CASCADE"`
	ProcessingJobs   []ProcessingJob   `json:"processing_jobs,omitempty" gorm:"foreignKey:VideoID;constraint:OnDelete:CASCADE"`
}

// JSONStringArray is a custom type for handling JSON arrays of strings
type JSONStringArray []string

// Scan implements the sql.Scanner interface for JSONStringArray
func (j *JSONStringArray) Scan(value interface{}) error {
	if value == nil {
		*j = []string{}
		return nil
	}
	
	bytes, ok := value.([]byte)
	if !ok {
		return nil
	}
	
	return json.Unmarshal(bytes, j)
}

// Value implements the driver.Valuer interface for JSONStringArray
func (j JSONStringArray) Value() (driver.Value, error) {
	if j == nil {
		return []byte("[]"), nil
	}
	return json.Marshal(j)
}

// JSONObject is a custom type for handling JSON objects
type JSONObject map[string]interface{}

// Scan implements the sql.Scanner interface for JSONObject
func (j *JSONObject) Scan(value interface{}) error {
	if value == nil {
		*j = make(map[string]interface{})
		return nil
	}
	
	bytes, ok := value.([]byte)
	if !ok {
		return nil
	}
	
	return json.Unmarshal(bytes, j)
}

// Value implements the driver.Valuer interface for JSONObject
func (j JSONObject) Value() (driver.Value, error) {
	if j == nil {
		return []byte("{}"), nil
	}
	return json.Marshal(j)
}

// VideoStatus represents the processing status of a video
type VideoStatus string

const (
	VideoStatusPending    VideoStatus = "pending"
	VideoStatusProcessing VideoStatus = "processing"
	VideoStatusCompleted  VideoStatus = "completed"
	VideoStatusDeleted    VideoStatus = "deleted"
)

// Scene represents a video scene with embeddings
type Scene struct {
    ID         uint      `json:"id" gorm:"primaryKey"`
    UUID       string    `json:"uuid" gorm:"type:uuid;default:uuid_generate_v4();unique;not null"`
    VideoID    uint      `json:"video_id" gorm:"not null;uniqueIndex:idx_scene_video_index"`
    SceneIndex int       `json:"scene_index" gorm:"not null;uniqueIndex:idx_scene_video_index"`
    StartTime  float64   `json:"start_time" gorm:"not null"`
    EndTime    float64   `json:"end_time" gorm:"not null"`
    Duration   float64   `json:"duration" gorm:"<-:false;computed:end_time - start_time"`
	
	HasCaptions   bool `json:"has_captions" gorm:"default:false"`
	CaptionCount  int  `json:"caption_count" gorm:"default:0"`
	
	// Vector embeddings (768 dimensions for CLIP-large, 512 for base)
	VisualEmbedding       *pgvector.Vector `json:"visual_embedding,omitempty" gorm:"type:vector(1024)"`
	TextEmbedding         *pgvector.Vector `json:"text_embedding,omitempty" gorm:"type:vector(768)"`
	AudioEmbedding        *pgvector.Vector `json:"audio_embedding,omitempty" gorm:"type:vector(512)"`
	VisualClipEmbedding   *pgvector.Vector `json:"visual_clip_embedding,omitempty" gorm:"type:vector(512)"`
	CombinedEmbedding     *pgvector.Vector `json:"combined_embedding,omitempty" gorm:"type:vector(768)"`
	
	CreatedAt time.Time `json:"created_at"`
	
	// Relationships
	Video    Video     `json:"video,omitempty" gorm:"foreignKey:VideoID"`
	Captions []Caption `json:"captions,omitempty" gorm:"foreignKey:SceneID;constraint:OnDelete:CASCADE"`
}

// Caption represents subtitle/caption text with timing
type Caption struct {
	ID         uint      `json:"id" gorm:"primaryKey"`
	UUID       string    `json:"uuid" gorm:"type:uuid;default:uuid_generate_v4();unique;not null"`
	VideoID    uint      `json:"video_id" gorm:"not null;index"`
	SceneID    *uint     `json:"scene_id" gorm:"index"`
	StartTime  float64   `json:"start_time" gorm:"not null"`
	EndTime    float64   `json:"end_time" gorm:"not null"`
	Duration   float64   `json:"duration" gorm:"<-:false;computed:end_time - start_time"`
	Text       string    `json:"text" gorm:"not null"`
	Language   string    `json:"language" gorm:"size:10;default:'en'"`
	Confidence float64   `json:"confidence" gorm:"default:1.0"`
	CreatedAt  time.Time `json:"created_at"`
	
	// Relationships
	Video *Video `json:"video,omitempty" gorm:"foreignKey:VideoID"`
	Scene *Scene `json:"scene,omitempty" gorm:"foreignKey:SceneID"`
}

// ProcessingJob represents background processing tasks
type ProcessingJob struct {
	ID          uint            `json:"id" gorm:"primaryKey"`
	UUID        string          `json:"uuid" gorm:"type:uuid;default:uuid_generate_v4();unique;not null"`
	VideoID     *uint           `json:"video_id" gorm:"index"`
	JobType     JobType         `json:"job_type" gorm:"not null"`
	Status      JobStatus       `json:"status" gorm:"default:'pending'"`
	Progress    int             `json:"progress" gorm:"default:0;check:progress >= 0 AND progress <= 100"`
	StartedAt   *time.Time      `json:"started_at"`
	CompletedAt *time.Time      `json:"completed_at"`
	ErrorMessage *string        `json:"error_message"`
	Metadata    JSONObject      `json:"metadata" gorm:"type:jsonb;default:'{}'"`
	CreatedAt   time.Time       `json:"created_at"`
	
	// Relationships
	Video *Video `json:"video,omitempty" gorm:"foreignKey:VideoID"`
}

// JobType represents the type of processing job
type JobType string

const (
	JobTypeVideoIngestion      JobType = "video_ingestion"
	JobTypeSceneDetection      JobType = "scene_detection"
	JobTypeCaptionExtraction   JobType = "caption_extraction"
	JobTypeEmbeddingGeneration JobType = "embedding_generation"
)

// JobStatus represents the processing status of a job
type JobStatus string

const (
	JobStatusPending    JobStatus = "pending"
	JobStatusRunning    JobStatus = "running"
	JobStatusCompleted  JobStatus = "completed"
	JobStatusFailed     JobStatus = "failed"
	JobStatusCancelled  JobStatus = "cancelled"
)

// DatabaseStats represents statistics about the database
type DatabaseStats struct {
	TotalVideos           int     `json:"total_videos"`
	CompletedVideos       int     `json:"completed_videos"`
	TotalScenes           int     `json:"total_scenes"`
	ScenesWithEmbeddings  int     `json:"scenes_with_embeddings"`
	TotalCaptions         int     `json:"total_captions"`
	TotalDurationSeconds  float64 `json:"total_duration_seconds"`
	ActiveJobs            int     `json:"active_jobs"`
}

// SearchRequest represents a search query
type SearchRequest struct {
	Query               string    `json:"query" binding:"required"`
	VideoIDs            []uint    `json:"video_ids,omitempty"`
	Limit               int       `json:"limit" binding:"min=1,max=100"`
	SimilarityThreshold float64   `json:"similarity_threshold" binding:"min=0,max=1"`
	EmbeddingType       string    `json:"embedding_type" binding:"oneof=visual text combined"`
}

// SearchResult represents a search result
type SearchResult struct {
	SceneID         uint               `json:"scene_id"`
	Scene           Scene              `json:"scene"`
	Video           Video              `json:"video"`
	Similarity      float64            `json:"similarity"`
	MatchedCaptions []Caption          `json:"matched_captions,omitempty"`
	Context         map[string]any     `json:"context,omitempty"`
}

// SearchResponse represents the response from a search query
type SearchResponse struct {
	Query       string         `json:"query"`
	Results     []SearchResult `json:"results"`
	TotalFound  int            `json:"total_found"`
	SearchTime  float64        `json:"search_time_ms"`
	Metadata    map[string]any `json:"metadata,omitempty"`
}

// VideoCreateRequest represents a request to create/register a video
type VideoCreateRequest struct {
	Filename string            `json:"filename" binding:"required"`
	Filepath string            `json:"filepath" binding:"required"`
	Title    *string           `json:"title"`
	Tags     []string          `json:"tags"`
	Metadata map[string]any    `json:"metadata"`
}

// VideoResponse represents a video with additional calculated fields
type VideoResponse struct {
	Video
	ActualSceneCount   int     `json:"actual_scene_count"`
	ActualCaptionCount int     `json:"actual_caption_count"`
	AvgSceneDuration   float64 `json:"avg_scene_duration"`
	HasEmbeddings      bool    `json:"has_embeddings"`
	ProcessingStatus   string  `json:"processing_status"`
}

// TableName methods for custom table names if needed
func (Video) TableName() string {
	return "videos"
}

func (Scene) TableName() string {
	return "scenes"
}

func (Caption) TableName() string {
	return "captions"
}

func (ProcessingJob) TableName() string {
	return "processing_jobs"
}