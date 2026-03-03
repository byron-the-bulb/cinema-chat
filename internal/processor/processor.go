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
// Operates on CLIPS (not scenes) — generates IV2 captions for visual clips,
// then computes all embeddings (InternVL, e5, CLIP ViT-B/32, CLAP) for each clip.
func (vp *VideoProcessor) ProcessEmbeddingGeneration(payload map[string]interface{}) error {
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

    clips, err := vp.db.GetClipsByVideoID(video.ID)
    if err != nil {
        return fmt.Errorf("failed to load clips: %v", err)
    }
    if len(clips) == 0 {
        log.Printf("[embeddings] video_id=%d: no clips to embed", video.ID)
        return nil
    }

    backend := os.Getenv("EMBEDDING_BACKEND")
    if backend == "" {
        backend = "iv2"
    }

    log.Printf("[embeddings] video_id=%d: starting clip embedding generation with backend=%s for %d clips", video.ID, backend, len(clips))

    // --- Shared config ---
    getIntEnv := func(key string, def int) int {
        if v := os.Getenv(key); v != "" {
            if n, err := strconv.Atoi(v); err == nil {
                return n
            }
        }
        return def
    }

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

    // Build clip ranges — use clip.ID as scene_index for mapping back
    type clipRange struct {
        SceneIndex int     `json:"scene_index"`
        Start      float64 `json:"start"`
        End        float64 `json:"end"`
    }
    var allClipRanges []clipRange
    for _, c := range clips {
        allClipRanges = append(allClipRanges, clipRange{
            SceneIndex: int(c.ID),
            Start:      c.StartTime,
            End:        c.EndTime,
        })
    }

    // Separate visual and dialog clips
    var visualClips []models.Clip
    var visualClipRanges []clipRange
    var dialogClips []models.Clip
    var dialogTexts []string
    for _, c := range clips {
        if c.ClipType == "visual" {
            visualClips = append(visualClips, c)
            visualClipRanges = append(visualClipRanges, clipRange{
                SceneIndex: int(c.ID), Start: c.StartTime, End: c.EndTime,
            })
        } else if c.ClipType == "dialog" && c.Label != "" {
            dialogClips = append(dialogClips, c)
            dialogTexts = append(dialogTexts, c.Label)
        }
    }

    // --- 1. IV2 captioning on visual clips (generates label text) ---
    if len(visualClips) > 0 {
        log.Printf("[embeddings] video_id=%d: generating IV2 captions for %d visual clips (backend=%s, model=%s)",
            video.ID, len(visualClips), backend, modelID)

        captionReq := map[string]interface{}{
            "video_path": video.Filepath,
            "scenes":     visualClipRanges,
            "prompt":     os.Getenv("IV2_CAPTION_PROMPT"),
            "sampling": map[string]int{
                "frames":     frames,
                "stride":     stride,
                "resolution": res,
            },
            "device":   device,
            "model_id": modelID,
        }
        captionPayload, _ := json.Marshal(captionReq)
        captionCmd := exec.Command("python3", "/root/internal/embeddings/iv2_caption_runner.py")
        captionCmd.Stdin = bytes.NewReader(captionPayload)
        captionStdout, _ := captionCmd.StdoutPipe()
        captionStderr, _ := captionCmd.StderrPipe()
        if err := captionCmd.Start(); err != nil {
            log.Printf("Warning: failed to start iv2_caption_runner for clips: %v", err)
        } else {
            go func() {
                if _, err := io.Copy(os.Stderr, captionStderr); err != nil {
                    log.Printf("Warning: failed to read iv2_caption_runner stderr: %v", err)
                }
            }()
            captionOut, _ := io.ReadAll(captionStdout)
            if err := captionCmd.Wait(); err != nil {
                log.Printf("Warning: iv2_caption_runner (clips) failed: %v", err)
            } else {
                var captionResp struct {
                    Model    string `json:"model"`
                    Captions []struct {
                        SceneIndex int    `json:"scene_index"`
                        Text       string `json:"text"`
                    } `json:"captions"`
                    Error string `json:"error"`
                }
                if err := json.Unmarshal(captionOut, &captionResp); err != nil {
                    log.Printf("Warning: failed to parse iv2_caption_runner output: %v", err)
                } else if captionResp.Error != "" {
                    log.Printf("Warning: iv2_caption_runner error: %s", captionResp.Error)
                } else {
                    savedCaptions := 0
                    for _, cap := range captionResp.Captions {
                        text := strings.TrimSpace(cap.Text)
                        if text == "" {
                            continue
                        }
                        clipID := uint(cap.SceneIndex) // we used clip.ID as scene_index
                        if err := vp.db.UpdateClipLabel(clipID, text); err != nil {
                            log.Printf("Warning: failed to update label for clip %d: %v", clipID, err)
                            continue
                        }
                        savedCaptions++
                    }
                    log.Printf("[embeddings] video_id=%d: persisted %d/%d IV2 captions for visual clips",
                        video.ID, savedCaptions, len(captionResp.Captions))

                    // Reload clips to get updated labels for text embedding
                    clips, err = vp.db.GetClipsByVideoID(video.ID)
                    if err != nil {
                        log.Printf("Warning: failed to reload clips after IV2 captioning: %v", err)
                    } else {
                        // Rebuild visual clip lists with updated labels
                        visualClips = nil
                        var visualTexts []string
                        for _, c := range clips {
                            if c.ClipType == "visual" && c.Label != "" {
                                visualClips = append(visualClips, c)
                                visualTexts = append(visualTexts, c.Label)
                            }
                        }

                        // --- 2. Text embedding (e5) on visual clip labels → text_embedding ---
                        if len(visualTexts) > 0 {
                            log.Printf("[embeddings] video_id=%d: computing text embeddings for %d visual clip labels",
                                video.ID, len(visualTexts))
                            vp.embedTextsToClips(video.ID, visualTexts, visualClips, "text_embedding")
                        }
                    }
                }
            }
        }
    }

    // --- 3. Dialog embedding (e5) on dialog clip labels → dialog_embedding ---
    if len(dialogTexts) > 0 {
        log.Printf("[embeddings] video_id=%d: computing dialog embeddings for %d dialog clips", video.ID, len(dialogTexts))
        vp.embedTextsToClips(video.ID, dialogTexts, dialogClips, "dialog_embedding")
    }

    // --- 4. InternVL visual embedding on ALL clips → visual_embedding ---
    if backend == "iv2" || backend == "internvl35" {
        log.Printf("[embeddings] video_id=%d: starting InternVL visual embedding for %d clips (model=%s)",
            video.ID, len(clips), modelID)

        ivReq := map[string]interface{}{
            "video_path": video.Filepath,
            "scenes":     allClipRanges,
            "sampling": map[string]int{
                "frames":     frames,
                "stride":     stride,
                "resolution": res,
            },
            "device":   device,
            "model_id": modelID,
            "backend":  backend,
        }
        ivPayload, _ := json.Marshal(ivReq)
        ivCmd := exec.Command("python3", "/root/internal/embeddings/iv2_runner.py")
        ivCmd.Stdin = bytes.NewReader(ivPayload)
        ivStdout, _ := ivCmd.StdoutPipe()
        ivStderr, _ := ivCmd.StderrPipe()
        if err := ivCmd.Start(); err != nil {
            log.Printf("Warning: failed to start iv2_runner for clips: %v", err)
        } else {
            ivOut, _ := io.ReadAll(ivStdout)
            ivErrBytes, _ := io.ReadAll(ivStderr)
            if err := ivCmd.Wait(); err != nil {
                log.Printf("Warning: iv2_runner (clips) failed: %v; stderr: %s", err, string(ivErrBytes))
            } else {
                var ivResp struct {
                    Model        string `json:"model"`
                    EmbeddingDim int    `json:"embedding_dim"`
                    Vectors      []struct {
                        SceneIndex int       `json:"scene_index"`
                        Vector     []float32 `json:"vector"`
                    } `json:"vectors"`
                    Error string `json:"error"`
                }
                if err := json.Unmarshal(ivOut, &ivResp); err != nil {
                    log.Printf("Warning: failed to parse iv2_runner (clips) output: %v", err)
                } else if ivResp.Error != "" {
                    log.Printf("Warning: iv2_runner (clips) error: %s", ivResp.Error)
                } else {
                    expectedDim := 768
                    if backend == "internvl35" {
                        expectedDim = 1024
                    }
                    if ivResp.EmbeddingDim != expectedDim {
                        log.Printf("Warning: IV2 embedding_dim=%d != %d; skipping", ivResp.EmbeddingDim, expectedDim)
                    } else {
                        savedIV := 0
                        for _, v := range ivResp.Vectors {
                            clipID := uint(v.SceneIndex)
                            if err := vp.db.UpdateClipVisualEmbedding(clipID, v.Vector); err != nil {
                                log.Printf("Warning: failed to persist visual embedding for clip %d: %v", clipID, err)
                                continue
                            }
                            savedIV++
                        }
                        log.Printf("[embeddings] video_id=%d: persisted %d/%d InternVL visual embeddings",
                            video.ID, savedIV, len(ivResp.Vectors))

                        // Update video's embedding model
                        video.EmbeddingModel = ivResp.Model
                        if err := vp.db.UpdateVideo(video); err != nil {
                            log.Printf("Warning: failed to update video embedding_model: %v", err)
                        }
                    }
                }
            }
        }
    }

    // --- 5. CLIP image embedding (ViT-B/32) on ALL clips → clip_embedding ---
    log.Printf("[embeddings] video_id=%d: computing CLIP image embeddings for %d clips", video.ID, len(clips))
    clipReq := map[string]interface{}{
        "video_path": video.Filepath,
        "scenes":     allClipRanges,
        "mode":       "image",
    }
    clipPayload, _ := json.Marshal(clipReq)
    clipCmd := exec.Command("python3", "/root/internal/embeddings/clip_runner.py")
    clipCmd.Stdin = bytes.NewReader(clipPayload)
    clipStdout, _ := clipCmd.StdoutPipe()
    clipStderr, _ := clipCmd.StderrPipe()
    if err := clipCmd.Start(); err != nil {
        log.Printf("Warning: failed to start clip_runner for clips: %v", err)
    } else {
        clipOut, _ := io.ReadAll(clipStdout)
        clipErrBytes, _ := io.ReadAll(clipStderr)
        if err := clipCmd.Wait(); err != nil {
            log.Printf("Warning: clip_runner (clips) failed: %v; stderr: %s", err, string(clipErrBytes))
        } else {
            var clipResp struct {
                EmbeddingDim int `json:"embedding_dim"`
                Vectors      []struct {
                    SceneIndex int       `json:"scene_index"`
                    Vector     []float32 `json:"vector"`
                } `json:"vectors"`
                Error string `json:"error"`
            }
            if err := json.Unmarshal(clipOut, &clipResp); err != nil {
                log.Printf("Warning: failed to parse clip_runner output: %v", err)
            } else if clipResp.Error != "" {
                log.Printf("Warning: clip_runner error: %s", clipResp.Error)
            } else if clipResp.EmbeddingDim != 512 {
                log.Printf("Warning: CLIP embedding_dim=%d != 512; skipping", clipResp.EmbeddingDim)
            } else {
                savedCE := 0
                for _, v := range clipResp.Vectors {
                    clipID := uint(v.SceneIndex)
                    if err := vp.db.UpdateClipClipEmbedding(clipID, v.Vector); err != nil {
                        log.Printf("Warning: failed to persist CLIP embedding for clip %d: %v", clipID, err)
                        continue
                    }
                    savedCE++
                }
                log.Printf("[embeddings] video_id=%d: persisted %d/%d CLIP embeddings", video.ID, savedCE, len(clipResp.Vectors))
            }
        }
    }

    // --- 6. CLAP audio embedding on ALL clips → audio_embedding ---
    if !(strings.EqualFold(os.Getenv("ENABLE_AUDIO_EMBEDDINGS"), "false") || os.Getenv("ENABLE_AUDIO_EMBEDDINGS") == "0") {
        log.Printf("[embeddings] video_id=%d: computing audio embeddings for %d clips", video.ID, len(clips))
        audioReq := map[string]interface{}{
            "video_path":  video.Filepath,
            "scenes":      allClipRanges,
            "sample_rate": 48000,
        }
        audioPayload, _ := json.Marshal(audioReq)
        audioCmd := exec.Command("python3", "/root/internal/embeddings/audio_embed_runner.py")
        audioCmd.Stdin = bytes.NewReader(audioPayload)
        audioStdout, _ := audioCmd.StdoutPipe()
        audioStderr, _ := audioCmd.StderrPipe()
        if err := audioCmd.Start(); err != nil {
            log.Printf("Warning: failed to start audio_embed_runner for clips: %v", err)
        } else {
            audioOut, _ := io.ReadAll(audioStdout)
            audioErrBytes, _ := io.ReadAll(audioStderr)
            if err := audioCmd.Wait(); err != nil {
                log.Printf("Warning: audio_embed_runner (clips) failed: %v; stderr: %s", err, string(audioErrBytes))
            } else {
                var audioResp struct {
                    EmbeddingDim int `json:"embedding_dim"`
                    Vectors      []struct {
                        SceneIndex int       `json:"scene_index"`
                        Vector     []float32 `json:"vector"`
                    } `json:"vectors"`
                    Error string `json:"error"`
                }
                if err := json.Unmarshal(audioOut, &audioResp); err != nil {
                    log.Printf("Warning: failed to parse audio_embed_runner output: %v", err)
                } else if audioResp.Error != "" {
                    log.Printf("Warning: audio_embed_runner error: %s", audioResp.Error)
                } else if audioResp.EmbeddingDim != 512 {
                    log.Printf("Warning: CLAP embedding_dim=%d != 512; skipping", audioResp.EmbeddingDim)
                } else {
                    savedAudio := 0
                    for _, v := range audioResp.Vectors {
                        clipID := uint(v.SceneIndex)
                        if err := vp.db.UpdateClipAudioEmbedding(clipID, v.Vector); err != nil {
                            log.Printf("Warning: failed to persist audio embedding for clip %d: %v", clipID, err)
                            continue
                        }
                        savedAudio++
                    }
                    log.Printf("[embeddings] video_id=%d: persisted %d/%d audio embeddings", video.ID, savedAudio, len(audioResp.Vectors))
                }
            }
        }
    } else {
        log.Printf("[embeddings] video_id=%d: skipping audio embeddings (disabled)", video.ID)
    }

    log.Printf("[embeddings] video_id=%d: clip embedding generation complete", video.ID)
    return nil
}

