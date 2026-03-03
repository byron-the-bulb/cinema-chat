package main

import (
    "bufio"
    "bytes"
    "encoding/json"
    "fmt"
    "io"
    "log"
    "net/http"
    "os"
    "path/filepath"
    "strconv"
    "strings"
    "time"

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
        v1.POST("/search/clips", searchClips)

        // File transfer — GET lets process-movie.sh pull SRT sidecars from
        // the RunPod instance; PUT lets it upload local video files to the pod.
        v1.GET("/files/:filename", serveFile)
        v1.PUT("/files/:filename", uploadFile)

        // Pod log streaming — tail /workspace/goodclips.log written by entrypoint.sh
        // ?tail=N   return last N lines (default 200)
        // ?follow=true  stream new lines as they arrive (like tail -f)
        v1.GET("/logs", streamLogs)

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

    // Start a minimal upload-only server on a separate port (default 9000).
    // This port is exposed as direct TCP on RunPod, bypassing the HTTP proxy
    // size limit that causes 413 on large video file uploads.
    uploadPort := getEnvOrDefault("UPLOAD_PORT", "9000")
    go func() {
        uploadR := gin.New()
        uploadR.Use(gin.Recovery())
        uploadR.PUT("/api/v1/files/:filename", uploadFile)
        log.Printf("📤 Upload server (direct TCP) starting on port %s\n", uploadPort)
        if err := uploadR.Run(":" + uploadPort); err != nil {
            log.Printf("Upload server error: %v", err)
        }
    }()

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

// searchText finds scenes by dialog similarity.
// Embeds the query with e5-base-v2 and searches against scenes that have real
// subtitle captions (language != 'iv2'), returning the matched dialog text alongside
// each result. Intended for bot responses: find clips where characters say something
// semantically similar to the bot's reply.
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
    if req.Query == "" {
        c.JSON(http.StatusBadRequest, gin.H{"error": "query is required"})
        return
    }

    limit := req.Limit
    if limit <= 0 {
        limit = 10
    }
    if limit > 100 {
        limit = 100
    }

    vec, err := embedTextQuery(req.Query)
    if err != nil {
        c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to embed query", "details": err.Error()})
        return
    }

    // Pad seconds added before/after the dialog timestamps for the clip boundaries.
    // Gives a brief visual breath before the first word and after the last.
    const clipPad = 0.5

    results, err := db.SearchScenesByDialogVector(vec, limit, req.VideoIDs)
    if err != nil {
        c.JSON(http.StatusInternalServerError, gin.H{"error": "Search failed", "details": err.Error()})
        return
    }

    items := make([]gin.H, 0, len(results))
    for _, r := range results {
        clipStart := r.DialogStart - clipPad
        if clipStart < 0 {
            clipStart = 0
        }
        items = append(items, gin.H{
            "scene": gin.H{
                "id":            r.Scene.ID,
                "uuid":          r.Scene.UUID,
                "video_id":      r.Scene.VideoID,
                "scene_index":   r.Scene.SceneIndex,
                "start_time":    r.Scene.StartTime,
                "end_time":      r.Scene.EndTime,
                "duration":      r.Scene.Duration,
                "has_captions":  r.Scene.HasCaptions,
                "caption_count": r.Scene.CaptionCount,
                "created_at":    r.Scene.CreatedAt,
            },
            "distance":    r.Distance,
            "dialog_text": r.DialogText,
            "clip_start":  clipStart,
            "clip_end":    r.DialogEnd + clipPad,
        })
    }

    c.JSON(http.StatusOK, gin.H{
        "query":   req.Query,
        "limit":   limit,
        "count":   len(items),
        "results": items,
    })
}

