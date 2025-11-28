#!/usr/bin/env python3
"""
Daily.co Client for Raspberry Pi with HTTP-based transcription

This version bypasses Daily.co's lack of local audio capture support by:
1. Capturing audio from USB microphone using PyAudio
2. Sending audio chunks to backend /transcribe endpoint
3. Injecting transcribed text into Daily room as user message
4. Receiving video playback commands via Daily app messages

Architecture:
- Audio input: PyAudio → /transcribe → Daily room (text injection)
- Video commands: Daily app messages → Video service
"""

import asyncio
import os
import sys
import json
import logging
import httpx
import io
import wave
import threading
from daily import Daily, CallClient, EventHandler
from typing import Optional
import pyaudio

# Configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://192.168.1.143:8765")
VIDEO_SERVICE_URL = os.getenv("VIDEO_SERVICE_URL", "http://localhost:5000")
AUDIO_DEVICE_FILE = "/home/twistedtv/audio_device.conf"
DEFAULT_AUDIO_DEVICE = "hw:1,0"  # USB microphone

# Audio capture settings
SAMPLE_RATE = 16000  # 16kHz for Whisper
CHANNELS = 1  # Mono
CHUNK_DURATION = 3  # Capture 3 seconds at a time
CHUNK_SIZE = int(SAMPLE_RATE * CHUNK_DURATION)

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AudioCapture:
    """Captures audio from microphone and sends to transcription endpoint"""

    def __init__(self, backend_url: str, device_name: str):
        self.backend_url = backend_url
        self.device_name = device_name
        self.http_client = httpx.AsyncClient()
        self.audio = None
        self.stream = None
        self.running = False

    def start(self):
        """Start audio capture"""
        # Initialize PyAudio
        self.audio = pyaudio.PyAudio()

        # Find device index for configured device
        device_index = None
        for i in range(self.audio.get_device_count()):
            info = self.audio.get_device_info_by_index(i)
            if self.device_name in info['name'] or (self.device_name == "hw:1,0" and i == 1):
                device_index = i
                logger.info(f"Found audio device: {info['name']} at index {i}")
                break

        if device_index is None:
            logger.warning(f"Device {self.device_name} not found, using default")
            device_index = None

        # Open audio stream
        self.stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=1024
        )

        self.running = True
        logger.info(f"🎤 Started capturing from {self.device_name}")

    async def capture_chunk(self) -> bytes:
        """Capture one chunk of audio (CHUNK_DURATION seconds)"""
        if not self.stream or not self.running:
            return None

        # Read audio data
        frames = []
        for _ in range(0, int(SAMPLE_RATE / 1024 * CHUNK_DURATION)):
            try:
                data = self.stream.read(1024, exception_on_overflow=False)
                frames.append(data)
            except Exception as e:
                logger.error(f"Error reading audio: {e}")
                return None

        # Combine frames into single audio chunk
        audio_data = b''.join(frames)

        # Create WAV file in memory
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(CHANNELS)
            wav_file.setsampwidth(self.audio.get_sample_size(pyaudio.paInt16))
            wav_file.setframerate(SAMPLE_RATE)
            wav_file.writeframes(audio_data)

        wav_buffer.seek(0)
        return wav_buffer.read()

    async def transcribe(self, audio_data: bytes, room_url: str) -> Optional[str]:
        """Send audio to backend /transcribe endpoint with room_url"""
        try:
            # Send audio file + room_url as form data
            response = await self.http_client.post(
                f"{self.backend_url}/transcribe",
                data={"room_url": room_url},
                files={"file": ("audio.wav", audio_data, "audio/wav")},
                timeout=10.0
            )

            if response.status_code == 200:
                result = response.json()
                text = result.get("text", "").strip()
                sent_to_room = result.get("sent_to_room", False)

                if sent_to_room:
                    logger.info(f"✅ Transcription sent to Daily room: {text}")
                else:
                    logger.warning(f"⚠️  Transcription NOT sent to room: {text}")

                return text if text else None
            else:
                logger.error(f"Transcription failed: {response.status_code} {response.text}")
                return None

        except Exception as e:
            logger.error(f"Error calling transcription endpoint: {e}")
            return None

    def stop(self):
        """Stop audio capture"""
        self.running = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        if self.audio:
            self.audio.terminate()
        logger.info("🎤 Stopped audio capture")


