package database

import (
    "errors"
    "os"
    "strconv"
    "time"

    "goodclips-server/internal/models"

    "gorm.io/driver/postgres"
    "gorm.io/gorm"
    "gorm.io/gorm/clause"
    "gorm.io/gorm/logger"
    "github.com/pgvector/pgvector-go"
)

// DB represents the database connection
type DB struct {
    *gorm.DB
}

// GetSceneByVideoAndIndex fetches a single scene by (video_id, scene_index)
func (db *DB) GetSceneByVideoAndIndex(videoID uint, sceneIndex int) (*models.Scene, error) {
    var s models.Scene
    if err := db.Where("video_id = ? AND scene_index = ?", videoID, sceneIndex).First(&s).Error; err != nil {
        return nil, err
    }
    return &s, nil
}

// SearchSimilarScenesByAnchor finds top-K nearest scenes by cosine distance to the anchor scene's visual embedding.
// It excludes the anchor itself and can optionally filter by a list of video IDs.
func (db *DB) SearchSimilarScenesByAnchor(anchorVideoID uint, anchorSceneIndex int, k int, filterVideoIDs []uint) ([]models.Scene, []float64, error) {
    // Load anchor
    anchor, err := db.GetSceneByVideoAndIndex(anchorVideoID, anchorSceneIndex)
    if err != nil {
        return nil, nil, err
    }
    if anchor.VisualEmbedding == nil {
        return nil, nil, errors.New("anchor scene has no visual_embedding")
    }

    // Build query using GORM
    type row struct {
        ID           uint
        UUID         string
        VideoID      uint
        SceneIndex   int
        StartTime    float64
        EndTime      float64
        Duration     float64
        HasCaptions  bool
        CaptionCount int
        CreatedAt    time.Time
        Distance     float64 `gorm:"column:distance"`
    }

    q := db.Table("scenes").
        Select("id, uuid, video_id, scene_index, start_time, end_time, duration, has_captions, caption_count, created_at, visual_embedding <=> ? as distance", *anchor.VisualEmbedding).
        Where("visual_embedding IS NOT NULL").
        Where("NOT (video_id = ? AND scene_index = ?)", anchorVideoID, anchorSceneIndex)
    if len(filterVideoIDs) > 0 {
        q = q.Where("video_id IN ?", filterVideoIDs)
    }
    var rows []row
    if err := q.Order("distance ASC").Limit(k).Scan(&rows).Error; err != nil {
        return nil, nil, err
    }

    scenes := make([]models.Scene, 0, len(rows))
    dists := make([]float64, 0, len(rows))
    for _, r := range rows {
        scenes = append(scenes, models.Scene{
            ID:           r.ID,
            UUID:         r.UUID,
            VideoID:      r.VideoID,
            SceneIndex:   r.SceneIndex,
            StartTime:    r.StartTime,
            EndTime:      r.EndTime,
            Duration:     r.Duration,
            HasCaptions:  r.HasCaptions,
            CaptionCount: r.CaptionCount,
            CreatedAt:    r.CreatedAt,
        })
        dists = append(dists, r.Distance)
    }
    return scenes, dists, nil
}

// Scene service methods

// CreateScene creates a new scene record
func (db *DB) CreateScene(scene *models.Scene) error {
    // upsert by (video_id, scene_index) to keep scene insertion idempotent.
    // Only update timing/count flags so embeddings/captions remain intact if present.
    return db.DB.Clauses(
        clause.OnConflict{
            Columns:   []clause.Column{{Name: "video_id"}, {Name: "scene_index"}},
            DoUpdates: clause.Assignments(map[string]interface{}{
                "start_time":    scene.StartTime,
                "end_time":      scene.EndTime,
                // duration is derived; keep it in sync in case it's stored
                "has_captions":  scene.HasCaptions,
                "caption_count": scene.CaptionCount,
            }),
        },
    ).Create(scene).Error
}

// GetScenesByVideoID retrieves scenes for a video
func (db *DB) GetScenesByVideoID(videoID uint) ([]models.Scene, error) {
    var scenes []models.Scene
    err := db.Where("video_id = ?", videoID).Order("scene_index ASC").Find(&scenes).Error
    return scenes, err
}

// GetCaptionsByVideoID retrieves captions for a video
func (db *DB) GetCaptionsByVideoID(videoID uint) ([]models.Caption, error) {
    var captions []models.Caption
    err := db.Where("video_id = ?", videoID).Order("start_time ASC").Find(&captions).Error
    return captions, err
}

