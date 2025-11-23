#!/bin/bash
# Cinema Chat - Stop Local Development Services
#
# This script stops all locally running Cinema Chat services.
#
# Usage:
#   ./stop-local.sh

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Base directory
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="$BASE_DIR/.pids"

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

# Stop services
stop_services() {
    print_info "Stopping Cinema Chat services..."

    if [ ! -d "$PID_DIR" ]; then
        print_info "No PID directory found. Services may not be running."
        return
    fi

    local stopped=0
    local not_running=0

    for pidfile in "$PID_DIR"/*.pid; do
        if [ -f "$pidfile" ]; then
            service_name=$(basename "$pidfile" .pid)
            pid=$(cat "$pidfile")

            if kill -0 "$pid" 2>/dev/null; then
                print_info "Stopping $service_name (PID: $pid)"
                kill "$pid" 2>/dev/null || true

                # Wait for process to stop
                for i in {1..10}; do
                    if ! kill -0 "$pid" 2>/dev/null; then
                        break
                    fi
                    sleep 0.5
                done

                # Force kill if still running
                if kill -0 "$pid" 2>/dev/null; then
                    print_info "Force killing $service_name"
                    kill -9 "$pid" 2>/dev/null || true
                fi

                stopped=$((stopped + 1))
            else
                not_running=$((not_running + 1))
            fi

            rm "$pidfile"
        fi
    done

    if [ $stopped -gt 0 ]; then
        print_success "Stopped $stopped service(s)"
    fi

    if [ $not_running -gt 0 ]; then
        print_info "$not_running service(s) were not running"
    fi

    # Clean up PID directory if empty
    if [ -d "$PID_DIR" ] && [ -z "$(ls -A "$PID_DIR")" ]; then
        rmdir "$PID_DIR"
    fi
}

# Main execution
main() {
    print_info "Cinema Chat - Stopping Local Services"
    print_info "====================================="

    stop_services

    print_info "====================================="
    print_success "All services stopped"
}

# Run main function
main
