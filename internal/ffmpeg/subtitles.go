package ffmpeg

import (
	"bufio"
	"fmt"
	"os"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// Subtitle represents a single subtitle entry
type Subtitle struct {
	Index int
	Start time.Duration
	End   time.Duration
	Text  string
}

// ParseSRTFile parses an SRT subtitle file
func ParseSRTFile(filename string) ([]Subtitle, error) {
	file, err := os.Open(filename)
	if err != nil {
		return nil, fmt.Errorf("failed to open SRT file: %v", err)
	}
	defer file.Close()

	var subtitles []Subtitle
	scanner := bufio.NewScanner(file)
	
	var current Subtitle
	lineNum := 0
	inText := false
	
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		lineNum++
		
		// Skip empty lines
		if line == "" {
			if inText && current.Text != "" {
				subtitles = append(subtitles, current)
				current = Subtitle{}
				inText = false
			}
			continue
		}
		
		// Parse index (number)
		if !inText {
			if index, err := strconv.Atoi(line); err == nil {
				current.Index = index
				continue
			}
			
			// Parse time range
			if times := parseTimeRange(line); times != nil {
				current.Start = times[0]
				current.End = times[1]
				inText = true
				continue
			}
		}
		
		// Parse text
		if inText {
			if current.Text != "" {
				current.Text += "\n" + line
			} else {
				current.Text = line
			}
		}
	}
	
	// Add the last subtitle if exists
	if inText && current.Text != "" {
		subtitles = append(subtitles, current)
	}
	
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("error reading SRT file: %v", err)
	}
	
	return subtitles, nil
}

// parseTimeRange parses SRT time format: HH:MM:SS,mmm --> HH:MM:SS,mmm
func parseTimeRange(line string) []time.Duration {
	// Regex to match SRT time format
	re := regexp.MustCompile(`(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})`)
	matches := re.FindStringSubmatch(line)
	
	if len(matches) != 9 {
		return nil
	}
	
	// Parse start time
	startHours, _ := strconv.Atoi(matches[1])
	startMinutes, _ := strconv.Atoi(matches[2])
	startSeconds, _ := strconv.Atoi(matches[3])
	startMilliseconds, _ := strconv.Atoi(matches[4])
	
	startTime := time.Duration(startHours)*time.Hour +
		time.Duration(startMinutes)*time.Minute +
		time.Duration(startSeconds)*time.Second +
		time.Duration(startMilliseconds)*time.Millisecond
	
	// Parse end time
	endHours, _ := strconv.Atoi(matches[5])
	endMinutes, _ := strconv.Atoi(matches[6])
	endSeconds, _ := strconv.Atoi(matches[7])
	endMilliseconds, _ := strconv.Atoi(matches[8])
	
	endTime := time.Duration(endHours)*time.Hour +
		time.Duration(endMinutes)*time.Minute +
		time.Duration(endSeconds)*time.Second +
		time.Duration(endMilliseconds)*time.Millisecond
	
	return []time.Duration{startTime, endTime}
}

// FormatDurationToSRT converts time.Duration to SRT time format
func FormatDurationToSRT(d time.Duration) string {
	hours := int(d.Hours())
	minutes := int(d.Minutes()) % 60
	seconds := int(d.Seconds()) % 60
	milliseconds := int(d.Milliseconds()) % 1000
	
	return fmt.Sprintf("%02d:%02d:%02d,%03d", hours, minutes, seconds, milliseconds)
}