# Multi-Video Database Architecture Plan: Microservices Approach

## Strategic Overview
Separate high-performance video ingestion system from ComfyUI's query/playback interface. This architecture supports 500+ DVDs with cloud migration capabilities.

## Architecture: Database + API + ComfyUI

```
┌─────────────────────────────────────────────────────────────────┐
│                     CLOUD DEPLOYMENT READY                     │
├─────────────────────┬─────────────────────┬─────────────────────┤
│   DATABASE LAYER    │     API LAYER       │   CLIENT LAYER      │
│                     │                     │                     │
│  ┌─────────────────┐│  ┌─────────────────┐│  ┌─────────────────┐ │
│  │ PostgreSQL      ││  │ API Server      ││  │ ComfyUI Nodes   │ │
│  │ + Vector Ext.   ││  │ (Go/Rust)       ││  │ (Query/Search)  │ │
│  │                 ││  │                 ││  │                 │ │
│  │ ┌─────────────┐ ││  │ ┌─────────────┐ ││  │ ┌─────────────┐ │ │
│  │ │ Video Meta  │ ││  │ │ REST API    │ ││  │ │ Search Node │ │ │
│  │ │ Scenes      │ ││  │ │ WebSocket   │ ││  │ │ Result Node │ │ │
│  │ │ Captions    │ ││  │ │ gRPC        │ ││  │ │ Player Node │ │ │
│  │ │ Embeddings  │ ││  │ │             │ ││  │ │             │ │ │
│  │ └─────────────┘ ││  │ └─────────────┘ ││  │ └─────────────┘ │ │
│  └─────────────────┘│  └─────────────────┘│  └─────────────────┘ │
│                     │                     │                     │
│  ┌─────────────────┐│  ┌─────────────────┐│  ┌─────────────────┐ │
│  │ File Storage    ││  │ Video Processor ││  │ Management UI   │ │
│  │ (Local/S3)      ││  │ (Background)    ││  │ (Web Dashboard) │ │
│  └─────────────────┘│  └─────────────────┘│  └─────────────────┘ │
│                     │                     │                     │
│    DOCKER COMPOSE   │    DOCKER COMPOSE   │    COMFYUI PLUGIN   │
└─────────────────────┴─────────────────────┴─────────────────────┘
```

## Technology Stack Evaluation

### Database Engine Options

#### Option 1: PostgreSQL + pgvector (RECOMMENDED)
```yaml
Pros:
  - Native vector similarity search (pgvector extension)
  - ACID compliance for metadata integrity
  - Excellent JSON support for flexible schemas
  - Cloud-native (AWS RDS, Google Cloud SQL, etc.)
  - Mature ecosystem and tooling
  - Docker official images
  - Built-in replication and backup

Cons:
  - Slightly more resource intensive than SQLite
  - Requires separate service (but dockerized)

Storage Estimate (500 DVDs):
  - Video metadata: ~50MB
  - Scene data: ~500MB 
  - Embeddings (768d): ~20GB
  - Captions: ~1GB
  - Total: ~22GB + videos
```

#### Option 2: Qdrant Vector Database
```yaml
Pros:
  - Purpose-built for vector similarity
  - Extremely fast search performance
  - Built-in clustering and filtering
  - Cloud-ready with managed options
  - Rust-based (high performance)

Cons:
  - Less mature ecosystem
  - Additional complexity for metadata
  - Learning curve for SQL developers
```

### API Server Technology Analysis

#### Option 1: Go (RECOMMENDED)
```yaml
Language: Go
Framework: Gin/Echo + GORM

Pros:
  - Excellent concurrency for video processing
  - Fast compilation and deployment
  - Strong ecosystem for media processing (ffmpeg bindings)
  - Low memory footprint
  - Easy Docker packaging
  - Cross-platform compilation

Cons:
  - Less AI/ML ecosystem than Python
  - Verbose error handling

Development Speed: ⭐⭐⭐⭐
Performance: ⭐⭐⭐⭐⭐
Cloud Ready: ⭐⭐⭐⭐⭐
```

#### Option 2: Rust
```yaml
Language: Rust
Framework: Axum/Actix + Diesel

Pros:
  - Maximum performance and memory safety
  - Excellent for CPU-intensive video processing
  - Zero-cost abstractions
  - Growing WASM ecosystem

Cons:
  - Steeper learning curve
  - Slower development iteration
  - Smaller AI/ML ecosystem

Development Speed: ⭐⭐⭐
Performance: ⭐⭐⭐⭐⭐
Cloud Ready: ⭐⭐⭐⭐⭐
```

