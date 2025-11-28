#!/usr/bin/env python3
"""
Pi Daily.co Client with Custom Audio Track from ALSA Device - FIXED
"""

import asyncio
import os
import sys
import json
import logging
import httpx
import alsaaudio
import numpy as np
from daily import Daily, CallClient, EventHandler
from typing import Optional

# Configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://192.168.1.143:8765/api")
VIDEO_SERVICE_URL = os.getenv("VIDEO_SERVICE_URL", "http://localhost:5000")
AUDIO_CONFIG_FILE = "/home/twistedtv/audio_device.conf"

# Audio settings to match Whisper expectations (16kHz mono)
SAMPLE_RATE = 16000
CHANNELS = 1
PERIOD_SIZE = 160  # 10ms at 16kHz

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_audio_device() -> str:
    """Get the configured audio device"""
    try:
        if os.path.exists(AUDIO_CONFIG_FILE):
            with open(AUDIO_CONFIG_FILE, 'r') as f:
                device = f.read().strip()
                if device:
                    logger.info(f"Using audio device from config: {device}")
                    return device
    except Exception as e:
        logger.warning(f"Could not read audio config: {e}")

    device = os.getenv("AUDIO_DEVICE", "hw:3,0")
    logger.info(f"Using audio device from environment: {device}")
    return device


class ALSAAudioSource:
    """Captures audio from ALSA device and provides frames"""

    def __init__(self, device: str, microphone_device):
        self.device = device
        self.running = False
        self.mic_device = None
        self.daily_mic = microphone_device

        logger.info(f"Opening ALSA device: {device}")
        try:
            # Open ALSA PCM device for capture
            self.mic_device = alsaaudio.PCM(
                alsaaudio.PCM_CAPTURE,
                alsaaudio.PCM_NONBLOCK,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                format=alsaaudio.PCM_FORMAT_S16_LE,
                periodsize=PERIOD_SIZE,
                device=device
            )

            logger.info(f"✅ ALSA device opened: {SAMPLE_RATE}Hz, {CHANNELS} ch")
        except Exception as e:
            logger.error(f"Failed to open ALSA device: {e}")
            raise

    async def read_frames(self):
        """Read audio from ALSA and write to Daily virtual microphone"""
        self.running = True
        logger.info("🎤 Starting audio capture loop")

        try:
            while self.running:
                try:
                    # Read audio data from ALSA
                    length, data = self.mic_device.read()

                    if length > 0:
                        # Convert bytes to numpy array (16-bit signed integers)
                        audio_array = np.frombuffer(data, dtype=np.int16)

                        # Daily expects float32 audio in range [-1, 1]
                        audio_float = audio_array.astype(np.float32) / 32768.0

                        # Write to Daily virtual microphone
                        self.daily_mic.write_frames(audio_float.tobytes())
                    else:
                        # No data available, sleep briefly
                        await asyncio.sleep(0.001)

                except Exception as e:
                    logger.error(f"Error reading audio: {e}")
                    await asyncio.sleep(0.01)

        except Exception as e:
            logger.error(f"Audio capture loop error: {e}")
        finally:
            logger.info("Audio capture stopped")

    def stop(self):
        """Stop audio capture"""
        self.running = False
        if self.mic_device:
            self.mic_device.close()


