#!/usr/bin/env python3
"""
Simple Video Playback Service

A lightweight HTTP server that plays video clips on the TV/HDMI output.
This runs on the installation computer and receives playback requests.

Usage:
    python3 video_playback_service.py

    # Then from anywhere:
    curl -X POST http://localhost:5000/play \
      -H 'Content-Type: application/json' \
      -d '{"video_path": "/path/to/video.mkv", "start": 120, "end": 128}'
"""

from flask import Flask, request, jsonify
import subprocess
import os
import threading
import time

app = Flask(__name__)

# Global state
current_process = None
process_lock = threading.Lock()

VIDEO_BASE = "/home/va55/code/cinema-chat/data/videos"


def play_video(video_path, start_time, end_time, fullscreen=True):
    """
    Play a video clip using ffplay.

    Args:
        video_path: Full path to video file
        start_time: Start time in seconds
        end_time: End time in seconds
        fullscreen: Whether to play fullscreen

    Returns:
        (success, message, pid)
    """
    global current_process

    # Validate file exists
    if not os.path.exists(video_path):
        return False, f"Video file not found: {video_path}", None

    # Stop any current playback
    stop_playback()

    # Calculate duration
    duration = end_time - start_time

    # Build command
    cmd = [
        "ffplay",
        "-ss", str(start_time),
        "-t", str(duration),
        "-autoexit",
        "-loglevel", "error",
    ]

    if fullscreen:
        cmd.append("-fs")

    cmd.append(video_path)

    # Set environment variables for display targeting
    env = os.environ.copy()
    env['DISPLAY'] = ':0'  # Default X display

    # SDL_VIDEO_WINDOW_POS can position the window on a specific monitor
    # Format: "X,Y" where X,Y are screen coordinates
    # For multi-monitor setups, you can use screen index: "SDL_VIDEO_FULLSCREEN_DISPLAY=1"
    # Get display configuration from environment or use defaults
    video_display = os.environ.get('VIDEO_DISPLAY', '1')  # Default to display 1 (HDMI)

    # Set SDL to use specific display for fullscreen
    env['SDL_VIDEO_FULLSCREEN_DISPLAY'] = video_display

    # Optionally set window position for non-fullscreen mode
    # If your primary monitor is 1920x1080 and HDMI is to the right:
    # SDL_VIDEO_WINDOW_POS="1920,0" would place it on the second monitor
    if 'VIDEO_WINDOW_POS' in os.environ:
        env['SDL_VIDEO_WINDOW_POS'] = os.environ['VIDEO_WINDOW_POS']

    try:
        with process_lock:
            # Don't capture output - let ffplay display directly
            # WSL/WSLg seems to have issues with subprocess PIPE
            current_process = subprocess.Popen(
                cmd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True  # Detach from parent
            )
            pid = current_process.pid

        # Give it a moment to start
        time.sleep(0.3)

        # Check if it's still running
        retcode = current_process.poll()
        if retcode is not None:
            return False, f"Process exited immediately with code {retcode}", None

        return True, f"Playing clip ({duration:.1f}s)", pid

    except Exception as e:
        return False, f"Error starting playback: {str(e)}", None


def stop_playback():
    """Stop any currently playing video."""
    global current_process

    with process_lock:
        if current_process:
            try:
                current_process.terminate()
                current_process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                current_process.kill()
                current_process.wait()
            except:
                pass
            finally:
                current_process = None


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "service": "video-playback",
        "playing": current_process is not None and current_process.poll() is None
    })


@app.route('/play', methods=['POST'])
def play():
    """
    Play a video clip.

    Request body:
    {
        "video_path": "/path/to/video.mkv",  // or just filename if in VIDEO_BASE
        "start": 120.0,
        "end": 128.0,
        "fullscreen": true  // optional, default true
    }
    """
    data = request.json

    if not data:
        return jsonify({"error": "Request body required"}), 400

    # Get parameters
    video_path = data.get('video_path')
    start = data.get('start')
    end = data.get('end')
    fullscreen = data.get('fullscreen', True)

    # Validate required fields
    if not video_path or start is None or end is None:
        return jsonify({
            "error": "Missing required fields: video_path, start, end"
        }), 400

    # If video_path is just a filename, prepend VIDEO_BASE
    if not video_path.startswith('/'):
        video_path = os.path.join(VIDEO_BASE, video_path)

    # Play the video
    success, message, pid = play_video(video_path, start, end, fullscreen)

    if success:
        return jsonify({
            "status": "playing",
            "message": message,
            "pid": pid,
            "duration": end - start
        })
    else:
        return jsonify({
            "status": "error",
            "message": message
        }), 500


@app.route('/stop', methods=['POST'])
def stop():
    """Stop current playback."""
    stop_playback()
    return jsonify({"status": "stopped"})


@app.route('/status', methods=['GET'])
def status():
    """Get current playback status."""
    is_playing = current_process is not None and current_process.poll() is None

    return jsonify({
        "playing": is_playing,
        "pid": current_process.pid if is_playing else None
    })


if __name__ == '__main__':
    print("🎬 Cinema-Chat Video Playback Service")
    print("=" * 50)
    print(f"📁 Video base directory: {VIDEO_BASE}")
    print(f"🌐 Starting server on http://0.0.0.0:5000")
    print()
    print("Endpoints:")
    print("  GET  /health  - Health check")
    print("  POST /play    - Play a video clip")
    print("  POST /stop    - Stop playback")
    print("  GET  /status  - Get playback status")
    print()
    print("Example:")
    print("  curl -X POST http://localhost:5000/play \\")
    print("    -H 'Content-Type: application/json' \\")
    print("    -d '{\"video_path\":\"hemo_the_magnificent.mp4.mkv\",\"start\":120,\"end\":128}'")
    print()

    # Run the server
    app.run(host='0.0.0.0', port=5000, debug=False)
