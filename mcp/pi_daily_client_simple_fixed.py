#!/usr/bin/env python3
"""
Simplified Daily.co Client for Raspberry Pi
Based on official Daily Python demo: https://github.com/daily-co/daily-python/blob/main/demos/pyaudio/record_and_play.py

Uses ALSA for audio capture (since we verified that works with plughw:1,0)
Writes to Daily virtual microphone in synchronous callback (not async loop)
"""

import asyncio
import os
import sys
import json
import logging
import httpx
import threading
import time
import subprocess
import alsaaudio
from daily import Daily, CallClient, EventHandler
from typing import Optional

# Configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://192.168.1.143:8765/api")
VIDEO_SERVICE_URL = os.getenv("VIDEO_SERVICE_URL", "http://localhost:5000")
AUDIO_CONFIG_FILE = "/home/twistedtv/audio_device.conf"
CLEANUP_SCRIPT = "/home/twistedtv/cleanup_pi.sh"

# Audio settings (16kHz mono to match backend expectations)
SAMPLE_RATE = 16000
CHANNELS = 1
PERIOD_SIZE = 160  # 10ms at 16kHz

# Setup logging
logging.basicConfig(
    level=logging.INFO,
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

    device = os.getenv("AUDIO_DEVICE", "hw:1,0")
    logger.info(f"Using audio device from environment: {device}")
    return device


def cleanup_pi_processes():
    """Run the cleanup script to kill all Pi processes"""
    try:
        logger.info("Running Pi cleanup script...")
        result = subprocess.run(
            ['bash', CLEANUP_SCRIPT],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            logger.info("Cleanup script completed successfully")
            if result.stdout:
                logger.debug(f"Cleanup output: {result.stdout}")
        else:
            logger.warning(f"Cleanup script returned code {result.returncode}")
            if result.stderr:
                logger.warning(f"Cleanup errors: {result.stderr}")

    except subprocess.TimeoutExpired:
        logger.error("Cleanup script timed out after 10 seconds")
    except Exception as e:
        logger.error(f"Error running cleanup script: {e}")


class ALSAAudioThread(threading.Thread):
    """Thread to capture audio from ALSA and write to Daily virtual microphone"""

    def __init__(self, device: str, virtual_mic):
        super().__init__(daemon=True)
        self.device = device
        self.virtual_mic = virtual_mic
        self.running = False
        self.mic_device = None

    def run(self):
        """Capture audio and write to Daily microphone in blocking thread"""
        self.running = True

        try:
            logger.info(f"Opening ALSA device: {self.device}")
            # Open ALSA PCM device for capture
            self.mic_device = alsaaudio.PCM(
                alsaaudio.PCM_CAPTURE,
                alsaaudio.PCM_NORMAL,  # BLOCKING mode (not NONBLOCK)
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                format=alsaaudio.PCM_FORMAT_S16_LE,
                periodsize=PERIOD_SIZE,
                device=self.device
            )
            logger.info(f"✅ ALSA device opened: {SAMPLE_RATE}Hz, {CHANNELS} ch")

            frame_count = 0

            while self.running:
                # Read audio data from ALSA (blocking)
                length, data = self.mic_device.read()

                if length > 0:
                    # Write raw int16 PCM data directly to Daily virtual microphone
                    # Daily will handle float32 conversion internally
                    self.virtual_mic.write_frames(data)

                    frame_count += 1
                    if frame_count % 100 == 0:
                        logger.debug(f"Sent {frame_count} audio frames to Daily")

        except Exception as e:
            logger.error(f"Error in audio capture thread: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if self.mic_device:
                self.mic_device.close()
            logger.info("Audio capture thread stopped")

    def stop(self):
        """Stop audio capture"""
        self.running = False


class CinemaClient(EventHandler):
    """Cinema Chat Daily.co client"""

    def __init__(self, backend_url: str, video_service_url: str):
        super().__init__()
        self.backend_url = backend_url
        self.video_service_url = video_service_url
        self.http_client = httpx.AsyncClient()
        self.room_url = None
        self.token = None
        self.audio_thread = None
        self.should_exit = False
        self.bot_left = False

    async def connect_to_backend(self):
        """Connect to backend and get Daily.co room info"""
        logger.info("=" * 60)
        logger.info("🎬 Cinema Chat - Pi Client (Fixed)")
        logger.info("=" * 60)
        logger.info(f"Backend: {self.backend_url}")
        logger.info(f"Video Service: {self.video_service_url}")
        logger.info("=" * 60)

        try:
            logger.info("Connecting to backend...")
            response = await self.http_client.post(
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

    def on_call_state_updated(self, state):
        """Called when call state changes"""
        logger.info(f"📞 Call state: {state}")

        if state == "joined":
            logger.info("✅ Joined Daily.co room successfully")
            logger.info("🎤 Audio should now be flowing to backend")
        elif state == "left":
            logger.info("Left Daily.co room")
            self.should_exit = True

    def on_participant_joined(self, participant):
        """Called when bot joins"""
        username = participant.get("user_name", participant.get("id", 'Unknown'))
        logger.info(f"🤖 Bot joined: {username}")

    def on_participant_left(self, participant, reason=None):
        """Called when bot leaves - trigger cleanup"""
        username = participant.get("user_name", participant.get("id", 'Unknown'))
        logger.info(f"🤖 Bot left: {username}")

        # Check if this is the bot participant (not ourselves)
        # The bot typically has user_name like "Pipecat Bot" or similar
        if username and "bot" in username.lower():
            logger.info("🧹 Bot has left the room, initiating cleanup...")
            self.bot_left = True
            self.should_exit = True

    def on_app_message(self, message, sender):
        """Handle app messages from bot (video playback commands)"""
        logger.debug(f"📨 Received message from {sender}")

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
                        logger.info(f"✅ Video playback started")
                    else:
                        logger.error(f"❌ Video playback failed: {response.text}")
                except Exception as e:
                    logger.error(f"❌ Error calling video service: {e}")

        except Exception as e:
            logger.error(f"Error handling app message: {e}")

    def on_error(self, error):
        """Called on error"""
        logger.error(f"❌ Daily.co error: {error}")


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

    # Get audio device
    audio_device = get_audio_device()

    # Create Daily virtual microphone with NON-BLOCKING mode (critical!)
    logger.info("Creating Daily virtual microphone...")
    virtual_mic = Daily.create_microphone_device(
        "pi-microphone",
        sample_rate=SAMPLE_RATE,
        channels=CHANNELS,
        non_blocking=True  # CRITICAL: Must be non-blocking for proper operation
    )
    logger.info("✅ Virtual microphone created (non-blocking mode)")

    # Create event handler
    client = CinemaClient(backend_url, video_service_url)

    # Get room URL from backend
    if not await client.connect_to_backend():
        logger.error("Failed to connect to backend")
        return

    # Create call client
    call_client = CallClient(event_handler=client)

    try:
        # Start audio capture thread BEFORE joining
        logger.info("Starting audio capture thread...")
        audio_thread = ALSAAudioThread(audio_device, virtual_mic)
        audio_thread.start()
        client.audio_thread = audio_thread

        # Give audio thread time to initialize
        await asyncio.sleep(0.5)

        logger.info(f"Joining room: {client.room_url}")

        # Join with virtual microphone - following official Daily demo pattern
        call_client.join(
            client.room_url,
            meeting_token=client.token if client.token else None,
            client_settings={
                "inputs": {
                    "camera": False,
                    "microphone": {
                        "isEnabled": True,
                        "settings": {
                            "deviceId": "pi-microphone"  # Use device NAME string, not object
                        }
                    }
                },
                "publishing": {
                    "camera": False,
                    "microphone": {
                        "isPublishing": True,  # Explicitly enable publishing
                        "sendSettings": {
                            "channelConfig": "mono"  # Match our CHANNELS setting
                        }
                    }
                }
            }
        )

        # Wait for join to complete
        await asyncio.sleep(2)
        logger.info("✅ Client running. Press Ctrl+C to stop.")
        logger.info("🎤 Audio is being captured and sent to backend")

        # Keep running until bot leaves or Ctrl+C
        while not client.should_exit:
            await asyncio.sleep(1)

        if client.bot_left:
            logger.info("🧹 Exiting due to bot leaving room...")

    except KeyboardInterrupt:
        logger.info("🧹 Shutting down (Ctrl+C)...")
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Clean up audio thread
        if client.audio_thread:
            client.audio_thread.stop()

        # Leave the Daily room
        try:
            await call_client.leave()
            logger.info("Left room")
        except:
            pass

        # Run cleanup script to kill all Pi processes
        logger.info("🧹 Running cleanup script to terminate all Pi processes...")
        cleanup_pi_processes()

        logger.info("✅ Cleanup complete, exiting")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Exiting...")