// embedTextsToClips runs text_embed_runner.py on a list of texts and persists to the specified embedding column.
func (vp *VideoProcessor) embedTextsToClips(videoID uint, texts []string, targetClips []models.Clip, embeddingType string) {
    treq := map[string]interface{}{
        "texts": texts,
        "mode":  "passage",
    }
    tPayload, _ := json.Marshal(treq)
    tcmd := exec.Command("python3", "/root/internal/embeddings/text_embed_runner.py")
    tcmd.Stdin = bytes.NewReader(tPayload)
    tStdout, _ := tcmd.StdoutPipe()
    tStderr, _ := tcmd.StderrPipe()
    if err := tcmd.Start(); err != nil {
        log.Printf("Warning: failed to start text_embed_runner for %s: %v", embeddingType, err)
        return
    }
    tOut, _ := io.ReadAll(tStdout)
    tErrBytes, _ := io.ReadAll(tStderr)
    if err := tcmd.Wait(); err != nil {
        log.Printf("Warning: text_embed_runner (%s) failed: %v; stderr: %s", embeddingType, err, string(tErrBytes))
        return
    }

    var tResp struct {
        Vectors [][]float32 `json:"vectors"`
        Vector  []float32   `json:"vector"`
        Error   string      `json:"error"`
    }
    if err := json.Unmarshal(tOut, &tResp); err != nil {
        log.Printf("Warning: failed to parse text_embed_runner (%s) output: %v", embeddingType, err)
        return
    }
    if tResp.Error != "" {
        log.Printf("Warning: text_embed_runner (%s) error: %s", embeddingType, tResp.Error)
        return
    }

    var tVectors [][]float32
    if len(tResp.Vectors) > 0 {
        tVectors = tResp.Vectors
    } else if len(tResp.Vector) > 0 && len(texts) == 1 {
        tVectors = [][]float32{tResp.Vector}
    }

    saved := 0
    for i, c := range targetClips {
        if i >= len(tVectors) || len(tVectors[i]) == 0 {
            continue
        }
        var err error
        switch embeddingType {
        case "dialog_embedding":
            err = vp.db.UpdateClipDialogEmbedding(c.ID, tVectors[i])
        case "text_embedding":
            err = vp.db.UpdateClipTextEmbedding(c.ID, tVectors[i])
        }
        if err != nil {
            log.Printf("Warning: failed to persist %s for clip %d: %v", embeddingType, c.ID, err)
            continue
        }
        saved++
    }
    log.Printf("[embeddings] video_id=%d: persisted %d/%d %s embeddings", videoID, saved, len(targetClips), embeddingType)
}

