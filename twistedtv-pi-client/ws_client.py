#!/usr/bin/env python3
"""
TwistedTV Pi WebSocket Client — Direct LAN audio streaming.

Replaces the Daily.co client with a simple WebSocket connection
to the server on the same LAN. Streams raw PCM audio and receives
playback commands.

Usage:
    python ws_client.py [--server ws://192.168.1.106:8765/ws/audio] [--audio-device hw:1,0]
"""

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time

import alsaaudio
import httpx
import websocket  # websocket-client library

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ws-client")

# Audio constants (must match server expectations)
SAMPLE_RATE = 16000
CHANNELS = 1
FORMAT = alsaaudio.PCM_FORMAT_S16_LE
PERIOD_SIZE = 160  # 10ms at 16kHz

# Default URLs
DEFAULT_SERVER_URL = os.getenv("SERVER_WS_URL", "ws://192.168.1.106:8765/ws/audio")
DEFAULT_VIDEO_SERVICE = os.getenv("VIDEO_SERVICE_URL", "http://localhost:5000")


class AudioCaptureThread(threading.Thread):
    """Captures audio from ALSA device and sends via WebSocket."""

    def __init__(self, ws, device: str = "default"):
        super().__init__(daemon=True)
        self.ws = ws
        self.device = device
        self.running = True

    def run(self):
        logger.info(f"Audio capture starting on device: {self.device}")

        try:
            mic = alsaaudio.PCM(
                alsaaudio.PCM_CAPTURE,
                alsaaudio.PCM_NORMAL,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                format=FORMAT,
                periodsize=PERIOD_SIZE,
                device=self.device,
            )
        except alsaaudio.ALSAAudioError as e:
            logger.error(f"Failed to open audio device '{self.device}': {e}")
            logger.info("Available devices: %s", alsaaudio.pcms(alsaaudio.PCM_CAPTURE))
            return

        logger.info("Audio capture started")

        while self.running:
            try:
                length, data = mic.read()
                if length > 0 and self.ws.sock and self.ws.sock.connected:
                    self.ws.send(data, opcode=websocket.ABNF.OPCODE_BINARY)
            except alsaaudio.ALSAAudioError as e:
                logger.error(f"Audio read error: {e}")
                time.sleep(0.1)
            except Exception as e:
                if self.running:
                    logger.error(f"Send error: {e}")
                break

        logger.info("Audio capture stopped")

    def stop(self):
        self.running = False


def play_video(video_service_url: str, video_path: str, start: float, end: float, fullscreen: bool = True):
    """Send play command to the local video playback service (with retry for startup race)."""
    max_retries = 5
    for attempt in range(1, max_retries + 1):
        try:
            resp = httpx.post(
                f"{video_service_url}/play",
                json={
                    "video_path": video_path,
                    "start": start,
                    "end": end,
                    "fullscreen": fullscreen,
                },
                timeout=5.0,
            )
            if resp.status_code == 200:
                result = resp.json()
                logger.info(f"Playing: {os.path.basename(video_path)} [{start}-{end}s] (pid={result.get('pid')})")
                return
            else:
                logger.error(f"Play failed ({resp.status_code}): {resp.text}")
                return
        except httpx.ConnectError:
            if attempt < max_retries:
                logger.warning(f"Video service not ready (attempt {attempt}/{max_retries}), retrying in 1s...")
                time.sleep(1)
            else:
                logger.error(f"Video service unreachable after {max_retries} attempts")
        except Exception as e:
            logger.error(f"Play request failed: {e}")
            return


def detect_audio_device() -> str:
    """Auto-detect the best audio input device."""
    # Check environment first
    env_device = os.getenv("AUDIO_DEVICE")
    if env_device:
        return env_device

    # Check config file
    config_path = os.path.expanduser("~/audio_device.conf")
    if os.path.exists(config_path):
        with open(config_path) as f:
            for line in f:
                if line.startswith("AUDIO_DEVICE="):
                    return line.split("=", 1)[1].strip()

    # Try common devices
    capture_devices = alsaaudio.pcms(alsaaudio.PCM_CAPTURE)
    logger.info(f"Available capture devices: {capture_devices}")

    # Prefer USB audio devices
    for dev in capture_devices:
        if "USB" in dev.upper() or "hw:1" in dev:
            return dev

    return "default"


def main():
    parser = argparse.ArgumentParser(description="TwistedTV Pi WebSocket Client")
    parser.add_argument("--server", type=str, default=DEFAULT_SERVER_URL, help="WebSocket server URL")
    parser.add_argument("--audio-device", type=str, default=None, help="ALSA audio device (e.g., hw:1,0)")
    parser.add_argument("--video-service", type=str, default=DEFAULT_VIDEO_SERVICE, help="Video playback service URL")
    args = parser.parse_args()

    audio_device = args.audio_device or detect_audio_device()
    logger.info(f"Audio device: {audio_device}")
    logger.info(f"Server: {args.server}")
    logger.info(f"Video service: {args.video_service}")

    audio_thread = None
    ws = None
    shutdown = threading.Event()

    def on_message(ws_conn, message):
        """Handle JSON messages from the server."""
        try:
            msg = json.loads(message)
            msg_type = msg.get("type")

            if msg_type == "play":
                logger.info(f"▶ Play command: {msg.get('video_path')}")
                play_video(
                    args.video_service,
                    msg.get("video_path", ""),
                    msg.get("start", 0),
                    msg.get("end", 10),
                    msg.get("fullscreen", True),
                )

            elif msg_type == "transcript":
                logger.info(f"📝 Transcript: {msg.get('text')}")

            elif msg_type == "status":
                logger.info(f"📊 Status: {msg.get('message')}")

            elif msg_type == "timing":
                logger.info(
                    f"⏱ Pipeline: {msg.get('total_secs')}s total "
                    f"(stt={msg.get('stt_secs')}s, search={msg.get('search_secs')}s)"
                )

            elif msg_type == "error":
                logger.error(f"Server error: {msg.get('message')}")

            elif msg_type == "pong":
                pass  # Heartbeat response

        except json.JSONDecodeError:
            logger.warning(f"Non-JSON message: {message[:100]}")

    def on_open(ws_conn):
        nonlocal audio_thread
        logger.info("Connected to server")
        audio_thread = AudioCaptureThread(ws_conn, audio_device)
        audio_thread.start()

    def on_close(ws_conn, close_status, close_msg):
        nonlocal audio_thread
        logger.info(f"Disconnected (status={close_status}, msg={close_msg})")
        if audio_thread:
            audio_thread.stop()
            audio_thread = None

    def on_error(ws_conn, error):
        logger.error(f"WebSocket error: {error}")

    def signal_handler(signum, frame):
        logger.info("Shutting down...")
        if audio_thread:
            audio_thread.stop()
        if ws:
            ws.close()
        shutdown.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Connect with auto-reconnect
    while not shutdown.is_set():
        try:
            logger.info(f"Connecting to {args.server}...")
            ws = websocket.WebSocketApp(
                args.server,
                on_message=on_message,
                on_open=on_open,
                on_close=on_close,
                on_error=on_error,
            )
            ws.run_forever(ping_interval=10, ping_timeout=5)
        except Exception as e:
            logger.error(f"Connection failed: {e}")

        if not shutdown.is_set():
            logger.info("Reconnecting in 3 seconds...")
            time.sleep(3)

    logger.info("Client exited")


if __name__ == "__main__":
    main()
