package main

import (
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"

	"goodclips-server/internal/database"
	"goodclips-server/internal/models"

	"github.com/gin-gonic/gin"
	"github.com/joho/godotenv"
)

var db *database.DB

func main() {
	// Load environment variables
	if err := godotenv.Load(); err != nil {
		log.Println("No .env file found, using environment variables")
	}

	// Check command line arguments
	if len(os.Args) > 1 && os.Args[1] == "worker" {
		log.Fatal("Worker mode not yet implemented")
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
	}

	// Get port from environment or default to 8080
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	fmt.Printf("🚀 GoodCLIPS Server starting on port %s\n", port)
	log.Fatal(r.Run(":" + port))
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

	// Get basic stats
	stats, statsErr := db.GetStats()
	
	response := gin.H{
		"status":    "ok",
		"service":   "goodclips-server",
		"version":   "0.1.0",
		"database":  dbHealth,
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

	c.JSON(http.StatusCreated, gin.H{
		"video": video,
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
	// TODO: Implement job listing
	c.JSON(http.StatusOK, gin.H{
		"jobs": []map[string]interface{}{},
		"message": "Job listing not yet implemented",
		"status": "coming_soon",
	})
}

func getJob(c *gin.Context) {
	jobID := c.Param("id")
	
	// TODO: Implement job retrieval
	c.JSON(http.StatusOK, gin.H{
		"job_id": jobID,
		"message": "Job retrieval not yet implemented",
		"status": "coming_soon",
	})
}

// Helper function to get environment variable or default value
func getEnvOrDefault(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}