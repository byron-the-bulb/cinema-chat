package ffmpeg

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os/exec"
	"strconv"
	"strings"
)

// VideoMetadata represents basic video metadata
type VideoMetadata struct {
	Duration    string  `json:"duration"`
	BitRate     string  `json:"bit_rate"`
	FormatName  string  `json:"format_name"`
	FormatLongName string  `json:"format_long_name"`
	StartTime   string  `json:"start_time"`
	Size        string  `json:"size"`
}

// Stream represents a video/audio stream
type Stream struct {
	Index          int     `json:"index"`
	CodecName      string  `json:"codec_name"`
	CodecLongName  string  `json:"codec_long_name"`
	CodecType      string  `json:"codec_type"`
	Width          int     `json:"width,omitempty"`
	Height         int     `json:"height,omitempty"`
	SampleRate     string  `json:"sample_rate,omitempty"`
	Duration       string  `json:"duration"`
	BitRate        string  `json:"bit_rate"`
	AvgFrameRate   string  `json:"avg_frame_rate,omitempty"`
	Tags           map[string]string `json:"tags,omitempty"`
}

// FFprobeResult represents the result of ffprobe
type FFprobeResult struct {
	Streams   []Stream      `json:"streams"`
	Format    VideoMetadata `json:"format"`
}

// FFmpegClient handles FFmpeg operations
type FFmpegClient struct {
	ffprobePath string
	ffmpegPath  string
}

// NewFFmpegClient creates a new FFmpeg client
func NewFFmpegClient() *FFmpegClient {
	return &FFmpegClient{
		ffprobePath: "ffprobe",
		ffmpegPath:  "ffmpeg",
	}
}

// GetVideoMetadata extracts metadata from a video file
func (f *FFmpegClient) GetVideoMetadata(videoPath string) (*FFprobeResult, error) {
	// Build ffprobe command to get JSON metadata
	cmd := exec.Command(f.ffprobePath,
		"-v", "quiet",
		"-print_format", "json",
		"-show_format",
		"-show_streams",
		videoPath)

	var out bytes.Buffer
	var stderr bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &stderr

	err := cmd.Run()
	if err != nil {
		return nil, fmt.Errorf("ffprobe failed: %v, stderr: %s", err, stderr.String())
	}

	// Parse JSON output
	var result FFprobeResult
	err = json.Unmarshal(out.Bytes(), &result)
	if err != nil {
		return nil, fmt.Errorf("failed to parse ffprobe output: %v", err)
	}

	return &result, nil
}

// GetVideoDuration extracts just the duration from a video file
func (f *FFmpegClient) GetVideoDuration(videoPath string) (float64, error) {
	cmd := exec.Command(f.ffprobePath,
		"-v", "quiet",
		"-show_entries", "format=duration",
		"-of", "default=noprint_wrappers=1:nokey=1",
		videoPath)

	var out bytes.Buffer
	var stderr bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &stderr

	err := cmd.Run()
	if err != nil {
		return 0, fmt.Errorf("ffprobe failed: %v, stderr: %s", err, stderr.String())
	}

	durationStr := strings.TrimSpace(out.String())
	duration, err := strconv.ParseFloat(durationStr, 64)
	if err != nil {
		return 0, fmt.Errorf("failed to parse duration: %v", err)
	}

	return duration, nil
}

// ExtractSubtitles extracts subtitles from a video file
func (f *FFmpegClient) ExtractSubtitles(videoPath, outputPath string) error {
	// First, check if there are subtitle streams
	metadata, err := f.GetVideoMetadata(videoPath)
	if err != nil {
		return fmt.Errorf("failed to get video metadata: %v", err)
	}

	// Look for subtitle streams
	subtitleStreams := []int{}
	for _, stream := range metadata.Streams {
		if stream.CodecType == "subtitle" {
			subtitleStreams = append(subtitleStreams, stream.Index)
		}
	}

	if len(subtitleStreams) == 0 {
		return fmt.Errorf("no subtitle streams found in video")
	}

	// Extract the first subtitle stream
	cmd := exec.Command(f.ffmpegPath,
		"-i", videoPath,
		"-map", fmt.Sprintf("0:s:%d", subtitleStreams[0]),
		"-c:s", "srt",
		outputPath)

	var out bytes.Buffer
	var stderr bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &stderr

	err = cmd.Run()
	if err != nil {
		return fmt.Errorf("ffmpeg failed to extract subtitles: %v, stderr: %s", err, stderr.String())
	}

	return nil
}