// searchClips searches the clips table using three parallel lanes:
// 1. Dialog: e5-base-v2(query) → dialog_embedding on dialog clips
// 2. CLIP cross-modal: CLIP-text(query) → clip_embedding on all clips
// 3. Visual description: e5-base-v2(query) → visual_embedding on visual clips (TODO: needs text_embedding column)
// Results are merged by normalized distance, deduplicated, and returned as top K.
func searchClips(c *gin.Context) {
    var req struct {
        Query        string   `json:"query"`
        DialogQuery  string   `json:"dialog_query"`  // optional: separate query for dialog lane
        VisualQuery  string   `json:"visual_query"`  // optional: separate query for CLIP/visual lane
        VideoIDs     []uint   `json:"video_ids"`
        Limit        int      `json:"limit"`
        ClipTypes    []string `json:"clip_types"`     // optional filter: ["dialog"], ["visual"], or both
        DialogWeight *float64 `json:"dialog_weight"`  // weight for dialog lane (default 1.0)
        VisualWeight *float64 `json:"visual_weight"`  // weight for CLIP/visual lane (default 1.0)
    }
    if err := c.ShouldBindJSON(&req); err != nil {
        c.JSON(http.StatusBadRequest, gin.H{"error": "Invalid search request", "details": err.Error()})
        return
    }
    if req.Query == "" {
        c.JSON(http.StatusBadRequest, gin.H{"error": "query is required"})
        return
    }
    limit := req.Limit
    if limit <= 0 {
        limit = 10
    }
    if limit > 100 {
        limit = 100
    }

    // Lane weights (default 1.0 each)
    dialogWeight := 1.0
    visualWeight := 1.0
    if req.DialogWeight != nil {
        dialogWeight = *req.DialogWeight
    }
    if req.VisualWeight != nil {
        visualWeight = *req.VisualWeight
    }

    // Per-lane queries (fall back to main query)
    dialogQuery := req.Query
    if req.DialogQuery != "" {
        dialogQuery = req.DialogQuery
    }
    visualQuery := req.Query
    if req.VisualQuery != "" {
        visualQuery = req.VisualQuery
    }

    // Lane 1: embed query with e5-base-v2 for dialog search
    var e5Vec []float32
    var e5Err error
    if dialogWeight > 0 {
        e5Vec, e5Err = embedTextQuery(dialogQuery)
    }

    // Lane 2: embed query with CLIP text encoder for cross-modal search
    var clipVec []float32
    var clipErr error
    if visualWeight > 0 {
        clipVec, clipErr = embedClipTextQuery(visualQuery)
    }

    // Collect per-lane scores for weighted merging
    type laneScores struct {
        DialogScore float64
        ClipScore   float64
        TextScore   float64 // Lane 3: e5 on IV2 descriptions (visual clips)
        BestResult  database.ClipSearchResult
        BestLane    string
    }
    clips := make(map[uint]*laneScores) // clip ID → scores
    fetchLimit := limit * 3              // fetch more per lane, merge later

    // Lane 1: dialog embedding search
    if dialogWeight > 0 && e5Err == nil {
        results, err := db.SearchClipsByDialogVector(e5Vec, fetchLimit, req.VideoIDs)
        if err != nil {
            log.Printf("Warning: dialog lane search failed: %v", err)
        } else {
            maxDist := 0.0
            for _, r := range results {
                if r.Distance > maxDist {
                    maxDist = r.Distance
                }
            }
            if maxDist <= 0 {
                maxDist = 1.0
            }
            for _, r := range results {
                score := 1.0 - (r.Distance / maxDist)
                if existing, ok := clips[r.Clip.ID]; ok {
                    existing.DialogScore = score
                    if score > existing.ClipScore {
                        existing.BestResult = r
                        existing.BestLane = "dialog"
                    }
                } else {
                    clips[r.Clip.ID] = &laneScores{
                        DialogScore: score,
                        BestResult:  r,
                        BestLane:    "dialog",
                    }
                }
            }
        }
    } else if dialogWeight > 0 {
        log.Printf("Warning: e5 embedding failed: %v", e5Err)
    }

    // Lane 2: CLIP cross-modal search
    if visualWeight > 0 && clipErr == nil {
        results, err := db.SearchClipsByClipVector(clipVec, fetchLimit, req.VideoIDs)
        if err != nil {
            log.Printf("Warning: CLIP lane search failed: %v", err)
        } else {
            maxDist := 0.0
            for _, r := range results {
                if r.Distance > maxDist {
                    maxDist = r.Distance
                }
            }
            if maxDist <= 0 {
                maxDist = 1.0
            }
            for _, r := range results {
                score := 1.0 - (r.Distance / maxDist)
                if existing, ok := clips[r.Clip.ID]; ok {
                    existing.ClipScore = score
                    if score > existing.DialogScore {
                        existing.BestResult = r
                        existing.BestLane = "clip"
                    }
                } else {
                    clips[r.Clip.ID] = &laneScores{
                        ClipScore:  score,
                        BestResult: r,
                        BestLane:   "clip",
                    }
                }
            }
        }
    } else if visualWeight > 0 {
        log.Printf("Warning: CLIP text embedding failed (lane 2 skipped): %v", clipErr)
    }

    // Lane 3: text embedding search on IV2 descriptions of visual clips
    if visualWeight > 0 && e5Err == nil {
        // Reuse e5 vector (same model encodes both dialog queries and visual description queries)
        textVec := e5Vec
        if req.VisualQuery != "" {
            // If a separate visual query was provided, re-embed it with e5
            textVec, _ = embedTextQuery(req.VisualQuery)
        }
        if textVec != nil {
            results, err := db.SearchClipsByTextVector(textVec, fetchLimit, req.VideoIDs)
            if err != nil {
                log.Printf("Warning: text lane (Lane 3) search failed: %v", err)
            } else {
                maxDist := 0.0
                for _, r := range results {
                    if r.Distance > maxDist {
                        maxDist = r.Distance
                    }
                }
                if maxDist <= 0 {
                    maxDist = 1.0
                }
                for _, r := range results {
                    score := 1.0 - (r.Distance / maxDist)
                    if existing, ok := clips[r.Clip.ID]; ok {
                        existing.TextScore = score
                        // Lane 3 runs last — beat both previous lanes to become BestLane
                        if score > existing.DialogScore && score > existing.ClipScore {
                            existing.BestResult = r
                            existing.BestLane = "text"
                        }
                    } else {
                        clips[r.Clip.ID] = &laneScores{
                            TextScore:  score,
                            BestResult: r,
                            BestLane:   "text",
                        }
                    }
                }
            }
        }
    }

    // Compute weighted combined score per clip
    type scored struct {
        Result database.ClipSearchResult
        Score  float64
        Lane   string
    }
    totalWeight := dialogWeight + visualWeight
    if totalWeight <= 0 {
        totalWeight = 1.0
    }
    sorted := make([]scored, 0, len(clips))
    for _, ls := range clips {
        // Lanes 2 (CLIP) and 3 (text/IV2) both use visualWeight — take the best of the two
        bestVisualScore := ls.ClipScore
        if ls.TextScore > bestVisualScore {
            bestVisualScore = ls.TextScore
        }
        combinedScore := (dialogWeight*ls.DialogScore + visualWeight*bestVisualScore) / totalWeight
        sorted = append(sorted, scored{
            Result: ls.BestResult,
            Score:  combinedScore,
            Lane:   ls.BestLane,
        })
    }
    // Sort descending by score
    for i := 0; i < len(sorted); i++ {
        for j := i + 1; j < len(sorted); j++ {
            if sorted[j].Score > sorted[i].Score {
                sorted[i], sorted[j] = sorted[j], sorted[i]
            }
        }
    }
    if len(sorted) > limit {
        sorted = sorted[:limit]
    }

    // Build response
    items := make([]gin.H, 0, len(sorted))
    for _, s := range sorted {
        clip := s.Result.Clip

        // Fetch video info
        videoInfo := gin.H{}
        if v, err := db.GetVideoByID(clip.VideoID); err == nil {
            videoInfo = gin.H{
                "id":       v.ID,
                "filename": v.Filename,
                "filepath": v.Filepath,
                "title":    v.Title,
            }
        }

        items = append(items, gin.H{
            "clip": gin.H{
                "id":               clip.ID,
                "uuid":             clip.UUID,
                "video_id":         clip.VideoID,
                "clip_type":        clip.ClipType,
                "start_time":       clip.StartTime,
                "end_time":         clip.EndTime,
                "duration":         clip.Duration,
                "label":            clip.Label,
                "salience_score":   clip.SalienceScore,
                "source_scene_id":  clip.SourceSceneID,
                "source_caption_id": clip.SourceCaptionID,
            },
            "video":        videoInfo,
            "score":        s.Score,
            "matched_lane": s.Lane,
        })
    }

    c.JSON(http.StatusOK, gin.H{
        "query":   req.Query,
        "limit":   limit,
        "count":   len(items),
        "results": items,
    })
}

