#!/usr/bin/env python3
"""
Video Playback Service — Persistent MPV with ASS subtitle overlays.

Uses a single long-lived MPV process with --idle mode and an IPC socket.
Plays clips via 'loadfile' commands and shows conversation subtitles via
ASS subtitle files (osd-overlay doesn't render on Pi DRM output).

The subtitle file is re-added after every loadfile since MPV resets tracks.

Usage:
    python3 video_playback_service_mpv.py

    curl -X POST http://localhost:5000/play \
      -H 'Content-Type: application/json' \
      -d '{"video_path":"test.mp4","start":0,"end":5}'
"""

from flask import Flask, request, jsonify
import subprocess
import os
import json
import socket
import threading
import time
import signal

app = Flask(__name__)

# Video base directory on Raspberry Pi
VIDEO_BASE = "/home/twistedtv/videos"
STATIC_VIDEO = os.path.join(VIDEO_BASE, "static.mp4")
MPV_SOCKET = "/tmp/mpv-socket"

# MPV display config
DRM_DEVICE = "/dev/dri/card1"
AUDIO_DEVICE = "alsa/hdmi:CARD=vc4hdmi0,DEV=0"

# Subtitle overlay
OVERLAY_ASS = "/tmp/twistedtv_overlay.ass"

# Global state
_mpv_process = None
_mpv_lock = threading.Lock()
_playing_content = False  # True when a clip is playing (vs static)
_overlay_active = False   # True when subtitle file has content


# ── MPV IPC ───────────────────────────────────────────────────────────────

def mpv_command(*args):
    """Send a JSON IPC command to MPV and return the response."""
    cmd = {"command": list(args)}
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(3.0)
        sock.connect(MPV_SOCKET)
        sock.sendall(json.dumps(cmd).encode() + b"\n")
        # Read response
        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break
        sock.close()
        if data:
            return json.loads(data.decode().strip().split("\n")[0])
        return None
    except Exception as e:
        print(f"MPV IPC error: {e}")
        return None


def mpv_set_property(name, value):
    """Set an MPV property via IPC."""
    return mpv_command("set_property", name, value)


def mpv_get_property(name):
    """Get an MPV property via IPC."""
    resp = mpv_command("get_property", name)
    if resp and "data" in resp:
        return resp["data"]
    return None


# ── Subtitle overlay (ASS file) ──────────────────────────────────────────

def _write_ass_file(transcript: str = "", captions: list = None):
    """
    Write an ASS subtitle file with conversation-style overlay.
    User transcript in cyan, movie dialogue in white.
    """
    header = (
        "[Script Info]\n"
        "Title: TwistedTV Overlay\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "PlayResX: 1920\n"
        "PlayResY: 1080\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: User,Sans,42,&H0000FFFF,&H000000FF,&H00000000,&H80000000,"
        "0,1,0,0,100,100,0,0,1,2,1,2,30,30,60,1\n"
        "Style: Movie,Sans,42,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "0,0,0,0,100,100,0,0,1,2,1,2,30,30,60,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )

    events = []
    if transcript:
        safe = transcript.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
        events.append(
            f"Dialogue: 0,0:00:00.00,9:00:00.00,User,,0,0,0,,> {safe}"
        )

    if captions:
        for cap in captions:
            text = cap if isinstance(cap, str) else cap.get("text", "")
            if text:
                safe = text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
                events.append(
                    f'Dialogue: 0,0:00:00.00,9:00:00.00,Movie,,0,0,0,,"{safe}"'
                )

    with open(OVERLAY_ASS, "w") as f:
        f.write(header)
        f.write("\n".join(events))
        f.write("\n")


def _load_subtitle():
    """Load (or reload) the ASS subtitle file into MPV."""
    # Remove any existing subtitle tracks first
    mpv_command("sub-remove")
    if _overlay_active and os.path.exists(OVERLAY_ASS):
        mpv_command("sub-add", OVERLAY_ASS, "select")
        mpv_set_property("sub-visibility", True)


def set_overlay(transcript: str = "", captions: list = None):
    """Write ASS file and load it as a subtitle track."""
    global _overlay_active
    _write_ass_file(transcript, captions)
    _overlay_active = True
    _load_subtitle()


def clear_overlay():
    """Remove the subtitle overlay."""
    global _overlay_active
    _overlay_active = False
    mpv_command("sub-remove")


# ── MPV lifecycle ─────────────────────────────────────────────────────────

def start_mpv():
    """Start MPV in idle mode with IPC socket."""
    global _mpv_process

    # Clean up any stale socket
    if os.path.exists(MPV_SOCKET):
        os.remove(MPV_SOCKET)

    # Kill any existing MPV
    subprocess.run(["pkill", "-9", "mpv"], check=False, timeout=2, capture_output=True)
    time.sleep(0.3)

    cmd = [
        "mpv",
        "--idle=yes",
        f"--input-ipc-server={MPV_SOCKET}",
        f"--drm-device={DRM_DEVICE}",
        f"--audio-device={AUDIO_DEVICE}",
        "--no-osc",
        "--no-osd-bar",
        "--fullscreen",
        "--force-seekable=yes",
        "--keep-open=no",
        "--osd-font-size=38",
        "--osd-margin-y=40",
    ]

    _mpv_process = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for IPC socket to appear
    for _ in range(30):
        if os.path.exists(MPV_SOCKET):
            print(f"MPV started (PID: {_mpv_process.pid}), IPC ready")
            return True
        time.sleep(0.1)

    print("Warning: MPV IPC socket did not appear within 3s")
    return False