class CinemaRTVIClient(EventHandler):
    """RTVI-compatible Daily.co client"""

    def __init__(self, backend_url: str, video_service_url: str):
        super().__init__()
        self.backend_url = backend_url
        self.video_service_url = video_service_url
        self.http_client = httpx.AsyncClient()
        self.room_url: Optional[str] = None
        self.token: Optional[str] = None
        self.call_client = None
        self.bot_participant_id = None
        self.audio_source = None
        self.audio_task = None

    async def connect_to_backend(self):
        """Connect to backend and get room info"""
        logger.info("="*60)
        logger.info("🎬 Cinema Chat - Pi RTVI Client (Fixed Audio)")
        logger.info("="*60)

        try:
            response = await self.http_client.post(
                f"{self.backend_url}/connect",
                json={"config": [{"service": "tts", "options": [{"name": "provider", "value": "cartesia"}]}]},
                timeout=30.0
            )

            if response.status_code != 200:
                raise Exception(f"Backend returned {response.status_code}")

            data = response.json()
            self.room_url = data.get("room_url")
            self.token = data.get("token")

            logger.info(f"✅ Got room URL: {self.room_url}")
            return True

        except Exception as e:
            logger.error(f"❌ Backend connection failed: {e}")
            return False

    def on_joined(self, data, error):
        if error:
            logger.error(f"Join error: {error}")
            return

        logger.info("✅ Joined Daily.co room")
        logger.info("🎤 Audio capture active")

    def on_participant_joined(self, participant):
        participant_id = participant.get("id")
        username = participant.get("user_name", participant_id or 'Unknown')
        logger.info(f"🤖 Participant joined: {username}")
        self.bot_participant_id = participant_id

    def on_participant_left(self, participant, reason=None):
        username = participant.get("user_name", participant.get("id", 'Unknown'))
        logger.info(f"Participant left: {username}")

    def on_app_message(self, message, sender):
        """Handle messages from bot"""
        try:
            msg_data = json.loads(message) if isinstance(message, str) else message

            # Unwrap server-message envelopes
            if msg_data.get("type") == "server-message" and "data" in msg_data:
                msg_data = msg_data["data"]

            # Handle video playback
            if msg_data.get("type") == "video-playback-command" and msg_data.get("action") == "play":
                import httpx
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
                        logger.info("✅ Video started")
                except Exception as e:
                    logger.error(f"Video playback error: {e}")

        except Exception as e:
            logger.error(f"Message handling error: {e}")

    def on_error(self, error):
        logger.error(f"Daily.co error: {error}")


async def run_client(backend_url: str, video_service_url: str, room_url: Optional[str] = None, token: Optional[str] = None):
    """Run the Pi client with custom audio"""

    # Initialize Daily
    Daily.init()

    # Get audio device
    audio_device = get_audio_device()

    # Create Daily virtual microphone device (16kHz mono to match Whisper)
    logger.info("Creating Daily virtual microphone...")
    microphone_device = Daily.create_microphone_device(
        "pi-microphone",
        sample_rate=SAMPLE_RATE,
        channels=CHANNELS
    )
    logger.info("✅ Virtual microphone created")

    # Create event handler
    client = CinemaRTVIClient(backend_url, video_service_url)

    # Get room URL from backend if needed
    if not room_url:
        if not await client.connect_to_backend():
            return
        room_url = client.room_url
        token = client.token

    # Create call client
    call_client = CallClient(event_handler=client)
    client.call_client = call_client

    try:
        logger.info(f"Joining room: {room_url}")

        # Join WITHOUT microphone settings initially
        call_client.join(
            room_url,
            meeting_token=token if token else None,
            client_settings={
                "inputs": {
                    "camera": False,
                    "microphone": False
                },
                "publishing": {
                    "camera": False,
                    "microphone": False
                }
            }
        )

        # Wait for join to complete
        await asyncio.sleep(1)

        # NOW use update_inputs to select our virtual microphone
        logger.info("Selecting virtual microphone with update_inputs()...")
        call_client.update_inputs({
            "microphone": {
                "isEnabled": True,
                "settings": {
                    "deviceId": microphone_device.device_name
                }
            }
        })

        # Enable publishing
        call_client.update_publishing({
            "microphone": True
        })

        logger.info("✅ Virtual microphone selected and publishing enabled")

        # Create ALSA audio source
        audio_source = ALSAAudioSource(audio_device, microphone_device)
        client.audio_source = audio_source

        # Start audio capture task
        logger.info("Starting audio capture from ALSA...")
        client.audio_task = asyncio.create_task(
            audio_source.read_frames()
        )

        logger.info("✅ Client running. Press Ctrl+C to stop.")

        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        if client.audio_source:
            client.audio_source.stop()
        if client.audio_task:
            client.audio_task.cancel()
        try:
            await call_client.leave()
        except:
            pass


async def main():
    backend_url = os.getenv("BACKEND_URL", BACKEND_URL)
    video_service_url = os.getenv("VIDEO_SERVICE_URL", VIDEO_SERVICE_URL)
    room_url = os.getenv("DAILY_ROOM_URL") or None
    token = os.getenv("DAILY_TOKEN") or None

    await run_client(backend_url, video_service_url, room_url, token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Exiting...")