// embedClipTextQuery encodes a text query using CLIP's text encoder (ViT-B/32)
// for cross-modal text→image search. Returns a 512-D vector.
func embedClipTextQuery(query string) ([]float32, error) {
    clipURL := os.Getenv("CLIP_EMBEDDING_URL")
    if clipURL == "" {
        clipURL = "http://localhost:8091"
    }

    payload := map[string]any{
        "text": query,
        "mode": "text",
    }
    b, _ := json.Marshal(payload)

    resp, err := http.Post(clipURL+"/embed", "application/json", bytes.NewReader(b))
    if err != nil {
        return nil, fmt.Errorf("CLIP embedding service request failed: %w", err)
    }
    defer resp.Body.Close()

    body, _ := io.ReadAll(resp.Body)
    if resp.StatusCode != 200 {
        return nil, fmt.Errorf("CLIP embedding service returned %d: %s", resp.StatusCode, string(body))
    }

    var result struct {
        Model        string    `json:"model"`
        EmbeddingDim int       `json:"embedding_dim"`
        Vector       []float32 `json:"vector"`
    }
    if err := json.Unmarshal(body, &result); err != nil {
        return nil, fmt.Errorf("failed to parse CLIP embedding response: %v", err)
    }
    if len(result.Vector) == 0 {
        return nil, fmt.Errorf("empty CLIP embedding returned")
    }
    return result.Vector, nil
}

