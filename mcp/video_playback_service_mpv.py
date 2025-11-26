#!/usr/bin/env python3
"""
Simple Video Playback Service (VLC version for Raspberry Pi)

A lightweight HTTP server that plays video clips on the TV/HDMI output using VLC.
This runs on the Raspberry Pi and receives playback requests.

Usage:
    python3 video_playback_service_vlc.py

    # Then from anywhere:
    curl -X POST http://192.168.1.201:5000/play \
      -H 'Content-Type: application/json' \
      -d '{"video_path": "test.mp4", "start": 0, "end": 5}'
"""

from flask import Flask, request, jsonify
import subprocess
import os
import threading
import time
import signal

app = Flask(__name__)

# Global state
current_process = None
process_lock = threading.Lock()

# Video base directory on Raspberry Pi
VIDEO_BASE = "/home/twistedtv/videos"


def play_static_directly():
    """Play static video directly (not via script) in infinite loop."""
    global current_process

    STATIC_VIDEO = "/home/twistedtv/videos/static.mp4"

    # Build MPV command to play static in loop
    cmd = [
        "bash", "-c",
        f"mpv --drm-device=/dev/dri/card1 --audio-device=alsa/hdmi:CARD=vc4hdmi0,DEV=0 --no-osc --no-osd-bar --loop=inf --fullscreen {STATIC_VIDEO} > /dev/null 2>&1"
    ]

    try:
        with process_lock:
            current_process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL
            )
        print(f"Started static playback directly (PID: {current_process.pid})")
    except Exception as e:
        print(f"Failed to start static playback: {e}")


def monitor_playback_and_restart_static():
    """Monitor video playback and restart static when it finishes."""
    global current_process

    if current_process:
        current_process.wait()  # Wait for video to finish
        time.sleep(0.5)  # Brief delay

        with process_lock:
            current_process = None

        # Restart static playback directly
        play_static_directly()
        print("Video finished, restarted static playback")


def play_video(video_path, start_time, end_time, fullscreen=True):
    """
    Play a video clip using MPV.

    Args:
        video_path: Path to video file (relative to VIDEO_BASE or absolute)
        start_time: Start time in seconds
        end_time: End time in seconds
        fullscreen: Whether to play fullscreen

    Returns:
        (success, message, pid)
    """
    global current_process

    # Resolve video path
    # Check if it's a URL (http:// or https://)
    is_url = video_path.startswith('http://') or video_path.startswith('https://')

    if not is_url and not os.path.isabs(video_path):
        video_path = os.path.join(VIDEO_BASE, video_path)

    # Validate file exists (skip for URLs)
    if not is_url and not os.path.exists(video_path):
        return False, f"Video file not found: {video_path}", None

    # Stop any current playback (including static)
    stop_playback()

    # Calculate duration
    duration = end_time - start_time

    # Build mpv command with sudo for DRM access
    # Let mpv auto-detect the correct connector on card1
    log_file = f'/home/twistedtv/mpv_{int(time.time())}.log'
    cmd = [
        "bash", "-c",
        f"mpv --drm-device=/dev/dri/card1 --audio-device=alsa/hdmi:CARD=vc4hdmi0,DEV=0 --no-osc --no-osd-bar --force-seekable=yes --start={start_time} --end={end_time} --fullscreen {video_path} > {log_file} 2>&1"
    ]

    try:
        # Start the video player process
        with process_lock:
            current_process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL
            )

        pid = current_process.pid

        # Start background thread to monitor playback and restart static
        monitor_thread = threading.Thread(
            target=monitor_playback_and_restart_static,
            daemon=True
        )
        monitor_thread.start()

        return True, f"Playing {os.path.basename(video_path)} ({start_time}s - {end_time}s)", pid

    except Exception as e:
        return False, f"Failed to start playback: {str(e)}", None


def stop_playback():
    """Stop any currently running video playback (including static)."""
    global current_process

    with process_lock:
        # Kill all mpv processes (both content and static)
        try:
            subprocess.run(['pkill', '-9', 'mpv'], check=False, timeout=2)
        except Exception:
            pass

        # Clean up our tracked process
        if current_process:
            try:
                if current_process.poll() is None:
                    current_process.terminate()
                    current_process.wait(timeout=1)
            except Exception:
                pass
            current_process = None

        return True, "Playback stopped"


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    is_playing = current_process is not None and current_process.poll() is None
    return jsonify({
        "status": "ok",
        "service": "video-playback",
        "playing": is_playing,
    })


@app.route('/status', methods=['GET'])
def status():
    """Get playback status."""
    is_playing = current_process is not None and current_process.poll() is None
    return jsonify({
        "playing": is_playing,
        "pid": current_process.pid if is_playing else None,
    })


@app.route('/play', methods=['POST'])
def play():
    """
    Play a video clip.

    Request JSON:
    {
        "video_path": "test.mp4",     # Relative to VIDEO_BASE or absolute path
        "start": 0,                    # Start time in seconds
        "end": 5,                      # End time in seconds
        "fullscreen": true             # Optional, default true
    }
    """
    data = request.json

    if not data:
        return jsonify({"error": "No JSON data provided"}), 400

    video_path = data.get('video_path')
    start_time = data.get('start', 0)
    end_time = data.get('end')
    fullscreen = data.get('fullscreen', True)

    if not video_path:
        return jsonify({"error": "video_path is required"}), 400

    if end_time is None:
        return jsonify({"error": "end time is required"}), 400

    success, message, pid = play_video(video_path, start_time, end_time, fullscreen)

    if success:
        return jsonify({
            "status": "playing",
            "message": message,
            "pid": pid,
            "video": os.path.basename(video_path),
            "start": start_time,
            "end": end_time,
        })
    else:
        return jsonify({
            "status": "error",
            "message": message,
        }), 500


@app.route('/stop', methods=['POST'])
def stop():
    """Stop current video playback."""
    success, message = stop_playback()

    return jsonify({
        "status": "stopped" if success else "error",
        "message": message,
    })


if __name__ == '__main__':
    print("🎬 Cinema-Chat Video Playback Service (MPV)")
    print("=" * 50)
    print(f"📁 Video base directory: {VIDEO_BASE}")
    print("🌐 Starting server on http://0.0.0.0:5000")
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
    print("    -d '{\"video_path\":\"test.mp4\",\"start\":0,\"end\":5}'")
    print()
    print("⚠️  Static playback will start with first video request")
    print()

    app.run(host='0.0.0.0', port=5000, debug=False)
