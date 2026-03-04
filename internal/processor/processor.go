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

    // Enqueue clip generation (runs after scenes + captions, detects clip boundaries)
    clipPayload := map[string]interface{}{
        "video_id": video.ID,
    }
    if _, err := vp.jobQueue.Enqueue(queue.JobTypeClipGeneration, clipPayload); err != nil {
        log.Printf("Warning: Failed to enqueue clip generation job for video %d: %v", video.ID, err)
    } else {
        log.Printf("Enqueued clip generation job for video ID %d", video.ID)
    }

    // Enqueue embedding generation (runs after clips, embeds clips not scenes)
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

    log.Printf("Processing scene detection for video ID %v: %s", videoID, filepathStr)

    // Verify the file is on disk before invoking PySceneDetect
    if info, statErr := os.Stat(filepathStr); os.IsNotExist(statErr) {
        return fmt.Errorf("video file not found: %s", filepathStr)
    } else if statErr != nil {
        return fmt.Errorf("failed to stat video file: %v", statErr)
    } else {
        log.Printf("Video file confirmed: %s (%.1f MB)", filepathStr, float64(info.Size())/1e6)
    }

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
	if len(scenes) == 0 {
		log.Printf("WARNING: 0 scenes detected in %s — check pod logs for PySceneDetect output", filepathStr)
	}
	
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

	// Check for a sidecar SRT alongside the video (e.g. generated by transcribe.py
	// before ingestion). Use it directly if present and non-empty — it has better
	// timestamp accuracy than FFmpeg's embedded subtitle extraction.
	ext := filepath.Ext(filepathStr)
	sidecarSRT := filepathStr[:len(filepathStr)-len(ext)] + ".srt"
	if si, err := os.Stat(sidecarSRT); err == nil && si.Size() > 0 {
		log.Printf("Using sidecar SRT for captions: %s", sidecarSRT)
		subtitlesPath = sidecarSRT
	} else {
		// No sidecar — try FFmpeg embedded subtitle extraction first.
		info, statErr := os.Stat(subtitlesPath)
		if os.IsNotExist(statErr) || (statErr == nil && info.Size() == 0) {
			if statErr == nil && info.Size() == 0 {
				log.Printf("Existing subtitles file %s is empty; re-extracting", subtitlesPath)
			}
			if err := vp.ffmpegClient.ExtractSubtitlesToSRT(filepathStr, subtitlesPath); err != nil {
				// No embedded subtitles — fall back to Whisper transcription.
				log.Printf("No embedded subtitles (%v); running Whisper transcription...", err)
				whisperModel := os.Getenv("WHISPER_MODEL")
				if whisperModel == "" {
					whisperModel = "large-v3"
				}
				cmd := exec.Command("python3", "/root/cloud-ingestion/transcribe.py",
					filepathStr,
					"--output", sidecarSRT,
					"--model", whisperModel,
					"--device", "cuda",
				)
				if out, wErr := cmd.CombinedOutput(); wErr != nil {
					log.Printf("Warning: Whisper transcription failed: %v\n%s", wErr, string(out))
					return nil
				}
				log.Printf("Whisper transcription complete: %s", sidecarSRT)
				subtitlesPath = sidecarSRT
			}
		} else if statErr != nil {
			log.Printf("Warning: Failed to stat subtitles file %s: %v", subtitlesPath, statErr)
			return nil
		}
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

// ProcessEmbeddingGeneration handles embedding generation jobs.
// Operates on clips — generates IV2 visual descriptions and computes
// all embeddings (InternVL, e5, CLIP ViT-B/32, CLAP) per clip.
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

    // Load video & clips
    video, err := vp.db.GetVideoByID(id)
    if err != nil {
        return fmt.Errorf("failed to get video: %v", err)
    }
    clips, err := vp.db.GetClipsByVideoID(video.ID)
    if err != nil {
        return fmt.Errorf("failed to load clips: %v", err)
    }
    if len(clips) == 0 {
        log.Printf("No clips for video %d; skipping embeddings.", video.ID)
        return nil
    }

    backend := os.Getenv("EMBEDDING_BACKEND")
    if backend == "" {
        backend = "iv2"
    }

    log.Printf("[embeddings] video_id=%d: starting embedding generation with backend=%s for %d clips", video.ID, backend, len(clips))

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

        // Build clip ranges — reuse "scene_index" JSON field for clip ID mapping
        type clipRange struct {
            SceneIndex int     `json:"scene_index"`
            Start      float64 `json:"start"`
            End        float64 `json:"end"`
        }
        var crs []clipRange
        for _, c := range clips {
            crs = append(crs, clipRange{SceneIndex: int(c.ID), Start: c.StartTime, End: c.EndTime})
        }

        req := map[string]interface{}{
            "video_path": video.Filepath,
            "scenes":     crs,
            "sampling": map[string]int{
                "frames":     frames,
                "stride":     stride,
                "resolution": res,
            },
            "device":   device,
            "model_id": modelID,
            "backend":  backend,
        }

        log.Printf("[embeddings] video_id=%d: starting IV2 visual embedding runner (backend=%s, model=%s)", video.ID, backend, modelID)

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

        log.Printf("Embedding runner (backend=%s) model=%s returned dim=%d for %d clips", backend, resp.Model, resp.EmbeddingDim, len(resp.Vectors))

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
            clipID := uint(v.SceneIndex)
            if err := vp.db.UpdateClipVisualEmbedding(clipID, v.Vector); err != nil {
                log.Printf("Failed to persist visual embedding for clip %d: %v", clipID, err)
                continue
            }
            saved++
        }
        // Update video's embedding model
        video.EmbeddingModel = resp.Model
        if err := vp.db.UpdateVideo(video); err != nil {
            log.Printf("Warning: failed to update video embedding_model: %v", err)
        }
        log.Printf("Persisted %d/%d visual embeddings for video %d", saved, len(resp.Vectors), video.ID)

        // --- IV2 caption generation for all clips ---
        log.Printf("[embeddings] video_id=%d: starting IV2 caption generation for %d clips", video.ID, len(clips))

        captionReq := map[string]interface{}{
            "video_path": video.Filepath,
            "scenes":     crs,
            "prompt":     os.Getenv("IV2_CAPTION_PROMPT"),
            "sampling": map[string]int{
                "frames":     frames,
                "stride":     stride,
                "resolution": res,
            },
            "device":   device,
            "model_id": modelID,
        }
        payloadBytes, _ = json.Marshal(captionReq)
        captionCmd := exec.Command("python3", "/root/internal/embeddings/iv2_caption_runner.py")
        captionCmd.Stdin = bytes.NewReader(payloadBytes)
        captionStdout, _ := captionCmd.StdoutPipe()
        captionStderr, _ := captionCmd.StderrPipe()
        if err := captionCmd.Start(); err != nil {
            log.Printf("Warning: failed to start iv2_caption_runner: %v", err)
        }
        // Stream stderr so per-clip progress logs appear in real time.
        go func() {
            if _, err := io.Copy(os.Stderr, captionStderr); err != nil {
                log.Printf("Warning: failed to read iv2_caption_runner stderr for video %d: %v", video.ID, err)
            }
        }()
        captionOut, _ := io.ReadAll(captionStdout)
        if err := captionCmd.Wait(); err != nil {
            log.Printf("Warning: iv2_caption_runner failed: %v", err)
        }

        var captionResp struct {
            Model    string `json:"model"`
            Captions []struct {
                SceneIndex int    `json:"scene_index"`
                Text       string `json:"text"`
            } `json:"captions"`
            Error string `json:"error"`
        }
        if err := json.Unmarshal(captionOut, &captionResp); err != nil {
            log.Printf("Warning: failed to parse iv2_caption_runner output: %v; raw: %s", err, string(captionOut))
        }
        if captionResp.Error != "" {
            log.Printf("Warning: iv2_caption_runner error: %s", captionResp.Error)
        }

        // Index clips by ID for quick lookup
        clipByID := make(map[uint]models.Clip, len(clips))
        for _, c := range clips {
            clipByID[c.ID] = c
        }

        // Store IV2 descriptions: update visual clip labels + collect all for text embedding
        iv2Descriptions := make(map[uint]string, len(captionResp.Captions))
        savedCaptions := 0
        for _, cap := range captionResp.Captions {
            text := strings.TrimSpace(cap.Text)
            if text == "" {
                continue
            }
            clipID := uint(cap.SceneIndex)
            iv2Descriptions[clipID] = text

            // Only update label for clips without dialog (dialog clips keep their spoken text)
            c, ok := clipByID[clipID]
            if ok && c.Label == "" {
                if err := vp.db.UpdateClipLabel(clipID, text); err != nil {
                    log.Printf("Warning: Failed to update label for clip %d: %v", clipID, err)
                    continue
                }
                savedCaptions++
            }
        }
        log.Printf("Persisted %d IV2 visual clip labels for video %d", savedCaptions, video.ID)
        log.Printf("[embeddings] video_id=%d: completed IV2 caption generation", video.ID)

        // --- Text embedding (e5) on IV2 descriptions → text_embedding ---
        var textClipIDs []uint
        var textDescs []string
        for _, c := range clips {
            if desc, ok := iv2Descriptions[c.ID]; ok && desc != "" {
                textClipIDs = append(textClipIDs, c.ID)
                textDescs = append(textDescs, desc)
            }
        }
        if len(textDescs) > 0 {
            treq := map[string]interface{}{
                "texts": textDescs,
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
            } else if len(tResp.Vector) > 0 && len(textDescs) == 1 {
                tVectors = [][]float32{tResp.Vector}
            }
            savedText := 0
            for i, clipID := range textClipIDs {
                if i >= len(tVectors) || len(tVectors[i]) == 0 {
                    continue
                }
                if err := vp.db.UpdateClipTextEmbedding(clipID, tVectors[i]); err != nil {
                    log.Printf("Failed to persist text embedding for clip %d: %v", clipID, err)
                    continue
                }
                savedText++
            }
            log.Printf("Persisted %d/%d text embeddings for video %d", savedText, len(textClipIDs), video.ID)
        }
        log.Printf("[embeddings] video_id=%d: completed text embedding stage", video.ID)

        // --- Dialog embedding (e5) on spoken text → dialog_embedding ---
        var dialogClipIDs []uint
        var dialogTexts []string
        for _, c := range clips {
            if c.Label != "" {
                dialogClipIDs = append(dialogClipIDs, c.ID)
                dialogTexts = append(dialogTexts, c.Label)
            }
        }
        if len(dialogTexts) > 0 {
            dreq := map[string]interface{}{
                "texts": dialogTexts,
                "mode":  "passage",
            }
            payloadBytes, _ = json.Marshal(dreq)
            dcmd := exec.Command("python3", "/root/internal/embeddings/text_embed_runner.py")
            dcmd.Stdin = bytes.NewReader(payloadBytes)
            dStdout, _ := dcmd.StdoutPipe()
            dStderr, _ := dcmd.StderrPipe()
            if err := dcmd.Start(); err != nil {
                log.Printf("Warning: failed to start text_embed_runner for dialog: %v", err)
                return nil
            }
            dOut, _ := io.ReadAll(dStdout)
            dErr, _ := io.ReadAll(dStderr)
            if err := dcmd.Wait(); err != nil {
                log.Printf("Warning: text_embed_runner (dialog) failed: %v; stderr: %s", err, string(dErr))
                return nil
            }
            var dResp struct {
                Model        string       `json:"model"`
                EmbeddingDim int          `json:"embedding_dim"`
                Vectors      [][]float32  `json:"vectors"`
                Vector       []float32    `json:"vector"`
                Error        string       `json:"error"`
            }
            if err := json.Unmarshal(dOut, &dResp); err != nil {
                log.Printf("Warning: failed to parse text_embed_runner (dialog) output: %v; raw: %s", err, string(dOut))
                return nil
            }
            if dResp.Error != "" {
                log.Printf("Warning: text_embed_runner (dialog) error: %s", dResp.Error)
                return nil
            }
            var dVectors [][]float32
            if len(dResp.Vectors) > 0 {
                dVectors = dResp.Vectors
            } else if len(dResp.Vector) > 0 && len(dialogTexts) == 1 {
                dVectors = [][]float32{dResp.Vector}
            }
            savedDialog := 0
            for i, clipID := range dialogClipIDs {
                if i >= len(dVectors) || len(dVectors[i]) == 0 {
                    continue
                }
                if err := vp.db.UpdateClipDialogEmbedding(clipID, dVectors[i]); err != nil {
                    log.Printf("Failed to persist dialog embedding for clip %d: %v", clipID, err)
                    continue
                }
                savedDialog++
            }
            log.Printf("Persisted %d/%d dialog embeddings for video %d", savedDialog, len(dialogClipIDs), video.ID)
        }
        log.Printf("[embeddings] video_id=%d: completed dialog embedding stage", video.ID)

        // --- CLIP image embeddings (ViT-B/32) ---
        log.Printf("[embeddings] video_id=%d: starting CLIP embedding stage for %d clips", video.ID, len(clips))
        creq := map[string]interface{}{
            "video_path": video.Filepath,
            "scenes":     crs,
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
            clipID := uint(v.SceneIndex)
            if err := vp.db.UpdateClipClipEmbedding(clipID, v.Vector); err != nil {
                log.Printf("Failed to persist CLIP embedding for clip %d: %v", clipID, err)
                continue
            }
            savedClip++
        }
        log.Printf("Persisted %d/%d CLIP embeddings for video %d", savedClip, len(cResp.Vectors), video.ID)
        log.Printf("[embeddings] video_id=%d: completed CLIP embedding stage (saved=%d/%d)", video.ID, savedClip, len(cResp.Vectors))

        // --- CLAP audio embeddings ---
        if strings.EqualFold(os.Getenv("ENABLE_AUDIO_EMBEDDINGS"), "false") || os.Getenv("ENABLE_AUDIO_EMBEDDINGS") == "0" {
            log.Printf("Skipping audio embeddings for video %d due to ENABLE_AUDIO_EMBEDDINGS", video.ID)
            return nil
        }
        areq := map[string]interface{}{
            "video_path":  video.Filepath,
            "scenes":      crs,
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
            clipID := uint(v.SceneIndex)
            if err := vp.db.UpdateClipAudioEmbedding(clipID, v.Vector); err != nil {
                log.Printf("Failed to persist audio embedding for clip %d: %v", clipID, err)
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

// ProcessClipGeneration runs Lighthouse on scenes to find salient clips,
// attaches overlapping dialog as labels, and persists clips to the database.
func (vp *VideoProcessor) ProcessClipGeneration(payload map[string]interface{}) error {
    videoID, ok := payload["video_id"]
    if !ok {
        return fmt.Errorf("missing video_id in payload")
    }
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
    scenes, err := vp.db.GetScenesByVideoID(video.ID)
    if err != nil {
        return fmt.Errorf("failed to load scenes: %v", err)
    }
    captions, err := vp.db.GetCaptionsByVideoID(video.ID)
    if err != nil {
        return fmt.Errorf("failed to load captions: %v", err)
    }

    log.Printf("[clips] video_id=%d: generating clips from %d scenes + %d captions", video.ID, len(scenes), len(captions))

    // Build payload for clip_generator.py
    type sceneData struct {
        ID        uint    `json:"id"`
        StartTime float64 `json:"start_time"`
        EndTime   float64 `json:"end_time"`
    }
    type captionData struct {
        ID         uint    `json:"id"`
        StartTime  float64 `json:"start_time"`
        EndTime    float64 `json:"end_time"`
        Text       string  `json:"text"`
        Language   string  `json:"language"`
        Confidence float64 `json:"confidence"`
    }

    var sd []sceneData
    for _, s := range scenes {
        sd = append(sd, sceneData{ID: s.ID, StartTime: s.StartTime, EndTime: s.EndTime})
    }
    var cd []captionData
    for _, c := range captions {
        cd = append(cd, captionData{
            ID: c.ID, StartTime: c.StartTime, EndTime: c.EndTime,
            Text: c.Text, Language: c.Language, Confidence: c.Confidence,
        })
    }

    device := os.Getenv("IV2_DEVICE")
    if device == "" {
        if os.Getenv("CUDA_VISIBLE_DEVICES") != "" {
            device = "cuda"
        } else {
            device = "cpu"
        }
    }

    req := map[string]interface{}{
        "video_id":       video.ID,
        "video_path":     video.Filepath,
        "video_duration": video.Duration,
        "scenes":         sd,
        "captions":       cd,
        "device":         device,
    }

    payloadBytes, _ := json.Marshal(req)
    cmd := exec.Command("python3", "/root/internal/clips/clip_generator.py")
    cmd.Stdin = bytes.NewReader(payloadBytes)
    stdout, _ := cmd.StdoutPipe()
    stderr, _ := cmd.StderrPipe()
    if err := cmd.Start(); err != nil {
        return fmt.Errorf("failed to start clip_generator: %v", err)
    }
    go func() {
        if _, err := io.Copy(os.Stderr, stderr); err != nil {
            log.Printf("Warning: failed to read clip_generator stderr: %v", err)
        }
    }()
    outBytes, _ := io.ReadAll(stdout)
    if err := cmd.Wait(); err != nil {
        return fmt.Errorf("clip_generator failed: %v; output: %s", err, string(outBytes))
    }

    var resp struct {
        VideoID    uint `json:"video_id"`
        ClipCount  int  `json:"clip_count"`
        WithDialog int  `json:"with_dialog"`
        Clips      []struct {
            ClipType        string  `json:"clip_type"`
            StartTime       float64 `json:"start_time"`
            EndTime         float64 `json:"end_time"`
            Label           string  `json:"label"`
            SalienceScore   float64 `json:"salience_score"`
            SourceSceneID   *uint   `json:"source_scene_id"`
            SourceCaptionID *uint   `json:"source_caption_id"`
        } `json:"clips"`
        Error string `json:"error"`
    }
    if err := json.Unmarshal(outBytes, &resp); err != nil {
        return fmt.Errorf("failed to parse clip_generator output: %v; raw: %s", err, string(outBytes))
    }
    if resp.Error != "" {
        return fmt.Errorf("clip_generator error: %s", resp.Error)
    }

    log.Printf("[clips] video_id=%d: clip_generator returned %d clips (%d with dialog)",
        video.ID, resp.ClipCount, resp.WithDialog)

    // Persist clips to database
    saved := 0
    for _, c := range resp.Clips {
        clip := &models.Clip{
            VideoID:         video.ID,
            ClipType:        c.ClipType,
            StartTime:       c.StartTime,
            EndTime:         c.EndTime,
            Label:           c.Label,
            SalienceScore:   c.SalienceScore,
            SourceSceneID:   c.SourceSceneID,
            SourceCaptionID: c.SourceCaptionID,
        }
        if err := vp.db.CreateClip(clip); err != nil {
            log.Printf("Warning: failed to store clip: %v", err)
            continue
        }
        saved++
    }
    log.Printf("[clips] video_id=%d: persisted %d/%d clips", video.ID, saved, len(resp.Clips))
    log.Printf("[clips] video_id=%d: clip generation complete (embeddings will run in embedding_generation job)", video.ID)
    return nil
}