// uploadFile accepts a raw PUT body and saves it to the videos directory.
// Used by process-movie.sh to stream a local video file to a RunPod pod
// (pods have no SSH; the HTTP API is the only upload path).
func uploadFile(c *gin.Context) {
    filename := filepath.Base(c.Param("filename"))
    videosDir := getEnvOrDefault("VIDEOS_PATH", "/data/videos")
    if err := os.MkdirAll(videosDir, 0755); err != nil {
        c.JSON(http.StatusInternalServerError, gin.H{"error": "cannot create directory", "details": err.Error()})
        return
    }
    fullPath := filepath.Join(videosDir, filename)
    f, err := os.Create(fullPath)
    if err != nil {
        c.JSON(http.StatusInternalServerError, gin.H{"error": "cannot create file", "details": err.Error()})
        return
    }
    defer f.Close()
    written, err := io.Copy(f, c.Request.Body)
    if err != nil {
        os.Remove(fullPath)
        c.JSON(http.StatusInternalServerError, gin.H{"error": "upload failed", "details": err.Error()})
        return
    }
    c.JSON(http.StatusOK, gin.H{"filename": filename, "bytes": written})
}

// serveFile serves a single file from the videos directory by name.
// Intended for process-movie.sh to pull generated files (SRT sidecars, etc.)
// from the RunPod instance over HTTP without needing SSH/scp.
//
// filepath.Base() on the parameter prevents path traversal — a request for
// "../../etc/passwd" is reduced to "passwd" and will 404 harmlessly.
func serveFile(c *gin.Context) {
    // Sanitise: strip any directory component from the URL parameter
    filename := filepath.Base(c.Param("filename"))
    videosDir := getEnvOrDefault("VIDEOS_PATH", "/data/videos")
    fullPath := filepath.Join(videosDir, filename)

    if _, err := os.Stat(fullPath); os.IsNotExist(err) {
        c.JSON(http.StatusNotFound, gin.H{"error": "file not found", "filename": filename})
        return
    }
    c.File(fullPath)
}

