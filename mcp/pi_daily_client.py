#!/usr/bin/env python3
"""
Headless Daily.co Audio Client for Raspberry Pi

This service runs on the Raspberry Pi and:
1. Captures audio from phone input (connected to Pi's audio input)
2. Connects to Daily.co WebRTC room
3. Sends audio to server for processing (Whisper STT → LLM → MCP)
4. Server's MCP makes direct HTTP calls to Pi's video service

This replaces the browser-based client and allows the Pi to run completely headless.
No video commands needed here - server calls video service directly via HTTP.
"""

import asyncio
import os
import sys
import json
import logging
import httpx
from daily import Daily, CallClient, EventHandler

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
VIDEO_SERVICE_URL = os.getenv("VIDEO_SERVICE_URL", "http://localhost:5000")
DAILY_API_KEY = os.getenv("DAILY_API_KEY", "")
DAILY_ROOM_URL = os.getenv("DAILY_ROOM_URL", "")  # Can be created dynamically
AUDIO_DEVICE = os.getenv("AUDIO_DEVICE", "default")  # ALSA device for phone input


class CinemaClientEventHandler(EventHandler):
    """Event handler for Daily.co client events"""

    def __init__(self, client):
        super().__init__()
        self.client = client
        self.http_client = httpx.AsyncClient()

    async def on_joined(self, participant):
        """Called when we successfully join the room"""
        logger.info(f"Joined Daily.co room: {participant}")

    async def on_participant_joined(self, participant):
        """Called when another participant joins (the bot)"""
        logger.info(f"Participant joined: {participant}")

    async def on_participant_left(self, participant):
        """Called when a participant leaves"""
        logger.info(f"Participant left: {participant}")

    async def on_app_message(self, message, sender):
        """
        Called when we receive an app message from the server.
        This is how the server sends video playback commands.
        """
        logger.info(f"Received app message from {sender}: {message}")

        try:
            # Parse the message
            if isinstance(message, str):
                data = json.loads(message)
            else:
                data = message

            # Check if it's a video playback command
            if data.get("type") == "video-playback-command" and data.get("action") == "play":
                await self.play_video(
                    video_path=data.get("video_path"),
                    start=data.get("start", 0),
                    end=data.get("end", 10),
                    fullscreen=data.get("fullscreen", True)
                )
        except Exception as e:
            logger.error(f"Error handling app message: {e}")

    async def play_video(self, video_path, start, end, fullscreen=True):
        """Call the local video playback service"""
        logger.info(f"Playing video: {video_path} ({start}s - {end}s)")

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
                logger.info(f"Video playback started: {result}")
            else:
                error = response.json().get("message", "Unknown error")
                logger.error(f"Failed to start video playback: {error}")

        except Exception as e:
            logger.error(f"Error calling video service: {e}")

    async def on_error(self, error):
        """Called when an error occurs"""
        logger.error(f"Daily.co error: {error}")


class HeadlessDailyClient:
    """Headless Daily.co client for Raspberry Pi"""

    def __init__(self, room_url, api_key=None):
        self.room_url = room_url
        self.api_key = api_key
        self.client = None
        self.event_handler = None

    async def start(self):
        """Start the Daily.co client"""
        logger.info(f"Starting headless Daily.co client for room: {self.room_url}")

        # Initialize Daily
        Daily.init()

        # Create call client
        self.client = CallClient(event_handler=CinemaClientEventHandler(self))

        # Configure audio input
        # This will capture from the phone connected to Pi's audio input
        self.client.update_inputs({
            "camera": False,  # No video
            "microphone": {
                "isEnabled": True,
                "settings": {
                    "deviceId": AUDIO_DEVICE
                }
            }
        })

        # Join the room
        await self.client.join(self.room_url, client_settings={
            "inputs": {
                "camera": False,
                "microphone": True
            }
        })

        logger.info("Successfully joined Daily.co room")

    async def stop(self):
        """Stop the Daily.co client"""
        if self.client:
            await self.client.leave()
            logger.info("Left Daily.co room")

    async def run(self):
        """Run the client (keep alive)"""
        try:
            await self.start()

            # Keep the client running
            logger.info("Client is running. Press Ctrl+C to stop.")
            while True:
                await asyncio.sleep(1)

        except KeyboardInterrupt:
            logger.info("Received shutdown signal")

        except Exception as e:
            logger.error(f"Error in client: {e}")

        finally:
            await self.stop()


async def create_daily_room(api_key):
    """Create a new Daily.co room for this session"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.daily.co/v1/rooms",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "properties": {
                    "enable_chat": False,
                    "enable_screenshare": False,
                    "enable_recording": False,
                    "start_video_off": True,
                    "start_audio_off": False
                }
            }
        )

        if response.status_code == 200:
            data = response.json()
            room_url = data.get("url")
            logger.info(f"Created Daily.co room: {room_url}")
            return room_url
        else:
            raise Exception(f"Failed to create room: {response.text}")


async def main():
    """Main entry point"""
    # Get room URL (or create one)
    room_url = DAILY_ROOM_URL

    if not room_url and DAILY_API_KEY:
        logger.info("No room URL provided, creating a new room...")
        room_url = await create_daily_room(DAILY_API_KEY)

    if not room_url:
        logger.error("No Daily.co room URL available. Set DAILY_ROOM_URL or DAILY_API_KEY.")
        sys.exit(1)

    # Start the headless client
    client = HeadlessDailyClient(room_url, DAILY_API_KEY)
    await client.run()


if __name__ == "__main__":
    asyncio.run(main())
