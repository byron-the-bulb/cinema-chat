#!/usr/bin/env python3
"""
Full-featured Daily.co Client for Raspberry Pi (RTVI-compatible)

Replicates all functionality from the browser RTVI client:
1. Connects to backend /connect endpoint
2. Joins Daily.co room with audio enabled
3. Handles bot events (transcription, responses, video commands)
4. Calls local video service for playback

This is the Pi equivalent of the browser's RTVI + Daily Transport.
"""

import asyncio
import os
import sys
import json
import logging
import httpx
from daily import Daily, CallClient, EventHandler
from typing import Optional

# Configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://192.168.1.143:8765/api")
VIDEO_SERVICE_URL = os.getenv("VIDEO_SERVICE_URL", "http://localhost:5000")
DAILY_ROOM_URL = os.getenv("DAILY_ROOM_URL", "")
DAILY_TOKEN = os.getenv("DAILY_TOKEN", "")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


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

    async def connect_to_backend(self):
        """Connect to backend and get Daily.co room info"""
        logger.info("=" * 60)
        logger.info("🎬 Cinema Chat - Raspberry Pi RTVI Client")
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

    def on_participant_joined(self, data, error=None):
        """Called when bot joins"""
        if error:
            return

        participant = data.get("participant", {})
        username = participant.get("user_name", participant.get("id", 'Unknown'))
        logger.info(f"🤖 Bot joined: {username}")

    def on_participant_left(self, data, error=None):
        """Called when bot leaves"""
        if error:
            return

        participant = data.get("participant", {})
        username = participant.get("user_name", participant.get("id", 'Unknown'))
        logger.info(f"Bot left: {username}")

    def on_app_message(self, data, error):
        """
        Handles app messages from the bot.

        This replicates the browser's handling of:
        - Video playback commands
        - Status updates
        - Any custom messages
        """
        if error:
            logger.error(f"Error receiving app message: {error}")
            return

        try:
            message = data.get("message")
            sender = data.get("fromId", "unknown")

            logger.info(f"📨 Received message from {sender}")

            # Parse message
            if isinstance(message, str):
                msg_data = json.loads(message)
            else:
                msg_data = message

            # Handle video playback commands (same as simple client)
            if msg_data.get("type") == "video-playback-command":
                if msg_data.get("action") == "play":
                    asyncio.create_task(self.play_video(
                        video_path=msg_data.get("video_path"),
                        start=msg_data.get("start", 0),
                        end=msg_data.get("end", 10),
                        fullscreen=msg_data.get("fullscreen", True)
                    ))

            # Handle other message types (status, config, etc.)
            elif msg_data.get("type") == "status":
                logger.info(f"📊 Status: {msg_data.get('message')}")

            elif msg_data.get("type") == "config":
                logger.info(f"⚙️  Config update: {msg_data}")

        except Exception as e:
            logger.error(f"Error handling app message: {e}")

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

    def on_transcription_message(self, data, error):
        """Handle transcription updates (user speech-to-text)"""
        if error:
            return

        text = data.get("text", "")
        is_final = data.get("is_final", False)

        if is_final:
            logger.info(f"👤 User said: {text}")

    def on_error(self, error):
        """Called on error"""
        logger.error(f"Daily.co error: {error}")


async def run_client(backend_url: str, video_service_url: str, room_url: Optional[str] = None, token: Optional[str] = None):
    """Run the Pi RTVI-compatible Daily.co client"""

    # Initialize Daily
    Daily.init()

    # Create event handler
    client = CinemaRTVIClient(backend_url, video_service_url)

    # Get room URL from backend if not provided
    if not room_url:
        if not await client.connect_to_backend():
            logger.error("Failed to connect to backend")
            return
        room_url = client.room_url
        token = client.token

    # Create call client
    call_client = CallClient(event_handler=client)

    # Join the room
    try:
        logger.info(f"Joining room: {room_url}")

        # Configure to send audio only (same as browser config)
        # Note: join() is synchronous, actual join completion signaled via on_joined event
        call_client.join(
            room_url,
            meeting_token=token if token else None,
            client_settings={
                "inputs": {
                    "camera": False,  # No video
                    "microphone": True  # Send audio from phone
                },
                "publishing": {
                    "camera": False,
                    "microphone": True
                }
            }
        )

        # Keep running
        logger.info("✅ Client running. Press Ctrl+C to stop.")
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
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
