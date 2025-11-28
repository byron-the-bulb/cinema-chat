#!/usr/bin/env python3
"""
Daily.co Client for Raspberry Pi using PyAudio
Based EXACTLY on official Daily Python demo:
https://github.com/daily-co/daily-python/blob/main/demos/pyaudio/record_and_play.py

This uses PyAudio callback (like the official demo) instead of ALSA async loop.
"""

import asyncio
import os
import sys
import json
import logging
import httpx
import threading
import time
import pyaudio
from daily import Daily, CallClient, EventHandler
from typing import Optional

# Configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://192.168.1.143:8765/api")
VIDEO_SERVICE_URL = os.getenv("VIDEO_SERVICE_URL", "http://localhost:5000")
AUDIO_CONFIG_FILE = "/home/twistedtv/audio_device.conf"

# Audio settings (44.1kHz native device rate - Daily will resample)
SAMPLE_RATE = 44100
NUM_CHANNELS = 1

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_audio_device_index() -> Optional[int]:
    """Get PyAudio device index for configured audio device"""
    try:
        if os.path.exists(AUDIO_CONFIG_FILE):
            with open(AUDIO_CONFIG_FILE, 'r') as f:
                device_name = f.read().strip()
                if device_name and device_name.startswith("plughw:"):
                    # Extract card number from plughw:1,0
                    card_str = device_name.split(':')[1].split(',')[0]
                    card_num = int(card_str)

                    # Find PyAudio device with matching card
                    p = pyaudio.PyAudio()
                    try:
                        for i in range(p.get_device_count()):
                            info = p.get_device_info_by_index(i)
                            if info['maxInputChannels'] > 0:  # Input device
                                name = info['name']
                                # Match either "hw:1,0" or "card 1" in the name
                                if f"hw:{card_num}" in name or f"card {card_num}" in name.lower():
                                    logger.info(f"Found PyAudio device {i}: {name}")
                                    return i
                    finally:
                        p.terminate()
    except Exception as e:
        logger.warning(f"Could not read audio config: {e}")

    logger.info("Using default PyAudio device")
    return None


