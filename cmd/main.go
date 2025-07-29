package main

import (
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"

	"goodclips-server/internal/database"
	"goodclips-server/internal/models"
	"goodclips-server/internal/queue"
	"goodclips-server/internal/processor"

	"github.com/gin-gonic/gin"
	"github.com/joho/godotenv"
)

var db *database.DB
var jobQueue *queue.Queue
var videoProcessor *processor.VideoProcessor

func main() {
	// Load environment variables
	if err := godotenv.Load(); err != nil {
		log.Println("No .env file found, using environment variables")
	}

	// Check command line arguments
	if len(os.Args) > 1 && os.Args[1] == "worker" {
		runWorker()
		return
	}

	// Initialize database connection
	config := database.GetDefaultConfig()
	var err error
	db, err = database.NewConnection(config)
	if err != nil {
		log.Fatalf("Failed to connect to database: %v", err)
	}
	defer db.Close()

	// Test connection
	if err := db.Health(); err != nil {
		log.Fatalf("Database health check failed: %v", err)
	}
	log.Println("✅ Database connection established")

	// Initialize job queue
	redisURL := getEnvOrDefault("REDIS_URL", "localhost:6379")
	// Extract host:port from redis://host:port format
	if strings.HasPrefix(redisURL, "redis://") {
		redisURL = strings.TrimPrefix(redisURL, "redis://")
	}
	
	queueConfig := queue.Config{
		Addr:     redisURL,
		Password: "",
		DB:       0,
	}
	jobQueue, err = queue.NewQueue(queueConfig)
	if err != nil {
		log.Fatalf("Failed to connect to job queue: %v", err)
	}
	defer jobQueue.Close()
	log.Println("✅ Job queue connection established")

	// Initialize video processor
	videoProcessor = processor.NewVideoProcessor()
	log.Println("✅ Video processor initialized")

	// Run auto-migration (optional - comment out in production)
	// if err := db.AutoMigrate(); err != nil {
	// 	log.Fatalf("Failed to run auto-migration: %v", err)
	// }
	// log.Println("✅ Database migrations completed")
	log.Println("⏭️ Skipping auto-migration (using existing schema)")

	// Initialize Gin router
	r := gin.Default()

	// Middleware
	r.Use(corsMiddleware())
	r.Use(gin.Recovery())

	// Health check endpoint
	r.GET("/health", healthCheck)

	// API v1 routes
	v1 := r.Group("/api/v1")
	{
		// Video management
		v1.GET("/videos", listVideos)
		v1.POST("/videos", createVideo)
		v1.GET("/videos/:id", getVideo)
		v1.DELETE("/videos/:id", deleteVideo)
		
		// Search endpoints
		v1.POST("/search/semantic", searchSemantic)
		v1.POST("/search/text", searchText)
		
		// Statistics
		v1.GET("/stats", getStats)
		
		// Processing jobs
		v1.GET("/jobs", listJobs)
		v1.GET("/jobs/:id", getJob)
		v1.POST("/jobs", createJob)
	}

	// Get port from environment or default to 8080
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	fmt.Printf("🚀 GoodCLIPS Server starting on port %s\n", port)
	log.Fatal(r.Run(":" + port))
}

