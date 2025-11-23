#!/bin/bash
# Cinema Chat - Local Development Startup Script
#
# This script starts all services needed for local development:
# 1. MCP Server (mock server with keyword-based video search)
# 2. Video Playback Service (HTTP server for playing videos via ffmpeg)
# 3. Cinema Bot Backend (FastAPI server with Whisper STT + OpenAI GPT)
# 4. Next.js Frontend (web interface for monitoring conversation)
#
# Usage:
#   ./start-local.sh
#
# To stop all services:
#   ./stop-local.sh (or press Ctrl+C and kill remaining processes)

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Base directory
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$BASE_DIR/logs"
PID_DIR="$BASE_DIR/.pids"

# Create log and pid directories
mkdir -p "$LOG_DIR" "$PID_DIR"

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

# Function to cleanup on exit
cleanup() {
    print_info "Shutting down services..."

    # Kill all processes from PID files
    for pidfile in "$PID_DIR"/*.pid; do
        if [ -f "$pidfile" ]; then
            pid=$(cat "$pidfile")
            if kill -0 "$pid" 2>/dev/null; then
                print_info "Stopping process $pid ($(basename "$pidfile" .pid))"
                kill "$pid" 2>/dev/null || true
            fi
            rm "$pidfile"
        fi
    done

    print_success "All services stopped"
    exit 0
}

# Trap Ctrl+C and call cleanup
trap cleanup INT TERM

# Check if .env files exist
check_env_files() {
    print_info "Checking environment files..."

    if [ ! -f "$BASE_DIR/cinema-bot-app/backend/src/cinema-bot/.env" ]; then
        print_error "Missing .env file: cinema-bot-app/backend/src/cinema-bot/.env"
        print_info "Please copy from .env.example and configure with your API keys"
        exit 1
    fi

    if [ ! -f "$BASE_DIR/mcp/.env" ]; then
        print_warning "Missing .env file: mcp/.env (optional for mock server)"
    fi

    print_success "Environment files OK"
}

# Start MCP Mock Server
start_mcp_server() {
    print_info "Starting MCP Mock Server..."

    cd "$BASE_DIR/mcp"

    # Check if venv exists, create if not
    if [ ! -d "venv" ]; then
        print_info "Creating Python virtual environment for MCP..."
        python3 -m venv venv
        source venv/bin/activate
        pip install -r requirements.txt
    else
        source venv/bin/activate
    fi

    # Start the server in background
    python3 mock_server.py > "$LOG_DIR/mcp-server.log" 2>&1 &
    echo $! > "$PID_DIR/mcp-server.pid"

    print_success "MCP Server started (PID: $(cat "$PID_DIR/mcp-server.pid"))"
    print_info "Logs: $LOG_DIR/mcp-server.log"

    deactivate
}

# Start Video Playback Service
start_video_service() {
    print_info "Starting Video Playback Service..."

    cd "$BASE_DIR/mcp"

    # Use the same venv as MCP
    source venv/bin/activate

    # Start the service in background
    python3 video_playback_service.py > "$LOG_DIR/video-playback.log" 2>&1 &
    echo $! > "$PID_DIR/video-playback.pid"

    print_success "Video Playback Service started (PID: $(cat "$PID_DIR/video-playback.pid"))"
    print_info "Logs: $LOG_DIR/video-playback.log"
    print_info "HTTP endpoint: http://localhost:5000"

    deactivate
}

# Start Cinema Bot Backend
start_cinema_bot() {
    print_info "Starting Cinema Bot Backend..."

    cd "$BASE_DIR/cinema-bot-app/backend/src/cinema-bot"

    # Check if venv exists, create if not
    if [ ! -d "../../venv" ]; then
        print_info "Creating Python virtual environment for Cinema Bot..."
        cd ../..
        python3 -m venv venv
        source venv/bin/activate
        pip install -r requirements.txt
        cd src/cinema-bot
    else
        cd ../..
        source venv/bin/activate
        cd src/cinema-bot
    fi

    # Start the server in background
    python3 server.py > "$LOG_DIR/cinema-bot.log" 2>&1 &
    echo $! > "$PID_DIR/cinema-bot.pid"

    print_success "Cinema Bot Backend started (PID: $(cat "$PID_DIR/cinema-bot.pid"))"
    print_info "Logs: $LOG_DIR/cinema-bot.log"
    print_info "API endpoint: http://localhost:7860"

    deactivate
}

# Start Next.js Frontend
start_frontend() {
    print_info "Starting Next.js Frontend..."

    cd "$BASE_DIR/cinema-bot-app/frontend-next"

    # Check if node_modules exists
    if [ ! -d "node_modules" ]; then
        print_info "Installing npm dependencies..."
        npm install
    fi

    # Start the frontend in background
    npm run dev > "$LOG_DIR/frontend.log" 2>&1 &
    echo $! > "$PID_DIR/frontend.pid"

    print_success "Next.js Frontend started (PID: $(cat "$PID_DIR/frontend.pid"))"
    print_info "Logs: $LOG_DIR/frontend.log"
    print_info "Web interface: http://localhost:3000"
}

# Wait for service to start
wait_for_service() {
    local service_name=$1
    local port=$2
    local max_attempts=30
    local attempt=0

    print_info "Waiting for $service_name to start on port $port..."

    while [ $attempt -lt $max_attempts ]; do
        if nc -z localhost $port 2>/dev/null; then
            print_success "$service_name is ready"
            return 0
        fi
        attempt=$((attempt + 1))
        sleep 1
    done

    print_error "$service_name failed to start within 30 seconds"
    return 1
}

# Main execution
main() {
    print_info "Cinema Chat - Starting Local Development Environment"
    print_info "================================================"

    # Check prerequisites
    check_env_files

    # Start services in order
    start_mcp_server
    sleep 2

    start_video_service
    wait_for_service "Video Playback Service" 5000

    start_cinema_bot
    wait_for_service "Cinema Bot Backend" 7860

    start_frontend
    wait_for_service "Next.js Frontend" 3000

    print_info "================================================"
    print_success "All services started successfully!"
    print_info ""
    print_info "Service URLs:"
    print_info "  - Frontend:       http://localhost:3000"
    print_info "  - Cinema Bot API: http://localhost:7860"
    print_info "  - Video Service:  http://localhost:5000"
    print_info ""
    print_info "Logs are available in: $LOG_DIR"
    print_info "Press Ctrl+C to stop all services"
    print_info ""

    # Wait for interrupt
    while true; do
        sleep 1
    done
}

# Run main function
main
