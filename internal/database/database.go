package database

import (
	"fmt"
	"log"
	"os"
	"time"

	"goodclips-server/internal/models"

	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

// DB represents the database connection
type DB struct {
	*gorm.DB
}

// Config holds database configuration
type Config struct {
	Host     string
	Port     string
	User     string
	Password string
	DBName   string
	SSLMode  string
	TimeZone string
}

// NewConnection creates a new database connection
func NewConnection(config Config) (*DB, error) {
	dsn := fmt.Sprintf("host=%s user=%s password=%s dbname=%s port=%s sslmode=%s TimeZone=%s",
		config.Host, config.User, config.Password, config.DBName, config.Port, config.SSLMode, config.TimeZone)

	gormConfig := &gorm.Config{
		Logger: logger.New(
			log.New(os.Stdout, "\r\n", log.LstdFlags), // io writer
			logger.Config{
				SlowThreshold:             time.Second,   // Slow SQL threshold
				LogLevel:                  logger.Info,   // Log level
				IgnoreRecordNotFoundError: true,          // Ignore ErrRecordNotFound error for logger
				Colorful:                  true,          // Enable color printing
			},
		),
		NowFunc: func() time.Time {
			return time.Now().UTC()
		},
	}

	db, err := gorm.Open(postgres.Open(dsn), gormConfig)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to database: %w", err)
	}

	// Configure connection pool
	sqlDB, err := db.DB()
	if err != nil {
		return nil, fmt.Errorf("failed to get underlying sql.DB: %w", err)
	}

	// SetMaxIdleConns sets the maximum number of connections in the idle connection pool.
	sqlDB.SetMaxIdleConns(10)

	// SetMaxOpenConns sets the maximum number of open connections to the database.
	sqlDB.SetMaxOpenConns(100)

	// SetConnMaxLifetime sets the maximum amount of time a connection may be reused.
	sqlDB.SetConnMaxLifetime(time.Hour)

	return &DB{db}, nil
}

// GetDefaultConfig returns default database configuration from environment variables
func GetDefaultConfig() Config {
	return Config{
		Host:     getEnvOrDefault("DB_HOST", "localhost"),
		Port:     getEnvOrDefault("DB_PORT", "5432"),
		User:     getEnvOrDefault("DB_USER", "goodclips"),
		Password: getEnvOrDefault("DB_PASSWORD", "goodclips_dev_password"),
		DBName:   getEnvOrDefault("DB_NAME", "goodclips"),
		SSLMode:  getEnvOrDefault("DB_SSLMODE", "disable"),
		TimeZone: getEnvOrDefault("DB_TIMEZONE", "UTC"),
	}
}

// AutoMigrate runs database migrations for all models
func (db *DB) AutoMigrate() error {
	return db.DB.AutoMigrate(
		&models.Video{},
		&models.Scene{},
		&models.Caption{},
		&models.ProcessingJob{},
	)
}

// GetStats queries database statistics
func (db *DB) GetStats() (*models.DatabaseStats, error) {
	var stats models.DatabaseStats
	
	err := db.Raw(`
		SELECT 
			(SELECT COUNT(*) FROM videos) as total_videos,
			(SELECT COUNT(*) FROM videos WHERE status = 'completed') as completed_videos,
			(SELECT COUNT(*) FROM scenes) as total_scenes,
			(SELECT COUNT(*) FROM scenes WHERE visual_embedding IS NOT NULL) as scenes_with_embeddings,
			(SELECT COUNT(*) FROM captions) as total_captions,
			(SELECT COALESCE(SUM(duration), 0) FROM videos WHERE status = 'completed') as total_duration_seconds,
			(SELECT COUNT(*) FROM processing_jobs WHERE status = 'running') as active_jobs
	`).Scan(&stats).Error

	if err != nil {
		return nil, fmt.Errorf("failed to query database stats: %w", err)
	}

	return &stats, nil
}

// Health checks the database connection
func (db *DB) Health() error {
	sqlDB, err := db.DB.DB()
	if err != nil {
		return fmt.Errorf("failed to get underlying sql.DB: %w", err)
	}

	if err := sqlDB.Ping(); err != nil {
		return fmt.Errorf("failed to ping database: %w", err)
	}

	return nil
}

// Close closes the database connection
func (db *DB) Close() error {
	sqlDB, err := db.DB.DB()
	if err != nil {
		return fmt.Errorf("failed to get underlying sql.DB: %w", err)
	}

	return sqlDB.Close()
}

// Helper function to get environment variable or default value
func getEnvOrDefault(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

// Transaction wraps a function in a database transaction
func (db *DB) Transaction(fn func(*gorm.DB) error) error {
	return db.DB.Transaction(fn)
}

// Video service methods

// CreateVideo creates a new video record
func (db *DB) CreateVideo(video *models.Video) error {
	return db.Create(video).Error
}

// GetVideoByID retrieves a video by ID
func (db *DB) GetVideoByID(id uint) (*models.Video, error) {
	var video models.Video
	err := db.Preload("Scenes").Preload("Captions").First(&video, id).Error
	if err != nil {
		return nil, err
	}
	return &video, nil
}

// GetVideoByHash retrieves a video by file hash
func (db *DB) GetVideoByHash(hash string) (*models.Video, error) {
	var video models.Video
	err := db.Where("file_hash = ?", hash).First(&video).Error
	if err != nil {
		return nil, err
	}
	return &video, nil
}

// ListVideos retrieves videos with pagination
func (db *DB) ListVideos(limit, offset int) ([]models.Video, int64, error) {
	var videos []models.Video
	var total int64

	// Get total count
	if err := db.Model(&models.Video{}).Count(&total).Error; err != nil {
		return nil, 0, err
	}

	// Get paginated results
	err := db.Limit(limit).Offset(offset).Order("created_at DESC").Find(&videos).Error
	if err != nil {
		return nil, 0, err
	}

	return videos, total, nil
}

// UpdateVideo updates a video record
func (db *DB) UpdateVideo(video *models.Video) error {
	return db.Save(video).Error
}

// DeleteVideo soft deletes a video record
func (db *DB) DeleteVideo(id uint) error {
	return db.Model(&models.Video{}).Where("id = ?", id).Update("status", models.VideoStatusDeleted).Error
}

// Scene service methods

// CreateScene creates a new scene record
func (db *DB) CreateScene(scene *models.Scene) error {
	return db.Create(scene).Error
}

// GetScenesByVideoID retrieves scenes for a video
func (db *DB) GetScenesByVideoID(videoID uint) ([]models.Scene, error) {
	var scenes []models.Scene
	err := db.Where("video_id = ?", videoID).Order("scene_index ASC").Find(&scenes).Error
	return scenes, err
}

// Caption service methods

// CreateCaption creates a new caption record
func (db *DB) CreateCaption(caption *models.Caption) error {
	return db.Create(caption).Error
}

// GetCaptionsByVideoID retrieves captions for a video
func (db *DB) GetCaptionsByVideoID(videoID uint) ([]models.Caption, error) {
	var captions []models.Caption
	err := db.Where("video_id = ?", videoID).Order("start_time ASC").Find(&captions).Error
	return captions, err
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