#### Option 3: Python (FastAPI)
```yaml
Language: Python
Framework: FastAPI + SQLAlchemy

Pros:
  - Easy integration with existing CLIP/ML code
  - Rich AI/ML ecosystem
  - Fast development iteration
  - Familiar for ComfyUI developers

Cons:
  - Lower performance for intensive processing
  - Higher memory usage
  - GIL limitations for concurrency

Development Speed: ⭐⭐⭐⭐⭐
Performance: ⭐⭐⭐
Cloud Ready: ⭐⭐⭐⭐
```

## Recommended Architecture: Go + PostgreSQL

### Component Breakdown

#### 1. Database Service (PostgreSQL + pgvector)
```sql
-- Core Tables
CREATE EXTENSION vector;

CREATE TABLE videos (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(512) NOT NULL,
    file_hash CHAR(64) UNIQUE NOT NULL,
    title VARCHAR(256),
    duration REAL,
    scene_count INTEGER,
    embedding_model VARCHAR(64),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    tags JSONB DEFAULT '[]',
    status VARCHAR(32) DEFAULT 'pending',
    metadata JSONB DEFAULT '{}'
);

CREATE TABLE scenes (
    id SERIAL PRIMARY KEY,
    video_id INTEGER REFERENCES videos(id) ON DELETE CASCADE,
    scene_index INTEGER NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    has_captions BOOLEAN DEFAULT FALSE,
    visual_embedding vector(768),
    text_embedding vector(768),
    combined_embedding vector(768),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE captions (
    id SERIAL PRIMARY KEY,
    video_id INTEGER REFERENCES videos(id) ON DELETE CASCADE,
    scene_id INTEGER REFERENCES scenes(id) ON DELETE CASCADE,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    text TEXT NOT NULL,
    language VARCHAR(10) DEFAULT 'en'
);

-- Vector similarity indexes
CREATE INDEX scenes_visual_embedding_idx ON scenes 
USING ivfflat (visual_embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX scenes_combined_embedding_idx ON scenes 
USING ivfflat (combined_embedding vector_cosine_ops) WITH (lists = 100);

-- Metadata indexes
CREATE INDEX videos_status_idx ON videos(status);
CREATE INDEX videos_created_at_idx ON videos(created_at);
CREATE INDEX scenes_video_id_idx ON scenes(video_id);
```

#### 2. Go API Server
```go
// Core API Structure
type APIServer struct {
    db          *gorm.DB
    vectorDB    *pgvector.Client
    processor   *VideoProcessor
    config      *Config
}

// Main API Routes
/api/v1/videos
  POST   /                 // Upload/register new video
  GET    /                 // List videos with pagination
  GET    /:id              // Get video details
  DELETE /:id              // Remove video from database
  
/api/v1/search
  POST   /semantic         // Vector similarity search
  POST   /text             // Text-based search in captions
  POST   /hybrid           // Combined search
  
/api/v1/scenes
  GET    /video/:id        // Get scenes for video
  GET    /:id/similar      // Find similar scenes
  
/api/v1/process
  POST   /video            // Queue video for processing
  GET    /status/:job_id   // Check processing status
  
/api/v1/admin
  GET    /health           // Health check
  GET    /stats            // Database statistics
  POST   /optimize        // Rebuild indexes
```

#### 3. Background Video Processor
```go
type VideoProcessor struct {
    queue       chan ProcessingJob
    workers     int
    clipModel   *clip.Model
    sceneDetect *scenedetect.Detector
}

type ProcessingJob struct {
    VideoID     int64
    FilePath    string
    Options     ProcessingOptions
    StatusChan  chan ProcessingUpdate
}

// Processing Pipeline
1. Video validation and metadata extraction
2. Scene detection (PySceneDetect via CGO or subprocess)
3. Caption extraction (FFmpeg)
4. Frame sampling and CLIP encoding
5. Database storage with atomic transactions
6. Index optimization
```

## Docker Compose Architecture

```yaml
# docker-compose.yml
version: '3.8'
services:
  # Database
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: goodclips
      POSTGRES_USER: goodclips
      POSTGRES_PASSWORD: your_secure_password
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init.sql:/docker-entrypoint-initdb.d/init.sql
    ports:
      - "5432:5432"
    restart: unless-stopped

  # API Server
  goodclips-api:
    build: ./api-server
    environment:
      DATABASE_URL: postgres://goodclips:password@postgres:5432/goodclips
      REDIS_URL: redis://redis:6379
      STORAGE_PATH: /data/videos
    volumes:
      - video_storage:/data/videos
      - processing_cache:/tmp/processing
    ports:
      - "8080:8080"
    depends_on:
      - postgres
      - redis
    restart: unless-stopped

  # Background Processor
  goodclips-processor:
    build: ./api-server
    command: ["./goodclips", "worker"]
    environment:
      DATABASE_URL: postgres://goodclips:password@postgres:5432/goodclips
      REDIS_URL: redis://redis:6379
      WORKER_CONCURRENCY: 4
    volumes:
      - video_storage:/data/videos
      - processing_cache:/tmp/processing
      - model_cache:/root/.cache/huggingface
    depends_on:
      - postgres
      - redis
    restart: unless-stopped

  # Job Queue
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    restart: unless-stopped

  # Web Dashboard (Optional)
  goodclips-web:
    build: ./web-dashboard
    ports:
      - "3000:3000"
    environment:
      API_URL: http://goodclips-api:8080
    depends_on:
      - goodclips-api
    restart: unless-stopped

  # Reverse Proxy
  nginx:
    image: nginx:alpine
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
    ports:
      - "80:80"
      - "443:443"
    depends_on:
      - goodclips-api
      - goodclips-web
    restart: unless-stopped

volumes:
  postgres_data:
  video_storage:
  processing_cache:
  model_cache:
```