// ExtractSubtitlesToSRT extracts subtitles and converts to SRT format
func (f *FFmpegClient) ExtractSubtitlesToSRT(videoPath, outputPath string) error {
	// Use ffprobe metadata to choose the best English text subtitle stream.
	meta, err := f.GetVideoMetadata(videoPath)
	if err != nil {
		return fmt.Errorf("failed to get video metadata for subtitles: %v", err)
	}

	type subInfo struct {
		idx   int
		codec string
		lang  string
	}
	var subs []subInfo
	for _, s := range meta.Streams {
		if s.CodecType != "subtitle" {
			continue
		}
		lang := ""
		if s.Tags != nil {
			if v, ok := s.Tags["language"]; ok {
				lang = v
			} else if v, ok := s.Tags["LANGUAGE"]; ok {
				lang = v
			}
		}
		subs = append(subs, subInfo{
			idx:   len(subs), // index among subtitle streams
			codec: s.CodecName,
			lang:  lang,
		})
	}
	if len(subs) == 0 {
		return fmt.Errorf("no subtitle streams found in video")
	}

	// Prefer English SubRip > English other > first subtitle.
	bestIdx := 0
	hasEnglish := false
	bestEnglishIdx := -1
	bestEnglishIsSubrip := false
	for i, s := range subs {
		l := strings.ToLower(s.lang)
		if l == "eng" || l == "en" {
			if !hasEnglish || (!bestEnglishIsSubrip && s.codec == "subrip") {
				hasEnglish = true
				bestEnglishIdx = i
				bestEnglishIsSubrip = (s.codec == "subrip")
			}
		}
	}
	if hasEnglish {
		bestIdx = bestEnglishIdx
	}
	best := subs[bestIdx]

	cmd := exec.Command(f.ffmpegPath,
		"-y", // overwrite any existing SRT, including empty ones
		"-i", videoPath,
		"-map", fmt.Sprintf("0:s:%d", best.idx),
		"-c:s", "srt",
		outputPath)

	var out bytes.Buffer
	var stderr bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &stderr

	if err := cmd.Run(); err != nil {
		return fmt.Errorf("ffmpeg failed to extract subtitles: %v, stderr: %s", err, stderr.String())
	}

	return nil
}

// ExtractKeyframes extracts keyframes from a video at specific intervals
func (f *FFmpegClient) ExtractKeyframes(videoPath, outputDir string, interval int) error {
	// Create a pattern for output files
	outputPattern := fmt.Sprintf("%s/frame_%%04d.jpg", outputDir)
	
	cmd := exec.Command(f.ffmpegPath,
		"-i", videoPath,
		"-vf", fmt.Sprintf("fps=1/%d", interval),
		"-q:v", "2",
		outputPattern)

	var out bytes.Buffer
	var stderr bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &stderr

	err := cmd.Run()
	if err != nil {
		return fmt.Errorf("ffmpeg failed to extract keyframes: %v, stderr: %s", err, stderr.String())
	}

	return nil
}

// CheckFFmpeg checks if FFmpeg and FFprobe are available
func (f *FFmpegClient) CheckFFmpeg() error {
	// Check ffprobe
	cmd := exec.Command(f.ffprobePath, "-version")
	err := cmd.Run()
	if err != nil {
		return fmt.Errorf("ffprobe not found: %v", err)
	}

	// Check ffmpeg
	cmd = exec.Command(f.ffmpegPath, "-version")
	err = cmd.Run()
	if err != nil {
		return fmt.Errorf("ffmpeg not found: %v", err)
	}

	return nil
}