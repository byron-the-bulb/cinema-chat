#!/bin/bash
# Cinema Chat - Cloud Deployment Startup Script
#
# This script starts all services on cloud infrastructure using Docker containers.
# It uses the existing Docker configurations and docker-compose setup.
#
# Services:
# 1. GoodCLIPS API (Go + Postgres + Redis) - via docker-compose
# 2. MCP Server (real server with GoodCLIPS integration) - via Docker
# 3. Cinema Bot Backend (FastAPI) - via Docker
# 4. Next.js Frontend (monitoring interface) - via Docker or npm
#
# Usage:
#   ./start-cloud.sh [--build] [--dev]
#
# Options:
#   --build    Rebuild Docker images before starting
#   --dev      Run in development mode (with hot reload)

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Base directory
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse arguments
BUILD_FLAG=""
DEV_MODE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --build)
            BUILD_FLAG="--build"
            shift
            ;;
        --dev)
            DEV_MODE=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--build] [--dev]"
            exit 1
            ;;
    esac
done

# Function to print colored messages
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Check if Docker is running
check_docker() {
    print_info "Checking Docker..."
    if ! docker info > /dev/null 2>&1; then
        print_error "Docker is not running. Please start Docker first."
        exit 1
    fi
    print_success "Docker is running"
}

# Check if .env files exist
check_env_files() {
    print_info "Checking environment files..."

    if [ ! -f "$BASE_DIR/.env" ]; then
        print_error "Missing .env file in root directory"
        print_info "Please copy from .env.example and configure"
        exit 1
    fi

    if [ ! -f "$BASE_DIR/cinema-bot-app/backend/.env" ]; then
        print_error "Missing .env file: cinema-bot-app/backend/.env"
        print_info "Please copy from .env.example and configure with your API keys"
        exit 1
    fi

    print_success "Environment files OK"
}

# Start GoodCLIPS API stack (Go + Postgres + Redis)
start_goodclips_api() {
    print_info "Starting GoodCLIPS API stack..."

    cd "$BASE_DIR"

    # Check if docker-compose.yml exists
    if [ ! -f "docker-compose.yml" ]; then
        print_error "docker-compose.yml not found"
        exit 1
    fi

    # Start the stack
    if [ -n "$BUILD_FLAG" ]; then
        docker-compose up -d --build
    else
        docker-compose up -d
    fi

    print_success "GoodCLIPS API stack started"
    print_info "Services: Postgres, Redis, GoodCLIPS API"
    print_info "API endpoint: http://localhost:8080"
}

# Build Cinema Bot Docker image
build_cinema_bot() {
    print_info "Building Cinema Bot Docker image..."

    cd "$BASE_DIR/cinema-bot-app/backend"

    # Use the existing build script
    if [ -f "build.sh" ]; then
        bash build.sh
    else
        docker build -t cinema-chat-bot:latest .
    fi

    print_success "Cinema Bot image built"
}

# Start Cinema Bot container
start_cinema_bot() {
    print_info "Starting Cinema Bot container..."

    cd "$BASE_DIR"

    # Stop and remove existing container if it exists
    docker stop cinema-bot 2>/dev/null || true
    docker rm cinema-bot 2>/dev/null || true

    # Get GPU device arguments if available
    GPU_ARGS=""
    if command -v nvidia-smi &> /dev/null; then
        print_info "NVIDIA GPU detected, enabling GPU support"
        GPU_ARGS="--gpus all"
    fi

    # Start the container
    docker run -d \
        --name cinema-bot \
        --network host \
        $GPU_ARGS \
        -e OPENAI_API_KEY="${OPENAI_API_KEY:-}" \
        -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" \
        -e DAILY_API_KEY="${DAILY_API_KEY:-}" \
        -e WHISPER_DEVICE="${WHISPER_DEVICE:-cuda}" \
        -v "$BASE_DIR/cinema-bot-app/backend/src/cinema-bot:/app/cinema-bot" \
        -v "$BASE_DIR/data:/data" \
        cinema-chat-bot:latest

    print_success "Cinema Bot container started"
    print_info "Container name: cinema-bot"
    print_info "API endpoint: http://localhost:7860"
    print_info "View logs: docker logs -f cinema-bot"
}

# Build MCP Server Docker image
build_mcp_server() {
    print_info "Building MCP Server Docker image..."

    cd "$BASE_DIR/mcp"

    # Create Dockerfile if it doesn't exist
    if [ ! -f "Dockerfile" ]; then
        cat > Dockerfile <<'EOF'
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port for video playback service
EXPOSE 5000

# Default to running the real server (with GoodCLIPS integration)
CMD ["python3", "server.py"]
EOF
    fi

    docker build -t cinema-mcp-server:latest .

    print_success "MCP Server image built"
}