// Worker function to process jobs
func runWorker() {
	log.Println("🔧 Starting GoodCLIPS worker...")

	// Initialize database connection
	config := database.GetDefaultConfig()
	var err error
	db, err = database.NewConnection(config)
	if err != nil {
		log.Fatalf("Failed to connect to database: %v", err)
	}
	defer db.Close()

	// Initialize job queue
	redisURL := getEnvOrDefault("REDIS_URL", "localhost:6379")
	// Extract host:port from redis://host:port format
	if strings.HasPrefix(redisURL, "redis://") {
		redisURL = strings.TrimPrefix(redisURL, "redis://")
	}
	
	queueConfig := queue.Config{
		Addr:     redisURL,
		Password: "",
		DB:       0,
	}
	jobQueue, err = queue.NewQueue(queueConfig)
	if err != nil {
		log.Fatalf("Failed to connect to job queue: %v", err)
	}
	defer jobQueue.Close()

	// Initialize video processor
	videoProcessor = processor.NewVideoProcessor()

	log.Println("✅ Worker initialized, waiting for jobs...")

	// Worker loop
	for {
		// Try to dequeue a job
		job, err := jobQueue.Dequeue("")
		if err != nil {
			log.Printf("Error dequeuing job: %v", err)
			continue
		}

		if job == nil {
			// No jobs available, continue loop
			continue
		}

		log.Printf("📥 Processing job %s of type %s", job.ID, job.Type)

		// Update job status to running
		err = jobQueue.UpdateJobStatus(job.ID, queue.JobStatusRunning, 0, nil)
		if err != nil {
			log.Printf("Error updating job status: %v", err)
			continue
		}

		// Process the job based on its type
		switch job.Type {
		case queue.JobTypeVideoIngestion:
			err = processVideoIngestionJob(job)
		case queue.JobTypeSceneDetection:
			err = processSceneDetectionJob(job)
		case queue.JobTypeCaptionExtraction:
			err = processCaptionExtractionJob(job)
		case queue.JobTypeEmbeddingGeneration:
			err = processEmbeddingGenerationJob(job)
		default:
			errMsg := fmt.Sprintf("Unknown job type: %s", job.Type)
			jobQueue.UpdateJobStatus(job.ID, queue.JobStatusFailed, 0, &errMsg)
			continue
		}

		// Update job status based on processing result
		if err != nil {
			errMsg := err.Error()
			jobQueue.UpdateJobStatus(job.ID, queue.JobStatusFailed, 0, &errMsg)
			log.Printf("❌ Job %s failed: %v", job.ID, err)
		} else {
			jobQueue.UpdateJobStatus(job.ID, queue.JobStatusCompleted, 100, nil)
			log.Printf("✅ Job %s completed successfully", job.ID)
		}
	}
}

// Job processing functions
func processVideoIngestionJob(job *queue.Job) error {
	return videoProcessor.ProcessVideoIngestion(job.Payload)
}

func processSceneDetectionJob(job *queue.Job) error {
	return videoProcessor.ProcessSceneDetection(job.Payload)
}

func processCaptionExtractionJob(job *queue.Job) error {
	return videoProcessor.ProcessCaptionExtraction(job.Payload)
}

func processEmbeddingGenerationJob(job *queue.Job) error {
	return videoProcessor.ProcessEmbeddingGeneration(job.Payload)
}

// Middleware

func corsMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Header("Access-Control-Allow-Origin", "*")
		c.Header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
		c.Header("Access-Control-Allow-Headers", "Content-Type, Authorization")
		
		if c.Request.Method == "OPTIONS" {
			c.AbortWithStatus(204)
			return
		}
		
		c.Next()
	}
}

// Handlers

func healthCheck(c *gin.Context) {
	// Check database health
	dbHealth := "ok"
	if err := db.Health(); err != nil {
		dbHealth = "error: " + err.Error()
	}

	// Check job queue health
	queueHealth := "ok"
	if err := jobQueue.UpdateJobStatus("test", queue.JobStatusPending, 0, nil); err != nil {
		queueHealth = "error: " + err.Error()
	}

	// Get basic stats
	stats, statsErr := db.GetStats()
	
	response := gin.H{
		"status":    "ok",
		"service":   "goodclips-server",
		"version":   "0.1.0",
		"database":  dbHealth,
		"queue":     queueHealth,
		"timestamp": "now",
	}

	if statsErr == nil {
		response["stats"] = stats
	}

	c.JSON(http.StatusOK, response)
}

func listVideos(c *gin.Context) {
	// Parse pagination parameters
	limitStr := c.DefaultQuery("limit", "20")
	offsetStr := c.DefaultQuery("offset", "0")
	
	limit, err := strconv.Atoi(limitStr)
	if err != nil || limit <= 0 {
		limit = 20
	}
	if limit > 100 {
		limit = 100 // Cap at 100
	}

	offset, err := strconv.Atoi(offsetStr)
	if err != nil || offset < 0 {
		offset = 0
	}

	// Get videos from database
	videos, total, err := db.ListVideos(limit, offset)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": "Failed to fetch videos",
			"details": err.Error(),
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"videos": videos,
		"pagination": gin.H{
			"total":  total,
			"limit":  limit,
			"offset": offset,
			"count":  len(videos),
		},
	})
}

