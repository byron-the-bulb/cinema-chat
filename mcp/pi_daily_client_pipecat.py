#!/usr/bin/env python3
"""
Pipecat-based Daily.co Client for Raspberry Pi

This is a simplified Pipecat client that runs on the Pi and:
1. Captures audio from phone input
2. Sends to Daily.co room (where the bot is)
3. Receives RTVI server messages with video playback commands
4. Calls local video playback service

Based on the same DailyTransport used by the backend.
"""

import asyncio
import os
import sys
import logging
import httpx
from loguru import logger

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.transports.services.daily import DailyTransport, DailyParams
from pipecat.processors.frameworks.rtvi import RTVIProcessor, RTVIConfig
from pipecat.frames.frames import Frame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# Configuration
VIDEO_SERVICE_URL = os.getenv("VIDEO_SERVICE_URL", "http://localhost:5000")
DAILY_ROOM_URL = os.getenv("DAILY_ROOM_URL", "")
DAILY_TOKEN = os.getenv("DAILY_TOKEN", "")  # Optional token for auth

# Setup logging
logger.remove(0)
logger.add(sys.stderr, level="INFO")


class VideoPlaybackProcessor(FrameProcessor):
    """
    Processor that listens for RTVI server messages with video playback commands
    and calls the local video service.
    """

    def __init__(self):
        super().__init__()
        self.http_client = httpx.AsyncClient()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Process frames looking for RTVI server messages"""
        from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame

        # Check if this is an RTVI server message
        if isinstance(frame, RTVIServerMessageFrame):
            data = frame.data if hasattr(frame, 'data') else frame

            logger.info(f"[VideoPlayback] Received RTVI message: {data}")

            # Check if it's a video playback command
            if isinstance(data, dict) and data.get("type") == "video-playback-command":
                if data.get("action") == "play":
                    await self.play_video(
                        video_path=data.get("video_path"),
                        start=data.get("start", 0),
                        end=data.get("end", 10),
                        fullscreen=data.get("fullscreen", True)
                    )

        # Let all frames through
        await self.push_frame(frame, direction)

    async def play_video(self, video_path, start, end, fullscreen=True):
        """Call the local video playback service"""
        logger.info(f"[VideoPlayback] Playing: {video_path} ({start}s - {end}s)")

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
                logger.info(f"[VideoPlayback] Video started: PID {result.get('pid')}")
            else:
                error = response.json().get("message", "Unknown error")
                logger.error(f"[VideoPlayback] Failed: {error}")

        except Exception as e:
            logger.error(f"[VideoPlayback] Error calling video service: {e}")


async def run_client(room_url, token=None):
    """Run the Pi Daily.co client"""
    logger.info(f"🎬 Starting Cinema Chat Pi client for room: {room_url}")

    # Create Daily transport (as a participant, not a bot)
    transport = DailyTransport(
        room_url=room_url,
        token=token,
        bot_name="Cinema Pi",  # Friendly name for the participant
        params=DailyParams(
            audio_in_enabled=True,   # Send phone audio to room
            audio_out_enabled=False,  # Don't need audio out (video is the response)
            vad_enabled=False,        # Don't need VAD on Pi side
            camera_out_enabled=False, # No video
            session_timeout=60 * 60,  # 1 hour timeout
        ),
    )

    # RTVI processor to handle server messages
    rtvi = RTVIProcessor(config=RTVIConfig(config=[]))

    # Video playback processor
    video_processor = VideoPlaybackProcessor()

    # Simple pipeline: just transport + RTVI + video playback
    pipeline = Pipeline(
        [
            transport.input(),   # Receive from Daily.co
            rtvi,                # Handle RTVI protocol
            video_processor,     # Process video commands
            transport.output(),  # Send to Daily.co (mostly just audio)
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=16000,   # Phone audio input
            audio_out_sample_rate=48000,  # Standard output rate
        ),
    )

    # Run the pipeline
    logger.info("✅ Pi client connected and running")
    logger.info("🎤 Streaming phone audio to server")
    logger.info("📺 Listening for video playback commands")

    try:
        runner = PipelineRunner()
        await runner.run(task)
    except KeyboardInterrupt:
        logger.info("Shutting down Pi client")
    except Exception as e:
        logger.error(f"Error in Pi client: {e}")
    finally:
        await task.queue_frame(None)  # Signal end


async def main():
    """Main entry point"""
    room_url = DAILY_ROOM_URL

    if not room_url:
        logger.error("❌ No Daily.co room URL provided")
        logger.error("Set DAILY_ROOM_URL environment variable")
        logger.error("Example: export DAILY_ROOM_URL=https://example.daily.co/room-name")
        sys.exit(1)

    token = DAILY_TOKEN if DAILY_TOKEN else None

    logger.info("=" * 60)
    logger.info("Cinema Chat - Raspberry Pi Client")
    logger.info("=" * 60)
    logger.info(f"Room URL: {room_url}")
    logger.info(f"Video Service: {VIDEO_SERVICE_URL}")
    logger.info("=" * 60)

    await run_client(room_url, token)


if __name__ == "__main__":
    asyncio.run(main())