// CreateCaption creates a new caption record
func (db *DB) CreateCaption(caption *models.Caption) error {
    return db.Create(caption).Error
}

// Processing job service methods

// CreateProcessingJob creates a new processing job
func (db *DB) CreateProcessingJob(job *models.ProcessingJob) error {
    return db.Create(job).Error
}

// GetProcessingJobsByVideoID retrieves processing jobs for a video
func (db *DB) GetProcessingJobsByVideoID(videoID uint) ([]models.ProcessingJob, error) {
	var jobs []models.ProcessingJob
	err := db.Where("video_id = ?", videoID).Order("created_at DESC").Find(&jobs).Error
	return jobs, err
}

// UpdateProcessingJob updates a processing job
func (db *DB) UpdateProcessingJob(job *models.ProcessingJob) error {
	return db.Save(job).Error
}

// Video service methods

// GetVideoByID returns a video by its primary key ID
func (db *DB) GetVideoByID(id uint) (*models.Video, error) {
    var v models.Video
    if err := db.First(&v, id).Error; err != nil {
        return nil, err
    }
    return &v, nil
}

// UpdateVideo persists changes to a video
func (db *DB) UpdateVideo(video *models.Video) error {
    return db.Save(video).Error
}

// Connection & config helpers

type Config struct {
    Host     string
    Port     int
    User     string
    Password string
    DBName   string
    SSLMode  string
}

// GetDefaultConfig reads environment variables to build the DB config
func GetDefaultConfig() Config {
    portStr := getEnv("DB_PORT", "5432")
    port, _ := strconv.Atoi(portStr)
    return Config{
        Host:     getEnv("DB_HOST", "localhost"),
        Port:     port,
        User:     getEnv("DB_USER", "postgres"),
        Password: getEnv("DB_PASSWORD", ""),
        DBName:   getEnv("DB_NAME", "postgres"),
        SSLMode:  getEnv("DB_SSLMODE", "disable"),
    }
}

// NewConnection opens a new GORM connection to Postgres
func NewConnection(cfg Config) (*DB, error) {
    dsn := "host=" + cfg.Host +
        " user=" + cfg.User +
        " password=" + cfg.Password +
        " dbname=" + cfg.DBName +
        " port=" + strconv.Itoa(cfg.Port) +
        " sslmode=" + cfg.SSLMode +
        " TimeZone=UTC"
    gdb, err := gorm.Open(postgres.Open(dsn), &gorm.Config{Logger: logger.Default.LogMode(logger.Silent)})
    if err != nil {
        return nil, err
    }
    return &DB{gdb}, nil
}

// Close closes the underlying sql.DB
func (db *DB) Close() error {
    sqlDB, err := db.DB.DB()
    if err != nil {
        return err
    }
    return sqlDB.Close()
}

// Health pings the database
func (db *DB) Health() error {
    sqlDB, err := db.DB.DB()
    if err != nil {
        return err
    }
    return sqlDB.Ping()
}

// Stats & listing

// GetStats returns aggregate statistics for the API
func (db *DB) GetStats() (models.DatabaseStats, error) {
    var stats models.DatabaseStats
    var n int64
    var f float64

    if err := db.Model(&models.Video{}).Count(&n).Error; err == nil {
        stats.TotalVideos = int(n)
    }
    n = 0
    if err := db.Model(&models.Video{}).Where("status = ?", models.VideoStatusCompleted).Count(&n).Error; err == nil {
        stats.CompletedVideos = int(n)
    }
    n = 0
    if err := db.Model(&models.Scene{}).Count(&n).Error; err == nil {
        stats.TotalScenes = int(n)
    }
    n = 0
    if err := db.Model(&models.Scene{}).Where("visual_embedding IS NOT NULL").Count(&n).Error; err == nil {
        stats.ScenesWithEmbeddings = int(n)
    }
    f = 0
    if err := db.Model(&models.Video{}).Select("COALESCE(SUM(duration), 0)").Scan(&f).Error; err == nil {
        stats.TotalDurationSeconds = f
    }
    n = 0
    if err := db.Model(&models.ProcessingJob{}).Where("status IN ?", []models.JobStatus{models.JobStatusPending, models.JobStatusRunning}).Count(&n).Error; err == nil {
        stats.ActiveJobs = int(n)
    }
    return stats, nil
}

