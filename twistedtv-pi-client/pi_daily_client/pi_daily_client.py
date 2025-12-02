#!/usr/bin/env python3
"""
Full-featured Daily.co Client for Raspberry Pi with ALSA Audio
Combines RTVI-compatible structure from pi_daily_client_rtvi.py
with ALSA audio capture from the official Daily Python demo.
"""

import asyncio
import os
import sys
import json
import logging
import httpx
import threading
import alsaaudio
from daily import Daily, CallClient, EventHandler
from typing import Optional

# Configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://192.168.1.143:8765/api")
VIDEO_SERVICE_URL = os.getenv("VIDEO_SERVICE_URL", "http://localhost:5000")
DAILY_ROOM_URL = os.getenv("DAILY_ROOM_URL", "")
DAILY_TOKEN = os.getenv("DAILY_TOKEN", "")
AUDIO_CONFIG_FILE = "/home/twistedtv/audio_device.conf"

# Audio settings (16kHz mono to match backend expectations)
SAMPLE_RATE = 16000
CHANNELS = 1
PERIOD_SIZE = 160  # 10ms at 16kHz

# Setup logging with DEBUG level to see all message details
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


class CinemaRTVIClient(EventHandler):
    """
    RTVI-compatible Daily.co client for Cinema Chat.

    Replicates the browser RTVI client functionality:
    - Joins Daily.co room
    - Receives audio from bot
    - Handles transcription events
    - Processes video playback commands
    """

    def __init__(self, backend_url: str, video_service_url: str):
        super().__init__()
        self.backend_url = backend_url
        self.video_service_url = video_service_url
        self.http_client = httpx.AsyncClient()
        self.room_url: Optional[str] = None
        self.token: Optional[str] = None
        self.audio_thread: Optional[ALSAAudioThread] = None

    async def connect_to_backend(self):
        """Connect to backend and get Daily.co room info"""
        logger.info("=" * 60)
        logger.info("🎬 Cinema Chat - Raspberry Pi RTVI Client with ALSA Audio")
        logger.info("=" * 60)
        logger.info(f"Backend: {self.backend_url}")
        logger.info(f"Video Service: {self.video_service_url}")
        logger.info("=" * 60)

        try:
            # Call backend /connect endpoint (same as browser)
            logger.info("Connecting to backend...")
            response = await self.http_client.post(
                f"{self.backend_url}/connect",
                json={
                    "config": [{
                        "service": "tts",
                        "options": [{
                            "name": "provider",
                            "value": "cartesia"
                        }]
                    }]
                },
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

    def on_joined(self, data, error):
        """Called when we join the room"""
        if error:
            logger.error(f"Error joining room: {error}")
            return

        logger.info("✅ Joined Daily.co room")
        logger.info("🎤 Streaming phone audio to bot")
        logger.info("📺 Listening for video commands...")

    def on_participant_joined(self, participant):
        """Called when bot joins - Daily.co SDK passes participant dict directly"""
        username = participant.get("user_name", participant.get("id", 'Unknown'))
        logger.info(f"🤖 Bot joined: {username}")

    def on_participant_left(self, participant, reason=None):
        """Called when bot leaves - Daily.co SDK passes participant dict directly"""
        username = participant.get("user_name", participant.get("id", 'Unknown'))
        logger.info(f"Bot left: {username}")

    def on_app_message(self, message, sender):
        """
        Handles app messages from the bot.
        Daily.co SDK signature: (self, message, sender)

        This replicates the browser's handling of:
        - Video playback commands
        - Status updates
        - Any custom messages
        """
        logger.info(f"📨 Received message from {sender}")
        logger.debug(f"🔍 RAW MESSAGE: {message}")
        logger.debug(f"🔍 MESSAGE TYPE: {type(message)}")

        try:
            # Parse message
            if isinstance(message, str):
                msg_data = json.loads(message)
                logger.debug(f"🔍 PARSED FROM STRING: {msg_data}")
            else:
                msg_data = message
                logger.debug(f"🔍 DIRECT OBJECT: {msg_data}")

            logger.info(f"🔍 MESSAGE DATA TYPE: {msg_data.get('type')}")
            logger.debug(f"🔍 FULL MSG_DATA: {json.dumps(msg_data, indent=2)}")

            # Unwrap server-message envelopes
            if msg_data.get("type") == "server-message" and "data" in msg_data:
                logger.info(f"🔓 Unwrapping server-message envelope")
                msg_data = msg_data["data"]
                logger.info(f"🔍 UNWRAPPED TYPE: {msg_data.get('type')}")
                logger.debug(f"🔍 UNWRAPPED DATA: {json.dumps(msg_data, indent=2)}")

            # Handle video playback commands (same as simple client)
            if msg_data.get("type") == "video-playback-command":
                logger.info(f"✅ MATCHED video-playback-command!")
                if msg_data.get("action") == "play":
                    logger.info(f"✅ MATCHED action=play, calling play_video()")
                    # Call video service directly (synchronous HTTP call)
                    # Can't use async in Daily.co callback thread
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
                            result = response.json()
                            logger.info(f"✅ Video started: PID {result.get('pid')}")
                        else:
                            logger.error(f"❌ Video playback failed: {response.text}")
                    except Exception as e:
                        logger.error(f"❌ Error calling video service: {e}")
                else:
                    logger.warning(f"⚠️  video-playback-command but action={msg_data.get('action')}, not 'play'")

            # Handle test ping messages
            elif msg_data.get("type") == "pi-test-ping":
                logger.info(f"✅ Test ping #{msg_data.get('counter')}: {msg_data.get('message')}")

            # Handle other message types (status, config, etc.)
            elif msg_data.get("type") == "status":
                logger.info(f"📊 Status: {msg_data.get('message')}")

            elif msg_data.get("type") == "config":
                logger.info(f"⚙️  Config update: {msg_data}")

            else:
                logger.warning(f"⚠️  Unknown message type: {msg_data.get('type')}")

        except Exception as e:
            logger.error(f"Error handling app message: {e}")
            import traceback
            traceback.print_exc()

    async def play_video(self, video_path, start, end, fullscreen=True):
        """Call the local video playback service"""
        logger.info(f"🎬 Playing: {video_path} ({start}s - {end}s)")

        try:
            response = await self.http_client.post(
                f"{self.video_service_url}/play",
                json={
                    "video_path": video_path,
                    "start": start,
                    "end": end,
                    "fullscreen": fullscreen
                },
                timeout=5.0
            )

            if response.status_code == 200:
                result = response.json()
                logger.info(f"✅ Video started: PID {result.get('pid')}")
            else:
                error = response.json().get("message", "Unknown error")
                logger.error(f"❌ Video playback failed: {error}")

        except Exception as e:
            logger.error(f"❌ Error calling video service: {e}")

    def on_transcription_message(self, message):
        """Handle transcription updates (user speech-to-text)
        Daily.co SDK signature: (self, message)
        """
        text = message.get("text", "")
        is_final = message.get("is_final", False)

        if is_final:
            logger.info(f"👤 User said: {text}")

    def on_error(self, error):
        """Called on error"""
        logger.error(f"Daily.co error: {error}")


async def run_client(backend_url: str, video_service_url: str, room_url: Optional[str] = None, token: Optional[str] = None):
    """Run the Pi RTVI-compatible Daily.co client with ALSA audio"""

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
    client = CinemaRTVIClient(backend_url, video_service_url)

    # Get room URL from backend if not provided
    if not room_url:
        if not await client.connect_to_backend():
            logger.error("Failed to connect to backend")
            return
        room_url = client.room_url
        token = client.token
    else:
        client.room_url = room_url
        client.token = token

    # Create call client
    call_client = CallClient(event_handler=client)

    # Join the room
    try:
        # Start audio capture thread BEFORE joining
        logger.info("Starting audio capture thread...")
        audio_thread = ALSAAudioThread(audio_device, virtual_mic)
        audio_thread.start()
        client.audio_thread = audio_thread

        # Give audio thread time to initialize
        await asyncio.sleep(0.5)

        logger.info(f"Joining room: {room_url}")

        # Configure to send audio with customConstraints (from official Daily demo)
        # Note: join() is synchronous, actual join completion signaled via on_joined event
        call_client.join(
            room_url,
            meeting_token=token if token else None,
            client_settings={
                "inputs": {
                    "camera": False,  # No video
                    "microphone": {
                        "isEnabled": True,
                        "settings": {
                            "deviceId": "pi-microphone",  # Use device NAME string, not object
                            "customConstraints": {
                                "autoGainControl": {"exact": True},
                                "noiseSuppression": {"exact": True},
                                "echoCancellation": {"exact": True},
                            },
                        }
                    }
                },
                "publishing": {
                    "camera": False,
                    "microphone": {
                        "isPublishing": True,
                        "sendSettings": {
                            "channelConfig": "mono"  # Match our CHANNELS setting
                        }
                    }
                }
            }
        )

        # Keep running and send periodic test messages
        logger.info("✅ Client running. Press Ctrl+C to stop.")
        test_counter = 0
        while True:
            await asyncio.sleep(5)
            test_counter += 1
            try:
                # Send test app message to verify Pi->Room communication
                call_client.send_app_message({
                    "type": "pi-test-ping",
                    "counter": test_counter,
                    "message": f"Pi test ping #{test_counter}",
                    "timestamp": asyncio.get_event_loop().time()
                })
                logger.info(f"📤 Sent test ping #{test_counter} to room")
            except Exception as e:
                logger.error(f"Failed to send test ping: {e}")

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        # Clean up audio thread
        if client.audio_thread:
            client.audio_thread.stop()

        try:
            await call_client.leave()
            logger.info("Left room")
        except:
            pass


async def main():
    """Main entry point"""
    backend_url = os.getenv("BACKEND_URL", BACKEND_URL)
    video_service_url = os.getenv("VIDEO_SERVICE_URL", VIDEO_SERVICE_URL)
    room_url = os.getenv("DAILY_ROOM_URL", DAILY_ROOM_URL) or None
    token = os.getenv("DAILY_TOKEN", DAILY_TOKEN) or None

    if not backend_url:
        logger.error("❌ No backend URL configured")
        logger.error("Set BACKEND_URL environment variable")
        sys.exit(1)

    await run_client(backend_url, video_service_url, room_url, token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Exiting...")