// generateIV2Captions generates one synthetic caption per scene using an external runner
// and stores them as Caption rows with language "iv2". These captions will be picked up
// by the existing text-embedding pipeline when aggregating per-scene text.
func (vp *VideoProcessor) generateIV2Captions(video *models.Video, scenes []models.Scene, frames, stride, res int, device, modelID string) error {
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
        "prompt":     os.Getenv("IV2_CAPTION_PROMPT"),
        "sampling": map[string]int{
            "frames":     frames,
            "stride":     stride,
            "resolution": res,
        },
        "device":   device,
        "model_id": modelID,
    }

    payloadBytes, _ := json.Marshal(req)
    cmd := exec.Command("python3", "/root/internal/embeddings/iv2_caption_runner.py")
    cmd.Stdin = bytes.NewReader(payloadBytes)
    stdout, _ := cmd.StdoutPipe()
    stderr, _ := cmd.StderrPipe()
    if err := cmd.Start(); err != nil {
        return fmt.Errorf("failed to start iv2_caption_runner: %v", err)
    }
    // Stream stderr so per-scene progress logs from the Python runner appear in real time.
    go func() {
        if _, err := io.Copy(os.Stderr, stderr); err != nil {
            log.Printf("Warning: failed to read iv2_caption_runner stderr for video %d: %v", video.ID, err)
        }
    }()
    outBytes, _ := io.ReadAll(stdout)
    if err := cmd.Wait(); err != nil {
        return fmt.Errorf("iv2_caption_runner failed: %v", err)
    }

    var resp struct {
        Model    string `json:"model"`
        Captions []struct {
            SceneIndex int    `json:"scene_index"`
            Text       string `json:"text"`
        } `json:"captions"`
        Error string `json:"error"`
    }
    if err := json.Unmarshal(outBytes, &resp); err != nil {
        return fmt.Errorf("failed to parse iv2_caption_runner output: %v; raw: %s", err, string(outBytes))
    }
    if resp.Error != "" {
        return fmt.Errorf("iv2_caption_runner error: %s", resp.Error)
    }

    // Index scenes by scene_index for quick lookup of timing
    sceneByIndex := make(map[int]models.Scene, len(scenes))
    for _, s := range scenes {
        sceneByIndex[s.SceneIndex] = s
    }

    saved := 0
    for _, c := range resp.Captions {
        if strings.TrimSpace(c.Text) == "" {
            continue
        }
        s, ok := sceneByIndex[c.SceneIndex]
        if !ok {
            continue
        }
        cap := &models.Caption{
            VideoID:   video.ID,
            SceneID:   &s.ID,
            StartTime: s.StartTime,
            EndTime:   s.EndTime,
            Text:      c.Text,
            Language:  "iv2",
        }
        if err := vp.db.CreateCaption(cap); err != nil {
            log.Printf("Warning: Failed to store IV2 caption for scene_index=%d: %v", c.SceneIndex, err)
            continue
        }
        saved++
    }
    log.Printf("Persisted %d/%d IV2 captions for video %d", saved, len(resp.Captions), video.ID)
    return nil
}

// ProcessClipGeneration creates dialog + visual clips from existing scenes and captions,
// then computes embeddings for each clip using the existing embedding runners.
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
        VideoID      uint `json:"video_id"`
        DialogCount  int  `json:"dialog_count"`
        VisualCount  int  `json:"visual_count"`
        Clips        []struct {
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

    log.Printf("[clips] video_id=%d: clip_generator returned %d dialog + %d visual clips",
        video.ID, resp.DialogCount, resp.VisualCount)

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