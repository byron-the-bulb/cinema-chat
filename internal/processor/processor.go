package processor

import (
    "bytes"
    "encoding/json"
    "fmt"
    "io"
    "log"
    "os"
    "os/exec"
    "path/filepath"
    "strconv"
    "strings"

    "goodclips-server/internal/database"
    "goodclips-server/internal/ffmpeg"
    "goodclips-server/internal/models"
    "goodclips-server/internal/scenedetect"
    "goodclips-server/internal/queue"
)

// VideoProcessor handles video processing tasks
type VideoProcessor struct {
    db             *database.DB
    ffmpegClient   *ffmpeg.FFmpegClient
    sceneDetector  *scenedetect.Detector
    jobQueue       *queue.Queue
}

// NewVideoProcessor creates a new video processor instance
func NewVideoProcessor(db *database.DB, jobQueue *queue.Queue) *VideoProcessor {
    return &VideoProcessor{
        db:             db,
        ffmpegClient:   ffmpeg.NewFFmpegClient(),
        sceneDetector:  scenedetect.NewDetector(),
        jobQueue:       jobQueue,
    }
}

// ProcessVideoIngestion handles video ingestion jobs
func (vp *VideoProcessor) ProcessVideoIngestion(payload map[string]interface{}) error {
    videoID, ok := payload["video_id"]
    if !ok {
        return fmt.Errorf("missing video_id in payload")
    }

    filepathStr, ok := payload["filepath"].(string)
    if !ok {
        return fmt.Errorf("missing or invalid filepath in payload")
    }

    filename, ok := payload["filename"].(string)
    if !ok {
        return fmt.Errorf("missing or invalid filename in payload")
    }

    log.Printf("Processing video ingestion for video ID %v: %s", videoID, filename)

    // Check if FFmpeg is available
    if err := vp.ffmpegClient.CheckFFmpeg(); err != nil {
        log.Printf("Warning: FFmpeg not available: %v", err)
        // Continue processing but without FFmpeg features
        return vp.processVideoIngestionWithoutFFmpeg(videoID, filepathStr, filename)
    }

    // Get video metadata using FFmpeg
    metadata, err := vp.ffmpegClient.GetVideoMetadata(filepathStr)
    if err != nil {
        log.Printf("Warning: Failed to get video metadata with FFmpeg: %v", err)
        return vp.processVideoIngestionWithoutFFmpeg(videoID, filepathStr, filename)
    }

    // Update video with metadata
    duration := 0.0
    if metadata.Format.Duration != "" {
        // Try to parse duration from string if it's not empty
        if d, err := vp.ffmpegClient.GetVideoDuration(filepathStr); err == nil {
            duration = d
        }
    }

    // Update video record in database
    video, err := vp.db.GetVideoByID(uint(videoID.(float64)))
    if err != nil {
        return fmt.Errorf("failed to get video: %v", err)
    }

    video.Duration = duration
    video.Status = models.VideoStatusProcessing

    if err := vp.db.UpdateVideo(video); err != nil {
        return fmt.Errorf("failed to update video: %v", err)
    }

    log.Printf("Successfully processed video ingestion for video ID %v", videoID)

    // Create subsequent jobs for scene detection and caption extraction
    return vp.createSubsequentJobs(video)
}

// processVideoIngestionWithoutFFmpeg updates minimal metadata when FFmpeg isn't available
func (vp *VideoProcessor) processVideoIngestionWithoutFFmpeg(videoID interface{}, filepathStr, filename string) error {
    // Resolve numeric ID from JSON payload (float64)
    var id uint
    switch v := videoID.(type) {
    case float64:
        id = uint(v)
    case int:
        id = uint(v)
    case uint:
        id = v
    default:
        return fmt.Errorf("unsupported video_id type: %T", videoID)
    }

    video, err := vp.db.GetVideoByID(id)
    if err != nil {
        return fmt.Errorf("failed to get video: %v", err)
    }

    // Keep duration as-is (likely 0), mark as processing
    video.Status = models.VideoStatusProcessing

    if err := vp.db.UpdateVideo(video); err != nil {
        return fmt.Errorf("failed to update video without ffmpeg: %v", err)
    }

    log.Printf("Processed video ingestion without FFmpeg for video ID %d: %s", id, filename)
    return nil
}