def ensure_mpv():
    """Make sure MPV is running; restart if it died."""
    global _mpv_process
    with _mpv_lock:
        if _mpv_process is None or _mpv_process.poll() is not None:
            print("MPV not running, starting...")
            start_mpv()


def load_static():
    """Load the static/idle video (loops forever)."""
    global _playing_content
    _playing_content = False
    if os.path.exists(STATIC_VIDEO):
        mpv_command("loadfile", STATIC_VIDEO, "replace")
        mpv_set_property("loop-file", "inf")
        # Re-add subtitle after loadfile (which resets tracks)
        time.sleep(0.3)
        _load_subtitle()
        print("Loaded static video")
    else:
        print(f"Warning: static video not found at {STATIC_VIDEO}")


def play_clip(video_path, start_time, end_time):
    """Play a video clip via IPC loadfile."""
    global _playing_content

    ensure_mpv()

    # Resolve path
    is_url = video_path.startswith("http://") or video_path.startswith("https://")
    if not is_url and not os.path.isabs(video_path):
        video_path = os.path.join(VIDEO_BASE, video_path)

    if not is_url and not os.path.exists(video_path):
        return False, f"Video file not found: {video_path}", None

    # Load the clip with start/end options
    opts = f"start={start_time},end={end_time}"
    mpv_command("loadfile", video_path, "replace", opts)
    mpv_set_property("loop-file", "no")
    _playing_content = True

    # Re-add subtitle after loadfile (which resets tracks)
    time.sleep(0.3)
    _load_subtitle()

    print(f"Playing: {os.path.basename(video_path)} [{start_time}-{end_time}s]")

    # Monitor for clip end → return to static
    def _wait_for_end():
        global _playing_content
        # Poll until idle (clip finished)
        time.sleep(0.5)  # Let playback start
        while _playing_content:
            idle = mpv_get_property("idle-active")
            if idle:
                print("Clip finished, loading static")
                _playing_content = False
                load_static()
                return
            time.sleep(0.5)

    threading.Thread(target=_wait_for_end, daemon=True).start()

    pid = _mpv_process.pid if _mpv_process else None
    return True, f"Playing {os.path.basename(video_path)} ({start_time}s - {end_time}s)", pid


# ── Flask endpoints ───────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    is_running = _mpv_process is not None and _mpv_process.poll() is None
    return jsonify({
        "status": "ok",
        "service": "video-playback",
        "mpv_running": is_running,
        "playing_content": _playing_content,
    })


@app.route("/status", methods=["GET"])
def status():
    is_running = _mpv_process is not None and _mpv_process.poll() is None
    return jsonify({
        "playing": is_running,
        "pid": _mpv_process.pid if is_running else None,
        "is_static": not _playing_content,
    })


@app.route("/play", methods=["POST"])
def play():
    """
    Play a video clip with optional subtitle overlay.

    Request JSON:
    {
        "video_path": "test.mp4",
        "start": 0,
        "end": 5,
        "fullscreen": true,
        "transcript": "what the user said",
        "captions": [{"text": "movie dialogue", "start": 1.0, "end": 3.0}]
    }
    """
    data = request.json
    if not data:
        return jsonify({"error": "No JSON data provided"}), 400

    video_path = data.get("video_path")
    start_time = data.get("start", 0)
    end_time = data.get("end")

    if not video_path:
        return jsonify({"error": "video_path is required"}), 400
    if end_time is None:
        return jsonify({"error": "end time is required"}), 400

    # Build and set subtitle overlay (written before play so it's ready to re-add)
    transcript = data.get("transcript", "")
    captions = data.get("captions", [])
    if transcript or captions:
        set_overlay(transcript, captions)

    # Play the clip
    success, message, pid = play_clip(video_path, start_time, end_time)

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
        return jsonify({"status": "error", "message": message}), 500


@app.route("/overlay", methods=["POST"])
def overlay():
    """
    Update the text overlay without changing video.
    Used to show user transcript immediately (before clip plays).

    Request JSON:
    {
        "transcript": "what the user said",
        "captions": [...]
    }
    """
    data = request.json or {}
    transcript = data.get("transcript", "")
    captions = data.get("captions", [])

    ensure_mpv()

    if transcript or captions:
        set_overlay(transcript, captions)
        return jsonify({"status": "ok", "overlay": "set"})
    else:
        clear_overlay()
        return jsonify({"status": "ok", "overlay": "cleared"})


@app.route("/stop", methods=["POST"])
def stop():
    """Stop current clip and return to static, clear subtitles."""
    global _playing_content
    _playing_content = False
    clear_overlay()
    load_static()
    return jsonify({"status": "stopped", "message": "Showing static"})


def shutdown_handler(signum, frame):
    """Clean shutdown."""
    print("Shutting down...")
    if _mpv_process:
        _mpv_process.terminate()
        try:
            _mpv_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _mpv_process.kill()
    if os.path.exists(MPV_SOCKET):
        os.remove(MPV_SOCKET)
    if os.path.exists(OVERLAY_ASS):
        os.remove(OVERLAY_ASS)
    exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    print("🎬 TwistedTV Video Playback Service (MPV IPC)")
    print("=" * 50)
    print(f"📁 Video base: {VIDEO_BASE}")
    print(f"🔌 IPC socket: {MPV_SOCKET}")
    print()

    # Start persistent MPV
    start_mpv()
    load_static()

    print()
    print("Endpoints:")
    print("  POST /play     - Play a video clip (with subtitles)")
    print("  POST /overlay  - Update text overlay")
    print("  POST /stop     - Stop and show static")
    print("  GET  /health   - Health check")
    print("  GET  /status   - Playback status")
    print()

    app.run(host="0.0.0.0", port=5000, debug=False)