# Start MCP Server container
start_mcp_server() {
    print_info "Starting MCP Server container..."

    cd "$BASE_DIR"

    # Stop and remove existing container if it exists
    docker stop cinema-mcp 2>/dev/null || true
    docker rm cinema-mcp 2>/dev/null || true

    # Determine which server to run
    MCP_CMD="python3 server.py"
    if [ "$DEV_MODE" = true ]; then
        print_info "Running in dev mode with mock server"
        MCP_CMD="python3 mock_server.py"
    fi

    # Start the container
    docker run -d \
        --name cinema-mcp \
        --network host \
        -e GOODCLIPS_API_URL="${GOODCLIPS_API_URL:-http://localhost:8080}" \
        -v "$BASE_DIR/mcp:/app" \
        -v "$BASE_DIR/data:/data" \
        cinema-mcp-server:latest \
        bash -c "$MCP_CMD & python3 video_playback_service.py"

    print_success "MCP Server container started"
    print_info "Container name: cinema-mcp"
    print_info "MCP Server: stdio"
    print_info "Video Playback: http://localhost:5000"
    print_info "View logs: docker logs -f cinema-mcp"
}

# Start Frontend (Next.js)
start_frontend() {
    print_info "Starting Next.js Frontend..."

    cd "$BASE_DIR/cinema-bot-app/frontend-next"

    if [ "$DEV_MODE" = true ]; then
        # Run in development mode with npm
        print_info "Running frontend in development mode..."

        # Install dependencies if needed
        if [ ! -d "node_modules" ]; then
            npm install
        fi

        # Start in background
        npm run dev > "$BASE_DIR/logs/frontend.log" 2>&1 &
        echo $! > "$BASE_DIR/.pids/frontend.pid"
    else
        # Build and run in production mode with Docker
        print_info "Building frontend Docker image..."

        # Create Dockerfile if it doesn't exist
        if [ ! -f "Dockerfile" ]; then
            cat > Dockerfile <<'EOF'
FROM node:20-alpine

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci --only=production

# Copy application code
COPY . .

# Build the application
RUN npm run build

# Expose port
EXPOSE 3000

# Start the application
CMD ["npm", "start"]
EOF
        fi

        docker build -t cinema-frontend:latest .

        # Stop and remove existing container
        docker stop cinema-frontend 2>/dev/null || true
        docker rm cinema-frontend 2>/dev/null || true

        # Start the container
        docker run -d \
            --name cinema-frontend \
            -p 3000:3000 \
            --network host \
            cinema-frontend:latest
    fi

    print_success "Frontend started"
    print_info "Web interface: http://localhost:3000"
}

# Wait for service to be healthy
wait_for_service() {
    local service_name=$1
    local port=$2
    local max_attempts=30
    local attempt=0

    print_info "Waiting for $service_name to be ready on port $port..."

    while [ $attempt -lt $max_attempts ]; do
        if nc -z localhost $port 2>/dev/null; then
            print_success "$service_name is ready"
            return 0
        fi
        attempt=$((attempt + 1))
        sleep 1
    done

    print_error "$service_name failed to start within 30 seconds"
    print_info "Check logs with: docker logs cinema-${service_name}"
    return 1
}

# Main execution
main() {
    print_info "Cinema Chat - Cloud Deployment"
    print_info "==============================="

    if [ "$DEV_MODE" = true ]; then
        print_warning "Running in DEVELOPMENT mode"
    fi

    if [ -n "$BUILD_FLAG" ]; then
        print_info "Will rebuild all Docker images"
    fi

    print_info ""

    # Check prerequisites
    check_docker
    check_env_files

    # Create directories
    mkdir -p "$BASE_DIR/logs" "$BASE_DIR/.pids"

    # Start services in order
    print_info ""
    print_info "Starting services..."
    print_info ""

    # 1. Start GoodCLIPS API stack
    start_goodclips_api
    wait_for_service "GoodCLIPS API" 8080

    # 2. Build and start MCP Server (if --build flag)
    if [ -n "$BUILD_FLAG" ]; then
        build_mcp_server
    fi
    start_mcp_server
    wait_for_service "Video Playback" 5000

    # 3. Build and start Cinema Bot (if --build flag)
    if [ -n "$BUILD_FLAG" ]; then
        build_cinema_bot
    fi
    start_cinema_bot
    wait_for_service "Cinema Bot" 7860

    # 4. Start Frontend
    start_frontend
    wait_for_service "Frontend" 3000

    print_info ""
    print_info "==============================="
    print_success "All services started successfully!"
    print_info ""
    print_info "Service URLs:"
    print_info "  - Frontend:       http://localhost:3000"
    print_info "  - Cinema Bot API: http://localhost:7860"
    print_info "  - GoodCLIPS API:  http://localhost:8080"
    print_info "  - Video Service:  http://localhost:5000"
    print_info ""
    print_info "Docker Containers:"
    print_info "  - cinema-bot      (Cinema Bot Backend)"
    print_info "  - cinema-mcp      (MCP Server + Video Playback)"
    print_info "  - cinema-frontend (Next.js Frontend)"
    print_info "  + GoodCLIPS stack (via docker-compose)"
    print_info ""
    print_info "Useful commands:"
    print_info "  - View logs:        docker logs -f <container-name>"
    print_info "  - Stop all:         docker stop cinema-bot cinema-mcp cinema-frontend && docker-compose down"
    print_info "  - Restart service:  docker restart <container-name>"
    print_info ""
}

# Run main function
main