// createSubsequentJobs creates jobs for scene detection and caption extraction
func (vp *VideoProcessor) createSubsequentJobs(video *models.Video) error {
    if vp.jobQueue == nil {
        log.Printf("Queue not available; skipping enqueue of follow-up jobs for video ID %d", video.ID)
        return nil
    }

    // Enqueue scene detection
    scenePayload := map[string]interface{}{
        "video_id": video.ID,
        "filename": video.Filename,
        "filepath": video.Filepath,
    }
    if _, err := vp.jobQueue.Enqueue(queue.JobTypeSceneDetection, scenePayload); err != nil {
        log.Printf("Warning: Failed to enqueue scene detection job for video %d: %v", video.ID, err)
    } else {
        log.Printf("Enqueued scene detection job for video ID %d", video.ID)
    }

    // Enqueue caption extraction
    captionPayload := map[string]interface{}{
        "video_id": video.ID,
        "filename": video.Filename,
        "filepath": video.Filepath,
    }
    if _, err := vp.jobQueue.Enqueue(queue.JobTypeCaptionExtraction, captionPayload); err != nil {
        log.Printf("Warning: Failed to enqueue caption extraction job for video %d: %v", video.ID, err)
    } else {
        log.Printf("Enqueued caption extraction job for video ID %d", video.ID)
    }

    // Optionally enqueue embedding generation after others
    embedPayload := map[string]interface{}{
        "video_id": video.ID,
    }
    if _, err := vp.jobQueue.Enqueue(queue.JobTypeEmbeddingGeneration, embedPayload); err != nil {
        log.Printf("Warning: Failed to enqueue embedding generation job for video %d: %v", video.ID, err)
    } else {
        log.Printf("Enqueued embedding generation job for video ID %d", video.ID)
    }

    return nil
}

// ProcessSceneDetection handles scene detection jobs
func (vp *VideoProcessor) ProcessSceneDetection(payload map[string]interface{}) error {
    videoID, ok := payload["video_id"]
    if !ok {
        return fmt.Errorf("missing video_id in payload")
    }
    filepathStr, ok := payload["filepath"].(string)
    if !ok {
        return fmt.Errorf("missing or invalid filepath in payload")
    }

    log.Printf("Processing scene detection for video ID %v", videoID)

    // Check if scene detection tools are available
	if err := vp.sceneDetector.CheckDependencies(); err != nil {
		log.Printf("Warning: Scene detection dependencies not available: %v", err)
		return fmt.Errorf("scene detection dependencies not available: %v", err)
	}
	
	// Detect scenes
	scenes, err := vp.sceneDetector.DetectScenes(filepathStr)
	if err != nil {
		return fmt.Errorf("failed to detect scenes: %v", err)
	}
	
	log.Printf("Detected %d scenes for video ID %v", len(scenes), videoID)
	
	// Update video scene count
	video, err := vp.db.GetVideoByID(uint(videoID.(float64)))
	if err != nil {
		return fmt.Errorf("failed to get video: %v", err)
	}
	
	video.SceneCount = len(scenes)
	if err := vp.db.UpdateVideo(video); err != nil {
		return fmt.Errorf("failed to update video scene count: %v", err)
	}
	
	// Store scenes in database
	for _, scene := range scenes {
		sceneModel := &models.Scene{
			VideoID:    video.ID,
			SceneIndex: scene.Index,
			StartTime:  scene.StartTime,
			EndTime:    scene.EndTime,
			Duration:   scene.EndTime - scene.StartTime,
		}
		
		if err := vp.db.CreateScene(sceneModel); err != nil {
			log.Printf("Warning: Failed to store scene: %v", err)
			continue
		}
	}
	
	// Extract keyframes for scenes
	dir := filepath.Dir(filepathStr)
	keyframesDir := filepath.Join(dir, fmt.Sprintf("video_%v_keyframes", videoID))
	
	// Create keyframes directory
	if err := os.MkdirAll(keyframesDir, 0755); err != nil {
		log.Printf("Warning: Failed to create keyframes directory: %v", err)
	} else {
		if err := vp.sceneDetector.ExtractKeyframes(filepathStr, keyframesDir, scenes); err != nil {
			log.Printf("Warning: Failed to extract keyframes: %v", err)
		}
	}
	
	return nil
}

