package queue

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/go-redis/redis/v8"
)

// Job represents a processing job in the queue
type Job struct {
	ID          string                 `json:"id"`
	Type        JobType                `json:"type"`
	Payload     map[string]interface{} `json:"payload"`
	Status      JobStatus              `json:"status"`
	Progress    int                    `json:"progress"`
	CreatedAt   time.Time              `json:"created_at"`
	StartedAt   *time.Time             `json:"started_at,omitempty"`
	CompletedAt *time.Time             `json:"completed_at,omitempty"`
	ErrorMessage *string               `json:"error_message,omitempty"`
}

// JobType represents the type of processing job
type JobType string

const (
	JobTypeVideoIngestion      JobType = "video_ingestion"
	JobTypeSceneDetection      JobType = "scene_detection"
	JobTypeCaptionExtraction   JobType = "caption_extraction"
	JobTypeEmbeddingGeneration JobType = "embedding_generation"
	JobTypeVideoAnalysis       JobType = "video_analysis"
)

// JobStatus represents the processing status of a job
type JobStatus string

const (
	JobStatusPending   JobStatus = "pending"
	JobStatusRunning   JobStatus = "running"
	JobStatusCompleted JobStatus = "completed"
	JobStatusFailed    JobStatus = "failed"
	JobStatusCancelled JobStatus = "cancelled"
)

// Queue represents the job queue system
type Queue struct {
	client *redis.Client
	ctx    context.Context
}

// Config holds queue configuration
type Config struct {
	Addr     string
	Password string
	DB       int
}

// NewQueue creates a new queue instance
func NewQueue(config Config) (*Queue, error) {
	client := redis.NewClient(&redis.Options{
		Addr:     config.Addr,
		Password: config.Password,
		DB:       config.DB,
	})

	ctx := context.Background()

	// Test connection
	_, err := client.Ping(ctx).Result()
	if err != nil {
		return nil, fmt.Errorf("failed to connect to Redis: %w", err)
	}

	return &Queue{
		client: client,
		ctx:    ctx,
	}, nil
}

// Enqueue adds a job to the queue
func (q *Queue) Enqueue(jobType JobType, payload map[string]interface{}) (*Job, error) {
	job := &Job{
		ID:        generateJobID(),
		Type:      jobType,
		Payload:   payload,
		Status:    JobStatusPending,
		Progress:  0,
		CreatedAt: time.Now(),
	}

	jobBytes, err := json.Marshal(job)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal job: %w", err)
	}

	// Add job to the queue
	queueName := fmt.Sprintf("jobs:%s", jobType)
	err = q.client.LPush(q.ctx, queueName, jobBytes).Err()
	if err != nil {
		return nil, fmt.Errorf("failed to enqueue job: %w", err)
	}

	// Add job to the job hash for tracking
	jobKey := fmt.Sprintf("job:%s", job.ID)
	err = q.client.HSet(q.ctx, jobKey, "data", jobBytes).Err()
	if err != nil {
		return nil, fmt.Errorf("failed to store job data: %w", err)
	}

	return job, nil
}

// Dequeue retrieves a job from the queue
func (q *Queue) Dequeue(jobType JobType) (*Job, error) {
	queueName := fmt.Sprintf("jobs:%s", jobType)
	result, err := q.client.BRPop(q.ctx, 5*time.Second, queueName).Result()
	if err != nil {
		if err == redis.Nil {
			return nil, nil // No jobs available
		}
		return nil, fmt.Errorf("failed to dequeue job: %w", err)
	}

	if len(result) < 2 {
		return nil, fmt.Errorf("invalid dequeue result")
	}

	var job Job
	err = json.Unmarshal([]byte(result[1]), &job)
	if err != nil {
		return nil, fmt.Errorf("failed to unmarshal job: %w", err)
	}

	return &job, nil
}

// UpdateJobStatus updates the status of a job
func (q *Queue) UpdateJobStatus(jobID string, status JobStatus, progress int, errorMessage *string) error {
	jobKey := fmt.Sprintf("job:%s", jobID)
	
	// Get current job data
	jobData, err := q.client.HGet(q.ctx, jobKey, "data").Result()
	if err != nil {
		return fmt.Errorf("failed to get job data: %w", err)
	}

	var job Job
	err = json.Unmarshal([]byte(jobData), &job)
	if err != nil {
		return fmt.Errorf("failed to unmarshal job: %w", err)
	}

	// Update job fields
	job.Status = status
	job.Progress = progress
	if errorMessage != nil {
		job.ErrorMessage = errorMessage
	}

	// Update timestamps
	now := time.Now()
	switch status {
	case JobStatusRunning:
		job.StartedAt = &now
	case JobStatusCompleted, JobStatusFailed:
		job.CompletedAt = &now
	}

	// Save updated job data
	jobBytes, err := json.Marshal(job)
	if err != nil {
		return fmt.Errorf("failed to marshal job: %w", err)
	}

	err = q.client.HSet(q.ctx, jobKey, "data", jobBytes).Err()
	if err != nil {
		return fmt.Errorf("failed to update job data: %w", err)
	}

	return nil
}

// GetJob retrieves a job by ID
func (q *Queue) GetJob(jobID string) (*Job, error) {
	jobKey := fmt.Sprintf("job:%s", jobID)
	
	jobData, err := q.client.HGet(q.ctx, jobKey, "data").Result()
	if err != nil {
		if err == redis.Nil {
			return nil, fmt.Errorf("job not found: %s", jobID)
		}
		return nil, fmt.Errorf("failed to get job data: %w", err)
	}

	var job Job
	err = json.Unmarshal([]byte(jobData), &job)
	if err != nil {
		return nil, fmt.Errorf("failed to unmarshal job: %w", err)
	}

	return &job, nil
}

// ListJobs returns jobs of a specific type
func (q *Queue) ListJobs(jobType JobType, limit int) ([]*Job, error) {
	// This is a simplified implementation
	// In a production system, you might want a more efficient approach
	// For now, we'll scan for job keys
	var cursor uint64
	var jobs []*Job

	for {
		var keys []string
		var err error
		keys, cursor, err = q.client.Scan(q.ctx, cursor, "job:*", int64(limit)).Result()
		if err != nil {
			return nil, fmt.Errorf("failed to scan job keys: %w", err)
		}

		for _, key := range keys {
			jobData, err := q.client.HGet(q.ctx, key, "data").Result()
			if err != nil {
				continue // Skip jobs with errors
			}

			var job Job
			err = json.Unmarshal([]byte(jobData), &job)
			if err != nil {
				continue // Skip jobs with unmarshal errors
			}

			// Filter by job type
			if job.Type == jobType || jobType == "" {
				jobs = append(jobs, &job)
				if len(jobs) >= limit && limit > 0 {
					break
				}
			}
		}

		if cursor == 0 || (len(jobs) >= limit && limit > 0) {
			break
		}
	}

	return jobs, nil
}

// Close closes the queue connection
func (q *Queue) Close() error {
	return q.client.Close()
}

// generateJobID generates a unique job ID
func generateJobID() string {
	// In a real implementation, you might want to use UUID or similar
	return fmt.Sprintf("job_%d", time.Now().UnixNano())
}