func createVideo(c *gin.Context) {
	var req models.VideoCreateRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": "Invalid request",
			"details": err.Error(),
		})
		return
	}

	// TODO: Calculate file hash
	// TODO: Check if video already exists
	
	// Create video record
	video := &models.Video{
		Filename: req.Filename,
		Filepath: req.Filepath,
		FileHash: "temp_hash_" + req.Filename, // TODO: Calculate real hash
		Title:    req.Title,
		Tags:     models.JSONStringArray(req.Tags),
		Metadata: models.JSONObject(req.Metadata),
		Status:   models.VideoStatusPending,
	}

	if err := db.CreateVideo(video); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": "Failed to create video",
			"details": err.Error(),
		})
		return
	}

	// Create a job to process this video
	jobPayload := map[string]interface{}{
		"video_id": video.ID,
		"filename": video.Filename,
		"filepath": video.Filepath,
	}
	
	job, err := jobQueue.Enqueue(queue.JobTypeVideoIngestion, jobPayload)
	if err != nil {
		log.Printf("Warning: Failed to create processing job for video %d: %v", video.ID, err)
	}

	c.JSON(http.StatusCreated, gin.H{
		"video": video,
		"processing_job": job,
		"message": "Video created successfully",
	})
}

func getVideo(c *gin.Context) {
	idStr := c.Param("id")
	id, err := strconv.ParseUint(idStr, 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": "Invalid video ID",
		})
		return
	}

	video, err := db.GetVideoByID(uint(id))
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error": "Video not found",
		})
		return
	}

	// Get processing jobs for this video
	jobs, _ := db.GetProcessingJobsByVideoID(video.ID)

	c.JSON(http.StatusOK, gin.H{
		"video": video,
		"processing_jobs": jobs,
	})
}

func deleteVideo(c *gin.Context) {
	idStr := c.Param("id")
	id, err := strconv.ParseUint(idStr, 10, 32)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": "Invalid video ID",
		})
		return
	}

	if err := db.DeleteVideo(uint(id)); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": "Failed to delete video",
			"details": err.Error(),
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"message": "Video deleted successfully",
	})
}

func searchSemantic(c *gin.Context) {
	var req models.SearchRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": "Invalid search request",
			"details": err.Error(),
		})
		return
	}

	// TODO: Implement semantic search using pgvector
	
	c.JSON(http.StatusOK, gin.H{
		"message": "Semantic search not yet implemented",
		"query": req.Query,
		"status": "coming_soon",
	})
}

func searchText(c *gin.Context) {
	var req models.SearchRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": "Invalid search request",
			"details": err.Error(),
		})
		return
	}

	// TODO: Implement full-text search in captions
	
	c.JSON(http.StatusOK, gin.H{
		"message": "Text search not yet implemented",
		"query": req.Query,
		"status": "coming_soon",
	})
}

func getStats(c *gin.Context) {
	stats, err := db.GetStats()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": "Failed to get statistics",
			"details": err.Error(),
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"stats": stats,
		"timestamp": "now",
	})
}

func listJobs(c *gin.Context) {
	// Parse query parameters
	limitStr := c.DefaultQuery("limit", "20")
	jobType := c.DefaultQuery("type", "")
	
	limit, err := strconv.Atoi(limitStr)
	if err != nil || limit <= 0 {
		limit = 20
	}
	if limit > 100 {
		limit = 100 // Cap at 100
	}

	// Convert jobType to JobType enum
	var jobTypeEnum queue.JobType
	if jobType != "" {
		jobTypeEnum = queue.JobType(jobType)
	}

	// Get jobs from queue
	jobs, err := jobQueue.ListJobs(jobTypeEnum, limit)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": "Failed to fetch jobs",
			"details": err.Error(),
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"jobs": jobs,
		"count": len(jobs),
	})
}

func getJob(c *gin.Context) {
	jobID := c.Param("id")
	
	job, err := jobQueue.GetJob(jobID)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error": "Job not found",
			"details": err.Error(),
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"job": job,
	})
}

func createJob(c *gin.Context) {
	var req struct {
		Type    string                 `json:"type" binding:"required"`
		Payload map[string]interface{} `json:"payload"`
	}
	
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": "Invalid request",
			"details": err.Error(),
		})
		return
	}

	job, err := jobQueue.Enqueue(queue.JobType(req.Type), req.Payload)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": "Failed to create job",
			"details": err.Error(),
		})
		return
	}

	c.JSON(http.StatusCreated, gin.H{
		"job": job,
		"message": "Job created successfully",
	})
}

// Helper function to get environment variable or default value
func getEnvOrDefault(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}