// ProcessCaptionExtraction handles caption extraction jobs
func (vp *VideoProcessor) ProcessCaptionExtraction(payload map[string]interface{}) error {
	videoID, ok := payload["video_id"]
	if !ok {
		return fmt.Errorf("missing video_id in payload")
	}
	
	filepathStr, ok := payload["filepath"].(string)
	if !ok {
		return fmt.Errorf("missing or invalid filepath in payload")
	}
	
	log.Printf("Processing caption extraction for video ID %v", videoID)
	
	// Check if FFmpeg is available
	if err := vp.ffmpegClient.CheckFFmpeg(); err != nil {
		return fmt.Errorf("FFmpeg not available: %v", err)
	}
	
	// Create path for extracted subtitles
	dir := filepath.Dir(filepathStr)
	subtitlesPath := filepath.Join(dir, fmt.Sprintf("video_%v_subtitles.srt", videoID))
	
	// Try to extract subtitles
	err := vp.ffmpegClient.ExtractSubtitlesToSRT(filepathStr, subtitlesPath)
	if err != nil {
		log.Printf("Warning: Failed to extract subtitles: %v", err)
		// This is not a critical error, continue processing
		return nil
	}
	
	// Parse extracted subtitles
	subtitles, err := ffmpeg.ParseSRTFile(subtitlesPath)
	if err != nil {
		log.Printf("Warning: Failed to parse extracted subtitles: %v", err)
		return nil
	}
	
	// Store subtitles in database
	log.Printf("Successfully extracted %d subtitles for video ID %v", len(subtitles), videoID)
	
	// Update video caption count
	video, err := vp.db.GetVideoByID(uint(videoID.(float64)))
	if err != nil {
		return fmt.Errorf("failed to get video: %v", err)
	}
	
	video.CaptionCount = len(subtitles)
	if err := vp.db.UpdateVideo(video); err != nil {
		return fmt.Errorf("failed to update video caption count: %v", err)
	}
	
	// Store individual captions
	for _, subtitle := range subtitles {
		caption := &models.Caption{
			VideoID:    video.ID,
			StartTime:  subtitle.Start.Seconds(),
			EndTime:    subtitle.End.Seconds(),
			Text:       subtitle.Text,
			Language:   "en", // Default to English, could be detected
		}
		
		if err := vp.db.CreateCaption(caption); err != nil {
			log.Printf("Warning: Failed to store caption: %v", err)
			continue
		}
	}
	
	return nil
}

