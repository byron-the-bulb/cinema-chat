#!/usr/bin/env python3
"""
Simple Daily.co Client for Raspberry Pi

Minimal client that:
1. Captures audio from phone input
2. Sends to Daily.co room via WebRTC
3. Receives app messages with video commands
4. Calls local video service

No Pipecat, no numpy, just daily-python SDK + httpx.
"""

import asyncio
import os
import sys
import json
import logging
import httpx
from daily import Daily, CallClient, EventHandler

# Configuration
VIDEO_SERVICE_URL = os.getenv("VIDEO_SERVICE_URL", "http://localhost:5000")
DAILY_ROOM_URL = os.getenv("DAILY_ROOM_URL", "")
DAILY_TOKEN = os.getenv("DAILY_TOKEN", "")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CinemaEventHandler(EventHandler):
    """Handle Daily.co events"""

    def __init__(self):
        super().__init__()
        self.http_client = httpx.AsyncClient()
        self.participant_id = None

    def on_joined(self, data, error):
        """Called when we join the room"""
        if error:
            logger.error(f"Error joining room: {error}")
            return

        logger.info("✅ Joined Daily.co room")
        logger.info("🎤 Streaming phone audio to server")
        logger.info("📺 Listening for video commands...")

    def on_participant_joined(self, data, error):
        """Called when bot joins"""
        if error:
            return

        participant = data.get("participant", {})
        logger.info(f"🤖 Bot joined: {participant.get('user_name', 'Unknown')}")

    def on_participant_left(self, data, error):
        """Called when bot leaves"""
        if error:
            return

        participant = data.get("participant", {})
        logger.info(f"Bot left: {participant.get('user_name', 'Unknown')}")

    def on_app_message(self, data, error):
        """
        Called when we receive an app message.
        This is how the server sends video playback commands.
        """
        if error:
            logger.error(f"Error receiving app message: {error}")
            return

        try:
            message = data.get("message")
            sender = data.get("fromId", "unknown")

            logger.info(f"📨 Received message from {sender}: {message}")

            # Parse message
            if isinstance(message, str):
                msg_data = json.loads(message)
            else:
                msg_data = message

            # Check if it's a video playback command
            if msg_data.get("type") == "video-playback-command":
                if msg_data.get("action") == "play":
                    asyncio.create_task(self.play_video(
                        video_path=msg_data.get("video_path"),
                        start=msg_data.get("start", 0),
                        end=msg_data.get("end", 10),
                        fullscreen=msg_data.get("fullscreen", True)
                    ))

        except Exception as e:
            logger.error(f"Error handling app message: {e}")

    async def play_video(self, video_path, start, end, fullscreen=True):
        """Call the local video playback service"""
        logger.info(f"🎬 Playing: {video_path} ({start}s - {end}s)")

        try:
            response = await self.http_client.post(
                f"{VIDEO_SERVICE_URL}/play",
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

    def on_error(self, error):
        """Called on error"""
        logger.error(f"Daily.co error: {error}")


async def run_client(room_url, token=None):
    """Run the Pi Daily.co client"""
    logger.info("=" * 60)
    logger.info("🎬 Cinema Chat - Raspberry Pi Client")
    logger.info("=" * 60)
    logger.info(f"Room: {room_url}")
    logger.info(f"Video Service: {VIDEO_SERVICE_URL}")
    logger.info("=" * 60)

    # Initialize Daily
    Daily.init()

    # Create event handler
    event_handler = CinemaEventHandler()

    # Create call client
    client = CallClient(event_handler=event_handler)

    # Join the room
    try:
        # Configure to send audio only
        # Note: join() is synchronous, actual join completion signaled via on_joined event
        client.join(
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
            await client.leave()
            logger.info("Left room")
        except:
            pass


async def main():
    """Main entry point"""
    room_url = DAILY_ROOM_URL

    if not room_url:
        logger.error("❌ No Daily.co room URL provided")
        logger.error("Set DAILY_ROOM_URL environment variable")
        logger.error("Example: export DAILY_ROOM_URL=https://example.daily.co/room-name")
        sys.exit(1)

    token = DAILY_TOKEN if DAILY_TOKEN else None

    await run_client(room_url, token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Exiting...")