class PyAudioApp(EventHandler):
    """PyAudio-based Daily client (following official demo pattern)"""

    def __init__(self, backend_url: str, video_service_url: str, sample_rate: int, num_channels: int):
        super().__init__()
        self.backend_url = backend_url
        self.video_service_url = video_service_url
        self.app_quit = False
        self.sample_rate = sample_rate
        self.num_channels = num_channels
        self.room_url = None
        self.token = None

        # Create virtual microphone with non_blocking=True (CRITICAL!)
        logger.info("Creating virtual microphone...")
        self.virtual_mic = Daily.create_microphone_device(
            "my-mic",
            sample_rate=sample_rate,
            channels=num_channels,
            non_blocking=True  # CRITICAL: Must be non-blocking
        )
        logger.info("✅ Virtual microphone created (non_blocking=True)")

        # We don't need virtual speaker for this use case
        # self.virtual_speaker = Daily.create_speaker_device(...)

        # Initialize PyAudio
        self.pyaudio = pyaudio.PyAudio()

        # Get device index
        device_index = get_audio_device_index()

        # Open input stream with callback (like official demo)
        logger.info(f"Opening PyAudio input stream (device_index={device_index})...")
        self.input_stream = self.pyaudio.open(
            format=pyaudio.paInt16,
            channels=num_channels,
            rate=sample_rate,
            input=True,
            input_device_index=device_index,
            stream_callback=self.on_input_stream,
        )
        logger.info("✅ PyAudio input stream opened")

        # Create Daily call client
        self.client = CallClient(event_handler=self)

        # Configure subscription (don't need camera or speaker for now)
        self.client.update_subscription_profiles(
            {"base": {"camera": "unsubscribed", "microphone": "subscribed"}}
        )

    def on_input_stream(self, in_data, frame_count, time_info, status):
        """PyAudio callback - called when audio data is available"""
        if self.app_quit:
            return None, pyaudio.paAbort

        # Write raw int16 PCM data directly to Daily virtual microphone
        # (Daily will handle conversion internally)
        self.virtual_mic.write_frames(in_data)

        return None, pyaudio.paContinue

    def on_call_state_updated(self, state):
        """Called when call state changes"""
        logger.info(f"📞 Call state: {state}")

        if state == "joined":
            logger.info("✅ Joined Daily.co room")
            logger.info("🎤 PyAudio streaming microphone to Daily")

    def on_participant_joined(self, participant):
        """Called when participant joins"""
        username = participant.get("user_name", participant.get("id", 'Unknown'))
        logger.info(f"🤖 Participant joined: {username}")

    def on_participant_left(self, participant, reason=None):
        """Called when participant leaves"""
        username = participant.get("user_name", participant.get("id", 'Unknown'))
        logger.info(f"Participant left: {username}")

    def on_app_message(self, message, sender):
        """Handle app messages from bot"""
        try:
            # Parse message
            if isinstance(message, str):
                msg_data = json.loads(message)
            else:
                msg_data = message

            # Unwrap server-message envelopes
            if msg_data.get("type") == "server-message" and "data" in msg_data:
                msg_data = msg_data["data"]

            # Handle video playback commands
            if msg_data.get("type") == "video-playback-command" and msg_data.get("action") == "play":
                logger.info(f"🎬 Playing video: {msg_data.get('video_path')}")
                try:
                    response = httpx.post(
                        f"{self.video_service_url}/play",
                        json={
                            "video_path": msg_data.get("video_path"),
                            "start": msg_data.get("start", 0),
                            "end": msg_data.get("end", 10),
                            "fullscreen": msg_data.get("fullscreen", True)
                        },
                        timeout=5.0
                    )
                    if response.status_code == 200:
                        logger.info("✅ Video playback started")
                    else:
                        logger.error(f"❌ Video playback failed: {response.text}")
                except Exception as e:
                    logger.error(f"❌ Error calling video service: {e}")
        except Exception as e:
            logger.error(f"Error handling app message: {e}")

    def on_error(self, error):
        """Called on error"""
        logger.error(f"❌ Daily.co error: {error}")

    async def connect_to_backend(self):
        """Connect to backend and get room URL"""
        logger.info("=" * 60)
        logger.info("🎬 Cinema Chat - Pi Client (PyAudio)")
        logger.info("=" * 60)
        logger.info(f"Backend: {self.backend_url}")
        logger.info(f"Video Service: {self.video_service_url}")
        logger.info("=" * 60)

        try:
            logger.info("Connecting to backend...")
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.backend_url}/connect",
                    json={"config": []},
                    timeout=30.0
                )

            if response.status_code != 200:
                raise Exception(f"Backend returned {response.status_code}: {response.text}")

            data = response.json()
            self.room_url = data.get("room_url")
            self.token = data.get("token")

            if not self.room_url:
                raise Exception("No room URL returned from backend")

            logger.info(f"✅ Got room URL: {self.room_url}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to connect to backend: {e}")
            return False

    def run(self, meeting_url):
        """Join Daily room and run (following official demo pattern)"""
        logger.info(f"Joining room: {meeting_url}")

        # Join with virtual microphone (following official demo exactly)
        self.client.join(
            meeting_url,
            meeting_token=self.token if self.token else None,
            client_settings={
                "inputs": {
                    "camera": False,
                    "microphone": {
                        "isEnabled": True,
                        "settings": {
                            "deviceId": "my-mic",  # Use device NAME string
                        },
                    },
                },
                "publishing": {
                    "microphone": {
                        "isPublishing": True,  # Explicitly enable publishing
                        "sendSettings": {
                            "channelConfig": "mono",  # Match our NUM_CHANNELS
                        },
                    }
                },
            }
        )

        logger.info("✅ Client running. Press Ctrl+C to stop.")
        logger.info("🎤 Audio is being captured and sent to backend via Daily")

        # Keep running (blocking)
        try:
            while not self.app_quit:
                time.sleep(0.1)
        except KeyboardInterrupt:
            logger.info("Shutting down...")

    def leave(self):
        """Clean shutdown"""
        self.app_quit = True
        self.client.leave()
        self.client.release()

        while self.input_stream.is_active():
            time.sleep(0.1)

        self.input_stream.close()
        self.pyaudio.terminate()
        logger.info("✅ Cleanup complete")


async def main():
    """Main entry point"""
    backend_url = os.getenv("BACKEND_URL", BACKEND_URL)
    video_service_url = os.getenv("VIDEO_SERVICE_URL", VIDEO_SERVICE_URL)

    if not backend_url:
        logger.error("❌ No backend URL configured")
        logger.error("Set BACKEND_URL environment variable")
        sys.exit(1)

    # Initialize Daily
    Daily.init()

    # Create PyAudio app
    app = PyAudioApp(backend_url, video_service_url, SAMPLE_RATE, NUM_CHANNELS)

    # Connect to backend to get room URL
    if not await app.connect_to_backend():
        logger.error("Failed to connect to backend")
        return

    # Run (blocking call)
    try:
        app.run(app.room_url)
    except KeyboardInterrupt:
        logger.info("Ctrl-C detected. Exiting!")
    finally:
        app.leave()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Exiting...")