## ComfyUI Integration Layer

### New Simplified Nodes

#### 1. **GoodCLIPS Connect Node**
```python
Inputs:
  - api_url: STRING (default: "http://localhost:8080")
  - api_key: STRING (optional authentication)

Outputs:
  - connection: API_CONNECTION
  - status: DICT (database stats, video count)
```

#### 2. **Video Search Node**
```python
Inputs:
  - connection: API_CONNECTION
  - query_text: STRING
  - search_type: ["semantic", "text", "hybrid"]
  - video_filters: LIST (optional video IDs)
  - k_results: INT
  - similarity_threshold: FLOAT

Outputs:
  - search_results: LIST
  - result_metadata: DICT
```

#### 3. **Clip Player Node**
```python
Inputs:
  - connection: API_CONNECTION
  - search_results: LIST
  - clip_index: INT
  - include_context: BOOLEAN (show adjacent scenes)

Outputs:
  - video_stream: VIDEO
  - clip_metadata: DICT
```

## Performance Characteristics (500 DVDs)

### Storage Requirements
```
PostgreSQL Database: ~25GB
  - Video metadata: 50MB
  - Scene data: 1GB 
  - Embeddings: 20GB
  - Captions: 2GB
  - Indexes: 2GB

Video Files: ~1-2TB (depending on quality)
Processing Cache: 100GB (temporary)
```

### Performance Estimates
```
Search Performance:
  - Simple semantic search: <100ms
  - Complex multi-video search: <500ms
  - Full-text caption search: <50ms

Processing Performance:
  - New video ingestion: 10-30 minutes/DVD
  - Concurrent processing: 4-8 videos simultaneously
  - Re-indexing: 5-10 minutes for full database
```

## Deployment Strategies

### Local Development
```bash
# Clone and start
git clone goodclips-system
docker-compose up -d

# Process first video
curl -X POST http://localhost:8080/api/v1/videos \
  -F "file=@movie.mkv" \
  -F "title=Action Movie"
```

### Cloud Migration Options

#### AWS Deployment
```yaml
Services:
  - RDS PostgreSQL with pgvector
  - ECS Fargate for API servers
  - S3 for video storage
  - ElastiCache for Redis
  - Application Load Balancer
  - CloudFront for video streaming
```

#### Self-Hosted Cloud
```yaml
Services:
  - DigitalOcean Droplet or Vultr VPS
  - Managed PostgreSQL database
  - S3-compatible object storage (Spaces)
  - Docker Swarm for orchestration
```

## Development Timeline

### Phase 1: Core Infrastructure (4-6 weeks)
- [ ] PostgreSQL schema and Docker setup
- [ ] Go API server basic structure
- [ ] Video metadata and scene processing
- [ ] Basic ComfyUI connection nodes

### Phase 2: Search and Embeddings (3-4 weeks)  
- [ ] CLIP model integration
- [ ] Vector similarity search
- [ ] Caption processing
- [ ] Search result ranking

### Phase 3: User Interface (2-3 weeks)
- [ ] ComfyUI search and playback nodes
- [ ] Web dashboard for management
- [ ] Batch processing workflows

### Phase 4: Production Ready (2-3 weeks)
- [ ] Performance optimization
- [ ] Cloud deployment configs
- [ ] Monitoring and logging
- [ ] Documentation

## Migration Strategy

1. **Parallel Development**: Build new system alongside existing ComfyUI nodes
2. **Import Utility**: Convert existing cache files to new database
3. **Gradual Adoption**: Users can choose between old and new systems
4. **Feature Parity**: Ensure new system has all current capabilities
5. **Performance Validation**: Benchmark against current system

This architecture provides enterprise-grade scalability while maintaining the ease of use that makes ComfyUI great. The clear separation of concerns allows each component to be optimized for its specific role.