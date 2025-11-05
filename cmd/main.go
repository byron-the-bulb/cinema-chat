package main

import (
    "bytes"
    "encoding/json"
    "fmt"
    "io"
    "log"
    "net/http"
    "os"
    "os/exec"
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

    // Initialize job queue (for API to enqueue jobs)
    redisURL := getEnvOrDefault("REDIS_URL", "localhost:6379")
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

    // Initialize video processor (pass jobQueue for follow-up enqueues)
    videoProcessor = processor.NewVideoProcessor(db, jobQueue)
    log.Println("✅ Video processor initialized")

    // Run auto-migration (optional - comment out in production)
    // if err := db.AutoMigrate(); err != nil {
    //     log.Fatalf("Failed to run auto-migration: %v", err)
    // }
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
        v1.POST("/search/scenes", searchScenesByAnchor)
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

// searchScenesByAnchor returns top-K nearest scenes to the anchor scene's visual embedding
func searchScenesByAnchor(c *gin.Context) {
    type Anchor struct {
        VideoID    uint `json:"video_id"`
        SceneIndex int  `json:"scene_index"`
    }
    type Req struct {
        Anchor         Anchor `json:"anchor"`
        K              int    `json:"k"`
        FilterVideoIDs []uint `json:"filter_video_ids"`
    }
    var req Req
    if err := c.ShouldBindJSON(&req); err != nil {
        c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request", "details": err.Error()})
        return
    }
    k := req.K
    if k <= 0 {
        k = 10
    }
    if k > 100 {
        k = 100
    }
    scenes, dists, err := db.SearchSimilarScenesByAnchor(req.Anchor.VideoID, req.Anchor.SceneIndex, k, req.FilterVideoIDs)
    if err != nil {
        c.JSON(http.StatusBadRequest, gin.H{"error": "Search failed", "details": err.Error()})
        return
    }
    items := make([]gin.H, 0, len(scenes))
    for i, s := range scenes {
        items = append(items, gin.H{
            "scene": gin.H{
                "id":            s.ID,
                "uuid":          s.UUID,
                "video_id":      s.VideoID,
                "scene_index":   s.SceneIndex,
                "start_time":    s.StartTime,
                "end_time":      s.EndTime,
                "duration":      s.Duration,
                "has_captions":  s.HasCaptions,
                "caption_count": s.CaptionCount,
                "created_at":    s.CreatedAt,
            },
            "distance": dists[i],
        })
    }
    c.JSON(http.StatusOK, gin.H{
        "anchor": gin.H{"video_id": req.Anchor.VideoID, "scene_index": req.Anchor.SceneIndex},
        "k":       k,
        "results": items,
        "count":   len(items),
    })
}

// searchText is a simple placeholder for keyword caption search (not implemented yet)
func searchText(c *gin.Context) {
    var req struct {
        Query    string `json:"query"`
        VideoIDs []uint `json:"video_ids"`
        Limit    int    `json:"limit"`
    }
    if err := c.ShouldBindJSON(&req); err != nil {
        c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid search request", "details": err.Error()})
        return
    }
    c.JSON(http.StatusNotImplemented, gin.H{"error": "caption keyword search not implemented yet"})
}

// getStats returns aggregate DB stats
func getStats(c *gin.Context) {
    stats, err := db.GetStats()
    if err != nil {
        c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to fetch stats", "details": err.Error()})
        return
    }
    c.JSON(http.StatusOK, stats)
}

// listJobs returns a list of jobs, optionally filtered by type
func listJobs(c *gin.Context) {
    jobTypeStr := c.DefaultQuery("type", "")
    limitStr := c.DefaultQuery("limit", "50")
    limit, err := strconv.Atoi(limitStr)
    if err != nil || limit <= 0 {
        limit = 50
    }
    jobs, err := jobQueue.ListJobs(queue.JobType(jobTypeStr), limit)
    if err != nil {
        c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to list jobs", "details": err.Error()})
        return
    }
    c.JSON(http.StatusOK, gin.H{"jobs": jobs, "count": len(jobs)})
}

// getJob returns a job by ID
func getJob(c *gin.Context) {
    id := c.Param("id")
    job, err := jobQueue.GetJob(id)
    if err != nil {
        c.JSON(http.StatusNotFound, gin.H{"error": "Job not found", "details": err.Error()})
        return
    }
    c.JSON(http.StatusOK, gin.H{"job": job})
}

// createJob enqueues a processing job
func createJob(c *gin.Context) {
    var req struct {
        Type    string                 `json:"type"`
        Payload map[string]interface{} `json:"payload"`
    }
    if err := c.ShouldBindJSON(&req); err != nil {
        c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid request", "details": err.Error()})
        return
    }
    if req.Type == "" {
        c.JSON(http.StatusBadRequest, gin.H{"error": "Missing job type"})
        return
    }
    job, err := jobQueue.Enqueue(queue.JobType(req.Type), req.Payload)
    if err != nil {
        c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to create job", "details": err.Error()})
        return
    }
    c.JSON(http.StatusOK, gin.H{"message": "Job created successfully", "job": job})
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
    videoProcessor = processor.NewVideoProcessor(db, jobQueue)

    log.Println("✅ Worker initialized, waiting for jobs...")

    // Worker loop
    for {
        // Try to dequeue a job
        job, err := jobQueue.DequeueAny(nil)
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

    // Check job queue health via ping
    queueHealth := "ok"
    if err := jobQueue.Ping(); err != nil {
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
    // Local request type to avoid strict validator tags in models.SearchRequest
    var req struct {
        Query    string `json:"query"`
        VideoIDs []uint `json:"video_ids"`
        Limit    int    `json:"limit"`
    }
    if err := c.ShouldBindJSON(&req); err != nil {
        c.JSON(http.StatusBadRequest, gin.H{
            "error":   "Invalid search request",
            "details": err.Error(),
        })
        return
    }

    // Defaults
    limit := req.Limit
    if limit <= 0 {
        limit = 10
    }
    if limit > 100 {
        limit = 100
    }

    // Embed the query in text space (e5-base-v2)
    vec, err := embedTextQuery(req.Query)
    if err != nil {
        c.JSON(http.StatusInternalServerError, gin.H{
            "error":   "Failed to embed query",
            "details": err.Error(),
        })
        return
    }

    // DB vector search on scenes.text_embedding
    scenes, dists, err := db.SearchScenesByTextVector(vec, limit, req.VideoIDs)
    if err != nil {
        c.JSON(http.StatusInternalServerError, gin.H{
            "error":   "Search failed",
            "details": err.Error(),
        })
        return
    }

    items := make([]gin.H, 0, len(scenes))
    for i, s := range scenes {
        items = append(items, gin.H{
            "scene": gin.H{
                "id":            s.ID,
                "uuid":          s.UUID,
                "video_id":      s.VideoID,
                "scene_index":   s.SceneIndex,
                "start_time":    s.StartTime,
                "end_time":      s.EndTime,
                "duration":      s.Duration,
                "has_captions":  s.HasCaptions,
                "caption_count": s.CaptionCount,
                "created_at":    s.CreatedAt,
            },
            "distance": dists[i],
        })
    }

    c.JSON(http.StatusOK, gin.H{
        "query":   req.Query,
        "limit":   limit,
        "count":   len(items),
        "results": items,
    })
}
// Helper function to get environment variable or default value
func getEnvOrDefault(key, defaultValue string) string {
    if value := os.Getenv(key); value != "" {
        return value
    }
    return defaultValue
}

// embedTextQuery runs the e5-base-v2 text embedding runner to obtain a 768-D vector for the query
func embedTextQuery(query string) ([]float32, error) {
    payload := map[string]any{
        "text": query,
        "mode": "query",
    }
    b, _ := json.Marshal(payload)
    cmd := exec.Command("python3", "/root/internal/embeddings/text_embed_runner.py")
    cmd.Stdin = bytes.NewReader(b)
    stdout, _ := cmd.StdoutPipe()
    stderr, _ := cmd.StderrPipe()
    if err := cmd.Start(); err != nil {
        return nil, fmt.Errorf("failed to start text_embed_runner: %w", err)
    }
    outBytes, _ := io.ReadAll(stdout)
    errBytes, _ := io.ReadAll(stderr)
    if err := cmd.Wait(); err != nil {
        return nil, fmt.Errorf("text_embed_runner failed: %v; stderr: %s", err, string(errBytes))
    }
    var resp struct {
        Model        string     `json:"model"`
        EmbeddingDim int        `json:"embedding_dim"`
        Vector       []float32  `json:"vector"`
        Error        string     `json:"error"`
    }
    if err := json.Unmarshal(outBytes, &resp); err != nil {
        return nil, fmt.Errorf("failed to parse text_embed_runner output: %v; raw: %s", err, string(outBytes))
    }
    if resp.Error != "" {
        return nil, fmt.Errorf("runner error: %s", resp.Error)
    }
    if len(resp.Vector) == 0 {
        return nil, fmt.Errorf("empty embedding returned")
    }
    return resp.Vector, nil
}