class CinemaTranscribeClient(EventHandler):
    """
    Cinema Chat Daily.co client with HTTP-based transcription

    - Captures audio locally and transcribes via HTTP
    - Injects transcribed text into Daily room
    - Receives video playback commands via app messages
    """

    def __init__(self, backend_url: str, video_service_url: str, audio_device: str):
        super().__init__()
        self.backend_url = backend_url
        self.video_service_url = video_service_url
        self.audio_device = audio_device
        self.http_client = httpx.AsyncClient()
        self.room_url: Optional[str] = None
        self.token: Optional[str] = None
        self.call_client: Optional[CallClient] = None
        self.audio_capture: Optional[AudioCapture] = None
        self.capture_task: Optional[asyncio.Task] = None

    async def connect_to_backend(self):
        """Connect to backend and get Daily.co room info"""
        logger.info("=" * 60)
        logger.info("🎬 Cinema Chat - Raspberry Pi Transcribe Client")
        logger.info("=" * 60)
        logger.info(f"Backend: {self.backend_url}")
        logger.info(f"Video Service: {self.video_service_url}")
        logger.info(f"Audio Device: {self.audio_device}")
        logger.info("=" * 60)

        try:
            logger.info("Connecting to backend...")
            response = await self.http_client.post(
                f"{self.backend_url}/api/connect",
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
            logger.info("🎤 Starting local audio capture and transcription")

            # Start audio capture in background
            asyncio.create_task(self.start_audio_capture())

    async def start_audio_capture(self):
        """Start capturing audio and sending for transcription"""
        self.audio_capture = AudioCapture(self.backend_url, self.audio_device)
        self.audio_capture.start()

        logger.info("🎤 Audio capture loop started")

        while self.audio_capture.running:
            try:
                # Capture audio chunk
                logger.debug(f"Capturing {CHUNK_DURATION}s audio chunk...")
                audio_data = await self.audio_capture.capture_chunk()

                if not audio_data:
                    logger.warning("No audio data captured")
                    continue

                # Send for transcription (will be sent to Daily room automatically)
                logger.debug("Sending audio for transcription...")
                text = await self.audio_capture.transcribe(audio_data, self.room_url)

                if text:
                    logger.info(f"👤 Transcribed and sent to room: {text}")
                else:
                    logger.debug("No speech detected in chunk")

            except Exception as e:
                logger.error(f"Error in audio capture loop: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(1)

    async def inject_user_message(self, text: str):
        """Inject transcribed text into Daily room as user message"""
        if not self.call_client:
            logger.error("Cannot inject message - no call client")
            return

        try:
            # Send app message to simulate user speech
            # The backend should pick this up and process it
            message = {
                "type": "user-transcription",
                "text": text,
                "source": "pi-microphone"
            }

            # Note: Daily Python doesn't have direct send_app_message
            # We need to use the sendAppMessage via the call client
            # This may not work - we might need to use Daily REST API instead

            logger.info(f"📤 Injecting user message: {text}")
            self.call_client.send_app_message(json.dumps(message))

        except Exception as e:
            logger.error(f"Error injecting message: {e}")
            import traceback
            traceback.print_exc()

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


async def run_client(backend_url: str, video_service_url: str, audio_device: str,
                     room_url: Optional[str] = None, token: Optional[str] = None):
    """Run the Pi client with HTTP-based transcription"""

    # Initialize Daily
    Daily.init()

    # Create event handler
    client = CinemaTranscribeClient(backend_url, video_service_url, audio_device)

    # Get room URL from backend if not provided
    if not room_url:
        if not await client.connect_to_backend():
            logger.error("Failed to connect to backend")
            return
        room_url = client.room_url
        token = client.token

    # Create call client
    call_client = CallClient(event_handler=client)
    client.call_client = call_client

    # Join the room (no audio/video from Daily perspective)
    try:
        logger.info(f"Joining room: {room_url}")

        call_client.join(
            room_url,
            meeting_token=token if token else None,
            client_settings={
                "inputs": {
                    "camera": False,
                    "microphone": False  # We handle audio separately
                },
                "publishing": {
                    "camera": False,
                    "microphone": False
                }
            }
        )

        logger.info("✅ Client running")
        logger.info("🎤 Capturing audio locally and transcribing via HTTP")
        logger.info("📺 Listening for video commands...")
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
            if client.audio_capture:
                client.audio_capture.stop()
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

    # Read audio device from config file
    audio_device = DEFAULT_AUDIO_DEVICE
    if os.path.exists(AUDIO_DEVICE_FILE):
        try:
            with open(AUDIO_DEVICE_FILE) as f:
                audio_device = f.read().strip() or DEFAULT_AUDIO_DEVICE
        except:
            pass

    if not backend_url:
        logger.error("❌ No backend URL configured")
        logger.error("Set BACKEND_URL environment variable")
        sys.exit(1)

    await run_client(backend_url, video_service_url, audio_device, room_url, token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Exiting...")
