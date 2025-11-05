package scenedetect

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"time"
)

// Scene represents a detected scene boundary
type Scene struct {
	Index     int     `json:"index"`
	StartTime float64 `json:"start_time"`
	EndTime   float64 `json:"end_time"`
}

// Detector handles scene detection operations
type Detector struct {
	pythonPath        string
	scenedetectScript string
}

// NewDetector creates a new scene detector instance
func NewDetector() *Detector {
    return &Detector{
        pythonPath:        "python3",
        scenedetectScript: "/root/internal/scenedetect/sd_runner.py",
    }
}

// DetectScenes detects scenes in a video file using PySceneDetect
func (d *Detector) DetectScenes(videoPath string) ([]Scene, error) {
    // Check if Python and required dependencies are available
    if err := d.CheckDependencies(); err != nil {
        return nil, fmt.Errorf("dependencies not available: %v", err)
    }

    // Create a context with timeout for scene detection (configurable, default 300s)
    detectTimeout := 300 * time.Second
    if v := os.Getenv("SCENEDETECT_TIMEOUT_SECS"); v != "" {
        if secs, err := strconv.Atoi(v); err == nil && secs > 0 {
            detectTimeout = time.Duration(secs) * time.Second
        }
    }
    ctx, cancel := context.WithTimeout(context.Background(), detectTimeout)
    defer cancel()

    // Run PySceneDetect script
    cmd := exec.CommandContext(ctx, d.pythonPath, d.scenedetectScript, videoPath)

    out, err := cmd.CombinedOutput()
    if err != nil {
        // Try to parse JSON error from the script output
        var result struct {
            Scenes []Scene `json:"scenes"`
            Count  int     `json:"count"`
            Error  string  `json:"error,omitempty"`
        }
        if json.Unmarshal(out, &result) == nil && result.Error != "" {
            return nil, fmt.Errorf("scene detection error: %s", result.Error)
        }
        return nil, fmt.Errorf("failed to run scene detection: %v; output: %s", err, string(out))
    }

    // Parse JSON output
    var result struct {
        Scenes []Scene `json:"scenes"`
        Count  int     `json:"count"`
        Error  string  `json:"error,omitempty"`
    }

    if err := json.Unmarshal(out, &result); err != nil {
        return nil, fmt.Errorf("failed to parse scene detection output: %v", err)
    }

    if result.Error != "" {
        return nil, fmt.Errorf("scene detection error: %s", result.Error)
    }

    log.Printf("Detected %d scenes in video", result.Count)
    return result.Scenes, nil
}

// CheckDependencies checks if Python, scenedetect script, and ffmpeg are available
func (d *Detector) CheckDependencies() error {
    // Check if python is available
    cmd := exec.Command(d.pythonPath, "--version")
    if err := cmd.Run(); err != nil {
        return fmt.Errorf("python not found: %v", err)
    }

    // Check if PySceneDetect script exists
    if _, err := os.Stat(d.scenedetectScript); os.IsNotExist(err) {
        return fmt.Errorf("scenedetect script not found: %s", d.scenedetectScript)
    }

    // Check if ffmpeg is available
    cmd = exec.Command("ffmpeg", "-version")
    if err := cmd.Run(); err != nil {
        return fmt.Errorf("ffmpeg not found: %v", err)
    }

    return nil
}

// ExtractKeyframes extracts keyframes for detected scenes
func (d *Detector) ExtractKeyframes(videoPath string, outputDir string, scenes []Scene) error {
    // Create keyframes directory
    if err := os.MkdirAll(outputDir, 0755); err != nil {
        return fmt.Errorf("failed to create keyframes directory: %v", err)
    }

    // Extract keyframes using ffmpeg directly
    for i, scene := range scenes {
        // Extract a keyframe from the middle of each scene
        midTime := (scene.StartTime + scene.EndTime) / 2.0

        outputPath := filepath.Join(outputDir, fmt.Sprintf("scene_%04d_keyframe.jpg", i))

        // Create a context with timeout for keyframe extraction (configurable, default 30s)
        keyframeTimeout := 30 * time.Second
        if v := os.Getenv("KEYFRAME_TIMEOUT_SECS"); v != "" {
            if secs, err := strconv.Atoi(v); err == nil && secs > 0 {
                keyframeTimeout = time.Duration(secs) * time.Second
            }
        }
        ctx, cancel := context.WithTimeout(context.Background(), keyframeTimeout)

        cmd := exec.CommandContext(ctx, "ffmpeg",
            "-ss", fmt.Sprintf("%.2f", midTime),
            "-i", videoPath,
            "-vframes", "1",
            "-q:v", "2",
            "-y",
            outputPath,
        )

        stderr, err := cmd.CombinedOutput()
        cancel() // ensure context is canceled
        if err != nil {
            log.Printf("Warning: Failed to extract keyframe for scene %d: %v\nOutput: %s", i, err, string(stderr))
            continue
        }

        log.Printf("Extracted keyframe for scene %d to %s", i, outputPath)
    }

    return nil
}