// ListVideos returns a page of videos and the total count
func (db *DB) ListVideos(limit, offset int) ([]models.Video, int, error) {
    var videos []models.Video
    var total int64
    if err := db.Model(&models.Video{}).Count(&total).Error; err != nil {
        return nil, 0, err
    }
    if err := db.Order("created_at DESC").Limit(limit).Offset(offset).Find(&videos).Error; err != nil {
        return nil, 0, err
    }
    return videos, int(total), nil
}

// CreateVideo inserts a new video
func (db *DB) CreateVideo(video *models.Video) error {
    return db.Create(video).Error
}

// DeleteVideo deletes a video by ID
func (db *DB) DeleteVideo(id uint) error {
    return db.Delete(&models.Video{}, id).Error
}

// helper
func getEnv(key, def string) string {
    if v := os.Getenv(key); v != "" {
        return v
    }
    return def
}

// UpdateSceneVisualEmbeddingByIndex sets the visual embedding for a scene identified by (video_id, scene_index)
func (db *DB) UpdateSceneVisualEmbeddingByIndex(videoID uint, sceneIndex int, vec []float32) error {
    v := pgvector.NewVector(vec)
    return db.Model(&models.Scene{}).
        Where("video_id = ? AND scene_index = ?", videoID, sceneIndex).
        Updates(map[string]interface{}{
            "visual_embedding": &v,
        }).Error
}

// UpdateSceneTextEmbeddingByIndex sets the text embedding for a scene identified by (video_id, scene_index)
func (db *DB) UpdateSceneTextEmbeddingByIndex(videoID uint, sceneIndex int, vec []float32) error {
    v := pgvector.NewVector(vec)
    return db.Model(&models.Scene{}).
        Where("video_id = ? AND scene_index = ?", videoID, sceneIndex).
        Updates(map[string]interface{}{
            "text_embedding": &v,
        }).Error
}

// UpdateSceneAudioEmbeddingByIndex sets the audio embedding for a scene identified by (video_id, scene_index)
func (db *DB) UpdateSceneAudioEmbeddingByIndex(videoID uint, sceneIndex int, vec []float32) error {
    v := pgvector.NewVector(vec)
    return db.Model(&models.Scene{}).
        Where("video_id = ? AND scene_index = ?", videoID, sceneIndex).
        Updates(map[string]interface{}{
            "audio_embedding": &v,
        }).Error
}

// UpdateSceneVisualClipEmbeddingByIndex sets the CLIP visual (text-aligned) embedding for a scene identified by (video_id, scene_index)
func (db *DB) UpdateSceneVisualClipEmbeddingByIndex(videoID uint, sceneIndex int, vec []float32) error {
    v := pgvector.NewVector(vec)
    return db.Model(&models.Scene{}).
        Where("video_id = ? AND scene_index = ?", videoID, sceneIndex).
        Updates(map[string]interface{}{
            "visual_clip_embedding": &v,
        }).Error
}

// SearchScenesByTextVector finds top-K nearest scenes by cosine distance to a provided text embedding vector.
// Optionally filter by a set of video IDs.
func (db *DB) SearchScenesByTextVector(vec []float32, k int, filterVideoIDs []uint) ([]models.Scene, []float64, error) {
    v := pgvector.NewVector(vec)

    type row struct {
        ID           uint
        UUID         string
        VideoID      uint
        SceneIndex   int
        StartTime    float64
        EndTime      float64
        Duration     float64
        HasCaptions  bool
        CaptionCount int
        CreatedAt    time.Time
        Distance     float64 `gorm:"column:distance"`
    }

    q := db.Table("scenes").
        Select("id, uuid, video_id, scene_index, start_time, end_time, duration, has_captions, caption_count, created_at, text_embedding <=> ? as distance", v).
        Where("text_embedding IS NOT NULL")
    if len(filterVideoIDs) > 0 {
        q = q.Where("video_id IN ?", filterVideoIDs)
    }

    var rows []row
    if err := q.Order("distance ASC").Limit(k).Scan(&rows).Error; err != nil {
        return nil, nil, err
    }

    scenes := make([]models.Scene, 0, len(rows))
    dists := make([]float64, 0, len(rows))
    for _, r := range rows {
        scenes = append(scenes, models.Scene{
            ID:           r.ID,
            UUID:         r.UUID,
            VideoID:      r.VideoID,
            SceneIndex:   r.SceneIndex,
            StartTime:    r.StartTime,
            EndTime:      r.EndTime,
            Duration:     r.Duration,
            HasCaptions:  r.HasCaptions,
            CaptionCount: r.CaptionCount,
            CreatedAt:    r.CreatedAt,
        })
        dists = append(dists, r.Distance)
    }
    return scenes, dists, nil
}