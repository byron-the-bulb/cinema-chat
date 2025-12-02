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
import re

app = Flask(__name__)

# Global state
current_process = None  # Currently playing video (content or static)
is_playing_static = False  # Track if we're showing static
process_lock = threading.Lock()

# Video base directory on Raspberry Pi
VIDEO_BASE = "/home/twistedtv/videos"


def start_static_if_nothing_playing():
    """Start static if nothing else is playing."""
    global current_process, is_playing_static

    with process_lock:
        # Check if anything is currently playing
        if current_process and current_process.poll() is None:
            # Something is already playing, don't start static
            return

        # Nothing playing, start static
        STATIC_VIDEO = "/home/twistedtv/videos/static.mp4"
        # VLC command for static loop
        # --play-and-exit not used here because we want infinite loop
        cmd = [
            "cvlc",
            "--fullscreen",
            "--no-video-title-show",
            "--no-osd",
            "--quiet",
            "--loop",
            "--aout=alsa",
            "--alsa-audio-device=hdmi:CARD=vc4hdmi0,DEV=0",
            STATIC_VIDEO
        ]

        try:
            log_file = open('/home/twistedtv/vlc_static.log', 'w')
            current_process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT
            )
            is_playing_static = True
            print(f"Started static (PID: {current_process.pid})")
        except Exception as e:
            print(f"Failed to start static: {e}")


def monitor_playback():
    """Monitor current playback. When it finishes, start static."""
    global current_process, is_playing_static

    if current_process:
        proc_to_monitor = current_process
        was_static = is_playing_static
        proc_to_monitor.wait()  # Wait for video to finish

        with process_lock:
            if current_process == proc_to_monitor:
                current_process = None
                is_playing_static = False

                if not was_static:
                    print("Content video finished, starting static...")
                    # Start static in background thread to avoid blocking
                    threading.Thread(target=start_static_if_nothing_playing, daemon=True).start()


def play_video(video_path, start_time, end_time, fullscreen=True):
    """
    Play a video clip. Stops static if it's playing.

    Args:
        video_path: Path to video file (relative to VIDEO_BASE or absolute)
        start_time: Start time in seconds
        end_time: End time in seconds
        fullscreen: Whether to play fullscreen

    Returns:
        (success, message, pid)
    """
    global current_process, is_playing_static

    # Resolve video path
    is_url = video_path.startswith('http://') or video_path.startswith('https://')

    if not is_url and not os.path.isabs(video_path):
        video_path = os.path.join(VIDEO_BASE, video_path)

    # Validate file exists (skip for URLs)
    if not is_url and not os.path.exists(video_path):
        return False, f"Video file not found: {video_path}", None

    # Stop any currently playing video (including static)
    # Use pkill to ensure we kill the actual vlc process, not just the shell
    try:
        subprocess.run(['pkill', '-9', 'vlc'], check=False, timeout=2)
        time.sleep(0.2)  # Brief delay to ensure process is dead
    except Exception as e:
        print(f"Error killing vlc: {e}")

    with process_lock:
        if current_process:
            print(f"Stopped previous playback (was_static: {is_playing_static})")
            current_process = None
            is_playing_static = False

    # Build VLC command for content
    # Calculate duration (VLC uses run-time parameter)
    duration = end_time - start_time
    log_file_path = f'/home/twistedtv/vlc_{int(time.time())}.log'

    cmd = [
        "cvlc",
        "--play-and-exit",
        "--fullscreen",
        "--no-video-title-show",
        "--no-osd",
        "--quiet",
        f"--start-time={start_time}",
        f"--run-time={duration}",
        "--aout=alsa",
        "--alsa-audio-device=hdmi:CARD=vc4hdmi0,DEV=0",
        video_path
    ]

    try:
        # Start the content video
        with process_lock:
            log_file = open(log_file_path, 'w')
            current_process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT
            )
            is_playing_static = False

        pid = current_process.pid
        print(f"Playing content (PID: {pid})")

        # Start background thread to monitor playback
        monitor_thread = threading.Thread(
            target=monitor_playback,
            daemon=True
        )
        monitor_thread.start()

        return True, f"Playing {os.path.basename(video_path)} ({start_time}s - {end_time}s)", pid

    except Exception as e:
        return False, f"Failed to start playback: {str(e)}", None


def stop_playback():
    """Stop current playback and start static."""
    global current_process, is_playing_static

    with process_lock:
        if current_process and current_process.poll() is None:
            try:
                current_process.terminate()
                current_process.wait(timeout=1)
            except Exception:
                try:
                    current_process.kill()
                except Exception:
                    pass
            current_process = None
            is_playing_static = False

    # Start static after stopping
    start_static_if_nothing_playing()
    return True, "Playback stopped, showing static"


def stop_all():
    """Stop ALL playback including static (for shutdown only)."""
    global current_process, is_playing_static

    with process_lock:
        # Kill all vlc processes
        try:
            subprocess.run(['pkill', '-9', 'vlc'], check=False, timeout=2)
        except Exception:
            pass

        current_process = None
        is_playing_static = False

        return True, "All playback stopped"


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    is_playing = current_process is not None and current_process.poll() is None
    return jsonify({
        "status": "ok",
        "service": "video-playback-vlc",
        "playing": is_playing,
        "is_static": is_playing_static,
    })


@app.route('/status', methods=['GET'])
def status():
    """Get playback status."""
    is_playing = current_process is not None and current_process.poll() is None
    return jsonify({
        "playing": is_playing,
        "pid": current_process.pid if is_playing else None,
        "is_static": is_playing_static,
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



@app.route('/set-audio-device', methods=['POST'])
def set_audio_device():
    """
    Set the audio device for Pi Daily client.

    Request JSON:
    {
        "device_id": "hw:3,0"
    }
    """
    data = request.json

    if not data:
        return jsonify({"error": "No JSON data provided"}), 400

    device_id = data.get('device_id')

    if not device_id:
        return jsonify({"error": "device_id is required"}), 400

    # Validate ALSA device ID format
    if not re.match(r'^hw:\d+,\d+$', device_id):
        return jsonify({
            "error": "Invalid device_id format. Expected format: hw:CARD,DEVICE (e.g., hw:1,0)"
        }), 400

    # Write to config file
    config_file = '/home/twistedtv/audio_device.conf'
    try:
        with open(config_file, 'w') as f:
            f.write(device_id)

        print(f"Set Pi audio device to: {device_id}")

        return jsonify({
            "success": True,
            "message": f"Audio device set to {device_id}",
            "device_id": device_id
        })
    except Exception as e:
        return jsonify({
            "error": str(e),
            "success": False
        }), 500


if __name__ == '__main__':
    print("🎬 Cinema-Chat Video Playback Service (VLC)")
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
    print("🔄 Starting static (nothing else playing)...")
    start_static_if_nothing_playing()
    print()

    app.run(host='0.0.0.0', port=5000, debug=False)