// ProcessEmbeddingGeneration handles embedding generation jobs
func (vp *VideoProcessor) ProcessEmbeddingGeneration(payload map[string]interface{}) error {
    videoID, ok := payload["video_id"]
    if !ok {
        return fmt.Errorf("missing video_id in payload")
    }

    // Resolve numeric ID from JSON payload (float64)
    var id uint
    switch v := videoID.(type) {
    case float64:
        id = uint(v)
    case int:
        id = uint(v)
    case uint:
        id = v
    default:
        return fmt.Errorf("unsupported video_id type: %T", videoID)
    }

    // Load video & scenes
    video, err := vp.db.GetVideoByID(id)
    if err != nil {
        return fmt.Errorf("failed to get video: %v", err)
    }
    scenes, err := vp.db.GetScenesByVideoID(video.ID)
    if err != nil {
        return fmt.Errorf("failed to load scenes: %v", err)
    }
    if len(scenes) == 0 {
        log.Printf("No scenes for video %d; skipping embeddings.", video.ID)
        return nil
    }

    backend := os.Getenv("EMBEDDING_BACKEND")
    if backend == "" {
        backend = "iv2"
    }

    switch backend {
    case "iv2", "internvl35":
        // Prepare IV2 runner input
        getIntEnv := func(key string, def int) int {
            if v := os.Getenv(key); v != "" {
                if n, err := strconv.Atoi(v); err == nil {
                    return n
                }
            }
            return def
        }

        // Defaults vary by backend
        defaultFrames := 16
        defaultRes := 224
        if backend == "internvl35" {
            defaultFrames = 8
            defaultRes = 448
        }
        frames := getIntEnv("IV2_FRAMES", defaultFrames)
        stride := getIntEnv("IV2_STRIDE", 4)
        res := getIntEnv("IV2_RES", defaultRes)
        device := os.Getenv("IV2_DEVICE")
        if device == "" {
            if os.Getenv("CUDA_VISIBLE_DEVICES") != "" {
                device = "cuda:0"
            } else {
                device = "cpu"
            }
        }
        modelID := os.Getenv("IV2_MODEL_ID")
        if modelID == "" {
            if backend == "internvl35" {
                modelID = "OpenGVLab/InternVL3_5-2B"
            } else {
                modelID = "OpenGVLab/InternVideo2-Stage2_1B-224p-f4"
            }
        }

        // Build scenes payload
        type sceneRange struct {
            SceneIndex int     `json:"scene_index"`
            Start      float64 `json:"start"`
            End        float64 `json:"end"`
        }
        var srs []sceneRange
        for _, s := range scenes {
            srs = append(srs, sceneRange{SceneIndex: s.SceneIndex, Start: s.StartTime, End: s.EndTime})
        }

        req := map[string]interface{}{
            "video_path": video.Filepath,
            "scenes":     srs,
            "sampling": map[string]int{
                "frames":     frames,
                "stride":     stride,
                "resolution": res,
            },
            "device":   device,
            "model_id": modelID,
            "backend":  backend,
        }

        payloadBytes, _ := json.Marshal(req)
        cmd := exec.Command("python3", "/root/internal/embeddings/iv2_runner.py")
        cmd.Stdin = bytes.NewReader(payloadBytes)
        stdout, _ := cmd.StdoutPipe()
        stderr, _ := cmd.StderrPipe()
        if err := cmd.Start(); err != nil {
            return fmt.Errorf("failed to start runner: %v", err)
        }
        outBytes, _ := io.ReadAll(stdout)
        errBytes, _ := io.ReadAll(stderr)
        if err := cmd.Wait(); err != nil {
            return fmt.Errorf("iv2 runner failed: %v; stderr: %s", err, string(errBytes))
        }
        out := outBytes

        var resp struct {
            Model        string `json:"model"`
            EmbeddingDim int    `json:"embedding_dim"`
            Vectors      []struct {
                SceneIndex int       `json:"scene_index"`
                Vector     []float32 `json:"vector"`
            } `json:"vectors"`
            Error string `json:"error"`
        }
        if err := json.Unmarshal(out, &resp); err != nil {
            return fmt.Errorf("failed to parse iv2 runner output: %v; raw: %s", err, string(out))
        }
        if resp.Error != "" {
            return fmt.Errorf("iv2 runner error: %s", resp.Error)
        }

        log.Printf("Embedding runner (backend=%s) model=%s returned dim=%d for %d scenes", backend, resp.Model, resp.EmbeddingDim, len(resp.Vectors))

        // Persist vectors only if embedding dim matches our schema
        expectedDim := 768
        if backend == "internvl35" {
            expectedDim = 1024
        }
        if resp.EmbeddingDim != expectedDim {
            log.Printf("Warning: embedding_dim=%d != %d; skipping persistence (update schema or backend)", resp.EmbeddingDim, expectedDim)
            return nil
        }

        saved := 0
        for _, v := range resp.Vectors {
            if err := vp.db.UpdateSceneVisualEmbeddingByIndex(video.ID, v.SceneIndex, v.Vector); err != nil {
                log.Printf("Failed to persist embedding for scene_index=%d: %v", v.SceneIndex, err)
                continue
            }
            saved++
        }
        // Update video's embedding model
        video.EmbeddingModel = resp.Model
        if err := vp.db.UpdateVideo(video); err != nil {
            log.Printf("Warning: failed to update video embedding_model: %v", err)
        }
        log.Printf("Persisted %d/%d scene embeddings for video %d", saved, len(resp.Vectors), video.ID)

        // --- Compute text embeddings for scenes from captions (e5-base-v2) ---
        captions, err := vp.db.GetCaptionsByVideoID(video.ID)
        if err != nil {
            log.Printf("Warning: failed to load captions for video %d: %v", video.ID, err)
            return nil
        }
        // Aggregate captions per scene time window
        texts := make([]string, len(scenes))
        hasText := make([]bool, len(scenes))
        for i, s := range scenes {
            var b strings.Builder
            for _, c := range captions {
                if c.StartTime < s.EndTime && c.EndTime > s.StartTime { // overlap
                    if b.Len() > 0 {
                        b.WriteString(" ")
                    }
                    b.WriteString(c.Text)
                }
            }
            txt := strings.TrimSpace(b.String())
            texts[i] = txt
            hasText[i] = txt != ""
        }
        // Prepare payload for runner with only non-empty texts, but we need ordering; simplest: send all and skip empty on persist
        treq := map[string]interface{}{
            "texts": texts,
            "mode":  "passage",
        }
        payloadBytes, _ = json.Marshal(treq)
        tcmd := exec.Command("python3", "/root/internal/embeddings/text_embed_runner.py")
        tcmd.Stdin = bytes.NewReader(payloadBytes)
        tStdout, _ := tcmd.StdoutPipe()
        tStderr, _ := tcmd.StderrPipe()
        if err := tcmd.Start(); err != nil {
            log.Printf("Warning: failed to start text_embed_runner: %v", err)
            return nil
        }
        tOut, _ := io.ReadAll(tStdout)
        tErr, _ := io.ReadAll(tStderr)
        if err := tcmd.Wait(); err != nil {
            log.Printf("Warning: text_embed_runner failed: %v; stderr: %s", err, string(tErr))
            return nil
        }
        var tResp struct {
            Model        string       `json:"model"`
            EmbeddingDim int          `json:"embedding_dim"`
            Vectors      [][]float32  `json:"vectors"`
            Vector       []float32    `json:"vector"`
            Error        string       `json:"error"`
        }
        if err := json.Unmarshal(tOut, &tResp); err != nil {
            log.Printf("Warning: failed to parse text_embed_runner output: %v; raw: %s", err, string(tOut))
            return nil
        }
        if tResp.Error != "" {
            log.Printf("Warning: text_embed_runner error: %s", tResp.Error)
            return nil
        }
        // Normalize single-vector vs vectors output
        var tVectors [][]float32
        if len(tResp.Vectors) > 0 {
            tVectors = tResp.Vectors
        } else if len(tResp.Vector) > 0 && len(texts) == 1 {
            tVectors = [][]float32{tResp.Vector}
        }
        // Persist per scene
        savedText := 0
        for i := range scenes {
            if !hasText[i] {
                continue
            }
            if i >= len(tVectors) || len(tVectors[i]) == 0 {
                continue
            }
            if err := vp.db.UpdateSceneTextEmbeddingByIndex(video.ID, scenes[i].SceneIndex, tVectors[i]); err != nil {
                log.Printf("Failed to persist text embedding for scene_index=%d: %v", scenes[i].SceneIndex, err)
                continue
            }
            savedText++
        }
        log.Printf("Persisted %d/%d text embeddings for video %d", savedText, len(scenes), video.ID)

        // --- Compute CLIP image embeddings for scenes (ViT-B/32) ---
        // Use the same scene ranges (srs) built earlier.
        creq := map[string]interface{}{
            "video_path": video.Filepath,
            "scenes":     srs,
            "mode":       "image",
        }
        payloadBytes, _ = json.Marshal(creq)
        ccmd := exec.Command("python3", "/root/internal/embeddings/clip_runner.py")
        ccmd.Stdin = bytes.NewReader(payloadBytes)
        cStdout, _ := ccmd.StdoutPipe()
        cStderr, _ := ccmd.StderrPipe()
        if err := ccmd.Start(); err != nil {
            log.Printf("Warning: failed to start clip_runner: %v", err)
            return nil
        }
        cOut, _ := io.ReadAll(cStdout)
        cErr, _ := io.ReadAll(cStderr)
        if err := ccmd.Wait(); err != nil {
            log.Printf("Warning: clip_runner failed: %v; stderr: %s", err, string(cErr))
            return nil
        }
        var cResp struct {
            Model        string `json:"model"`
            EmbeddingDim int    `json:"embedding_dim"`
            Vectors      []struct {
                SceneIndex int       `json:"scene_index"`
                Vector     []float32 `json:"vector"`
            } `json:"vectors"`
            Error string `json:"error"`
        }
        if err := json.Unmarshal(cOut, &cResp); err != nil {
            log.Printf("Warning: failed to parse clip_runner output: %v; raw: %s", err, string(cOut))
            return nil
        }
        if cResp.Error != "" {
            log.Printf("Warning: clip_runner error: %s", cResp.Error)
            return nil
        }
        if cResp.EmbeddingDim != 512 {
            log.Printf("Warning: CLIP embedding_dim=%d != 512; skipping persistence", cResp.EmbeddingDim)
            return nil
        }
        savedClip := 0
        for _, v := range cResp.Vectors {
            if err := vp.db.UpdateSceneVisualClipEmbeddingByIndex(video.ID, v.SceneIndex, v.Vector); err != nil {
                log.Printf("Failed to persist CLIP embedding for scene_index=%d: %v", v.SceneIndex, err)
                continue
            }
            savedClip++
        }
        log.Printf("Persisted %d/%d CLIP embeddings for video %d", savedClip, len(cResp.Vectors), video.ID)

        // --- Compute CLAP audio embeddings per scene ---
        areq := map[string]interface{}{
            "video_path": video.Filepath,
            "scenes":     srs,
            "sample_rate": 48000,
        }
        payloadBytes, _ = json.Marshal(areq)
        acmd := exec.Command("python3", "/root/internal/embeddings/audio_embed_runner.py")
        acmd.Stdin = bytes.NewReader(payloadBytes)
        aStdout, _ := acmd.StdoutPipe()
        aStderr, _ := acmd.StderrPipe()
        if err := acmd.Start(); err != nil {
            log.Printf("Warning: failed to start audio_embed_runner: %v", err)
            return nil
        }
        aOut, _ := io.ReadAll(aStdout)
        aErr, _ := io.ReadAll(aStderr)
        if err := acmd.Wait(); err != nil {
            log.Printf("Warning: audio_embed_runner failed: %v; stderr: %s", err, string(aErr))
            return nil
        }
        var aResp struct {
            Model        string `json:"model"`
            EmbeddingDim int    `json:"embedding_dim"`
            Vectors      []struct {
                SceneIndex int       `json:"scene_index"`
                Vector     []float32 `json:"vector"`
            } `json:"vectors"`
            Error string `json:"error"`
        }
        if err := json.Unmarshal(aOut, &aResp); err != nil {
            log.Printf("Warning: failed to parse audio_embed_runner output: %v; raw: %s", err, string(aOut))
            return nil
        }
        if aResp.Error != "" {
            log.Printf("Warning: audio_embed_runner error: %s", aResp.Error)
            return nil
        }
        if aResp.EmbeddingDim != 512 {
            log.Printf("Warning: CLAP embedding_dim=%d != 512; skipping persistence", aResp.EmbeddingDim)
            return nil
        }
        savedAudio := 0
        for _, v := range aResp.Vectors {
            if err := vp.db.UpdateSceneAudioEmbeddingByIndex(video.ID, v.SceneIndex, v.Vector); err != nil {
                log.Printf("Failed to persist audio embedding for scene_index=%d: %v", v.SceneIndex, err)
                continue
            }
            savedAudio++
        }
        log.Printf("Persisted %d/%d audio embeddings for video %d", savedAudio, len(aResp.Vectors), video.ID)

        return nil

    case "clip":
        log.Printf("CLIP embedding backend not implemented yet; skipping.")
        return nil

    default:
        return fmt.Errorf("unknown EMBEDDING_BACKEND: %s", backend)
    }
}