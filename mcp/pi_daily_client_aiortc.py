#!/usr/bin/env python3
"""
Daily.co Client for Raspberry Pi using aiortc for audio capture

This version uses aiortc (pure Python WebRTC) to capture microphone audio
and inject it into the Daily.co room, since daily-python doesn't support
local audio capture on Linux.

Architecture:
1. aiortc captures audio from USB microphone (hw:1,0)
2. daily-python connects to Daily.co room
3. We bridge audio from aiortc → Daily.co
"""

import asyncio
import os
import sys
import json
import logging
import httpx
from daily import Daily, CallClient, EventHandler
from typing import Optional
import pyaudio
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
from aiortc.contrib.media import MediaRecorder, MediaPlayer
from av import AudioFrame
import numpy as np

# Configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://192.168.1.143:8765/api")
VIDEO_SERVICE_URL = os.getenv("VIDEO_SERVICE_URL", "http://localhost:5000")
AUDIO_DEVICE = os.getenv("AUDIO_DEVICE", "hw:1,0")  # USB microphone

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MicrophoneTrack(MediaStreamTrack):
    """
    Audio track that captures from the microphone using PyAudio
    """
    kind = "audio"

    def __init__(self, device_name="hw:1,0"):
        super().__init__()
        self.device_name = device_name
        self.sample_rate = 48000  # Daily.co uses 48kHz
        self.channels = 1  # Mono
        self.chunk_size = 960  # 20ms at 48kHz

        # Initialize PyAudio
        self.audio = pyaudio.PyAudio()

        # Find device index for hw:1,0
        device_index = None
        for i in range(self.audio.get_device_count()):
            info = self.audio.get_device_info_by_index(i)
            if device_name in info['name'] or i == 1:  # Card 1
                device_index = i
                logger.info(f"Found audio device: {info['name']} at index {i}")
                break

        if device_index is None:
            logger.warning(f"Device {device_name} not found, using default")
            device_index = None

        # Open audio stream
        self.stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=self.chunk_size
        )

        logger.info(f"🎤 Opened microphone: {device_name}")

    async def recv(self):
        """Read audio frame from microphone"""
        # Read audio data
        data = self.stream.read(self.chunk_size, exception_on_overflow=False)

        # Convert to numpy array
        samples = np.frombuffer(data, dtype=np.int16)

        # Create AudioFrame
        frame = AudioFrame.from_ndarray(
            samples.reshape(1, -1),  # (channels, samples)
            format='s16',
            layout='mono'
        )
        frame.sample_rate = self.sample_rate
        frame.pts = int(asyncio.get_event_loop().time() * self.sample_rate)
        frame.time_base = f"1/{self.sample_rate}"

        return frame

    def stop(self):
        """Stop the audio stream"""
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        if self.audio:
            self.audio.terminate()


class CinemaRTVIClient(EventHandler):
    """
    Cinema Chat Daily.co client with aiortc audio capture
    """

    def __init__(self, backend_url: str, video_service_url: str):
        super().__init__()
        self.backend_url = backend_url
        self.video_service_url = video_service_url
        self.http_client = httpx.AsyncClient()
        self.room_url: Optional[str] = None
        self.token: Optional[str] = None
        self.call_client: Optional[CallClient] = None
        self.mic_track: Optional[MicrophoneTrack] = None

    async def connect_to_backend(self):
        """Connect to backend and get Daily.co room info"""
        logger.info("=" * 60)
        logger.info("🎬 Cinema Chat - Raspberry Pi RTVI Client (aiortc)")
        logger.info("=" * 60)
        logger.info(f"Backend: {self.backend_url}")
        logger.info(f"Video Service: {self.video_service_url}")
        logger.info("=" * 60)

        try:
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

    def on_call_state_updated(self, state):
        """Called when call state changes"""
        logger.info(f"📞 Call state: {state}")

        if state == "joined":
            logger.info("✅ Joined Daily.co room")
            logger.info("🎤 Audio capture via aiortc")
            logger.info("📺 Listening for video commands...")

    def on_participant_joined(self, participant):
        """Called when bot joins"""
        username = participant.get("user_name", participant.get("id", 'Unknown'))
        logger.info(f"🤖 Bot joined: {username}")

    def on_participant_left(self, participant, reason=None):
        """Called when bot leaves"""
        username = participant.get("user_name", participant.get("id", 'Unknown'))
        logger.info(f"Bot left: {username}")

    def on_app_message(self, message, sender):
        """Handle app messages from the bot (video playback commands)"""
        logger.info(f"📨 Received message from {sender}")
        logger.debug(f"🔍 RAW MESSAGE: {message}")

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
            if msg_data.get("type") == "video-playback-command":
                if msg_data.get("action") == "play":
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

        except Exception as e:
            logger.error(f"Error handling app message: {e}")
            import traceback
            traceback.print_exc()


async def run_client_with_aiortc(backend_url: str, video_service_url: str, room_url: Optional[str] = None, token: Optional[str] = None):
    """Run the Pi client with aiortc audio capture"""

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

    # Create microphone track
    logger.info("🎤 Initializing microphone capture...")
    mic_track = MicrophoneTrack(device_name=AUDIO_DEVICE)
    client.mic_track = mic_track

    # Create Daily call client
    call_client = CallClient(event_handler=client)
    client.call_client = call_client

    # Join the room
    try:
        logger.info(f"Joining room: {room_url}")

        # Note: We'll need to figure out how to inject aiortc audio into Daily
        # For now, just join the room and see what happens
        call_client.join(
            room_url,
            meeting_token=token if token else None,
            client_settings={
                "inputs": {
                    "camera": False,
                    "microphone": True  # This won't work, but trying anyway
                },
                "publishing": {
                    "camera": False,
                    "microphone": True
                }
            }
        )

        logger.info("✅ Client running with aiortc audio capture")
        logger.info("⚠️  Note: Audio bridging Daily ↔ aiortc not yet implemented")
        logger.info("Press Ctrl+C to stop.")

        # Keep running
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            if mic_track:
                mic_track.stop()
            await call_client.leave()
            logger.info("Left room")
        except:
            pass


async def main():
    """Main entry point"""
    backend_url = os.getenv("BACKEND_URL", BACKEND_URL)
    video_service_url = os.getenv("VIDEO_SERVICE_URL", VIDEO_SERVICE_URL)
    room_url = os.getenv("DAILY_ROOM_URL", "") or None
    token = os.getenv("DAILY_TOKEN", "") or None

    if not backend_url:
        logger.error("❌ No backend URL configured")
        logger.error("Set BACKEND_URL environment variable")
        sys.exit(1)

    await run_client_with_aiortc(backend_url, video_service_url, room_url, token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Exiting...")