// streamLogs serves the pod's stdout log written by entrypoint.sh.
//
//   GET /api/v1/logs           — last 200 lines, plain text
//   GET /api/v1/logs?tail=500  — last 500 lines
//   GET /api/v1/logs?follow=true — stream new lines as they arrive (tail -f)
//
// The log file path is controlled by LOG_PATH (default /workspace/goodclips.log).
func streamLogs(c *gin.Context) {
    logPath := getEnvOrDefault("LOG_PATH", "/workspace/goodclips.log")

    tail := 200
    if t := c.Query("tail"); t != "" {
        if n, err := strconv.Atoi(t); err == nil && n > 0 {
            tail = n
        }
    }
    follow := c.Query("follow") == "true"

    f, err := os.Open(logPath)
    if err != nil {
        c.String(http.StatusNotFound, "log file not found: %s\n", logPath)
        return
    }
    defer f.Close()

    // Collect last `tail` lines efficiently using a circular line buffer
    var lines []string
    scanner := bufio.NewScanner(f)
    scanner.Buffer(make([]byte, 1024*1024), 1024*1024) // 1 MB line buffer
    for scanner.Scan() {
        lines = append(lines, scanner.Text())
        if len(lines) > tail {
            lines = lines[1:]
        }
    }

    c.Header("Content-Type", "text/plain; charset=utf-8")
    c.Header("X-Content-Type-Options", "nosniff")

    if !follow {
        c.String(http.StatusOK, "%s\n", strings.Join(lines, "\n"))
        return
    }

    // follow=true: stream the tail then keep sending new lines
    c.Stream(func(w io.Writer) bool {
        // Flush the buffered tail first
        if len(lines) > 0 {
            fmt.Fprintln(w, strings.Join(lines, "\n"))
            lines = nil
        }

        // Seek to end and poll for new content every second
        offset, _ := f.Seek(0, io.SeekCurrent)
        ticker := time.NewTicker(time.Second)
        defer ticker.Stop()

        for {
            select {
            case <-c.Request.Context().Done():
                return false
            case <-ticker.C:
                buf := make([]byte, 64*1024)
                n, _ := f.ReadAt(buf, offset)
                if n > 0 {
                    w.Write(buf[:n])
                    offset += int64(n)
                }
            }
        }
    })
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
        case queue.JobTypeClipGeneration:
            err = processClipGenerationJob(job)
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

func processClipGenerationJob(job *queue.Job) error {
    return videoProcessor.ProcessClipGeneration(job.Payload)
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
    embeddingURL := os.Getenv("EMBEDDING_SERVICE_URL")
    if embeddingURL == "" {
        embeddingURL = "http://localhost:8090"
    }

    payload := map[string]any{
        "text": query,
        "mode": "query",
    }
    b, _ := json.Marshal(payload)

    resp, err := http.Post(embeddingURL+"/embed", "application/json", bytes.NewReader(b))
    if err != nil {
        return nil, fmt.Errorf("embedding service request failed: %w", err)
    }
    defer resp.Body.Close()

    body, _ := io.ReadAll(resp.Body)
    if resp.StatusCode != 200 {
        return nil, fmt.Errorf("embedding service returned %d: %s", resp.StatusCode, string(body))
    }

    var result struct {
        Model        string    `json:"model"`
        EmbeddingDim int       `json:"embedding_dim"`
        Vector       []float32 `json:"vector"`
    }
    if err := json.Unmarshal(body, &result); err != nil {
        return nil, fmt.Errorf("failed to parse embedding response: %v; raw: %s", err, string(body))
    }
    if len(result.Vector) == 0 {
        return nil, fmt.Errorf("empty embedding returned")
    }
    return result.Vector, nil
}