#!/usr/bin/env python3
"""
Daily.co Client for Raspberry Pi with Real Audio Capture

This version properly captures audio from the microphone and sends it to Daily
using CustomAudioSource and CustomAudioTrack.
"""

import asyncio
import os
import sys
import json
import logging
import httpx
import pyaudio
import threading
from daily import Daily, CallClient, EventHandler
from typing import Optional

# Configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8765")
VIDEO_SERVICE_URL = os.getenv("VIDEO_SERVICE_URL", "http://localhost:5000")
AUDIO_CONFIG_FILE = "/home/twistedtv/audio_device.conf"

# Audio settings (44.1kHz native device rate, will be resampled by Daily/backend if needed)
SAMPLE_RATE = 44100
CHANNELS = 1
CHUNK_SIZE = 4410  # 100ms at 44.1kHz

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_audio_device() -> Optional[str]:
    """Get the configured audio device from config file or environment"""
    # First try reading from config file (set by admin panel)
    try:
        if os.path.exists(AUDIO_CONFIG_FILE):
            with open(AUDIO_CONFIG_FILE, 'r') as f:
                device = f.read().strip()
                if device:
                    logger.info(f"Using audio device from config file: {device}")
                    return device
    except Exception as e:
        logger.warning(f"Could not read audio config file: {e}")

    # Fall back to environment variable
    device = os.getenv("AUDIO_DEVICE")
    if device and device != "default":
        logger.info(f"Using audio device from environment: {device}")
        return device

    logger.info("Using default audio device")
    return None


def get_pyaudio_device_index(device_name: Optional[str]) -> Optional[int]:
    """Convert ALSA device name (hw:X,Y) to PyAudio device index"""
    if not device_name:
        return None

    p = pyaudio.PyAudio()
    try:
        # If device_name is like "hw:1,0", extract card number
        if device_name.startswith("hw:"):
            card_str = device_name.split(':')[1].split(',')[0]
            card_num = int(card_str)

            # Find device with matching card number
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info['maxInputChannels'] > 0:  # Input device
                    # Check if name contains the card identifier
                    name = info['name']
                    logger.debug(f"Device {i}: {name}")
                    if f"card {card_num}" in name.lower() or f"hw:{card_num}" in name.lower():
                        logger.info(f"Found PyAudio device index {i} for {device_name}: {name}")
                        return i

        logger.warning(f"Could not find PyAudio device for {device_name}, using default")
        return None
    finally:
        p.terminate()


class AudioCaptureThread(threading.Thread):
    """Background thread to capture audio from microphone and send to Daily"""

    def __init__(self, microphone_device, device_index: Optional[int] = None):
        super().__init__(daemon=True)
        self.microphone_device = microphone_device
        self.device_index = device_index
        self.running = False
        self.audio = None
        self.stream = None

    def run(self):
        """Capture audio and write to Daily microphone"""
        self.running = True
        self.audio = pyaudio.PyAudio()

        try:
            # Open audio stream
            logger.info(f"Opening audio stream (device_index={self.device_index})")
            self.stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                input=True,
                input_device_index=self.device_index,
                frames_per_buffer=CHUNK_SIZE,
                stream_callback=self._audio_callback
            )

            self.stream.start_stream()
            logger.info("✅ Audio capture started")

            # Keep running
            import time
            while self.running:
                time.sleep(0.1)

        except Exception as e:
            logger.error(f"Error in audio capture: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()
            if self.audio:
                self.audio.terminate()
            logger.info("Audio capture stopped")

    def _audio_callback(self, in_data, frame_count, time_info, status):
        """Called by PyAudio when audio data is available"""
        if status:
            logger.warning(f"Audio callback status: {status}")

        try:
            # Write audio frames to Daily microphone
            # in_data is already bytes in int16 format - pass directly
            result = self.microphone_device.write_frames(in_data)

            # Log every 100th frame to confirm audio is flowing
            if not hasattr(self, '_frame_count'):
                self._frame_count = 0
            self._frame_count += 1
            if self._frame_count % 100 == 0:
                logger.debug(f"Sent {self._frame_count} audio frames ({frame_count} samples each)")
        except Exception as e:
            logger.error(f"Error writing audio frames: {e}")
            import traceback
            traceback.print_exc()

        return (None, pyaudio.paContinue)

    def stop(self):
        """Stop audio capture"""
        self.running = False


class CinemaRTVIClient(EventHandler):
    """
    RTVI-compatible Daily.co client with real audio capture
    """

    def __init__(self, backend_url: str, video_service_url: str):
        super().__init__()
        self.backend_url = backend_url
        self.video_service_url = video_service_url
        self.http_client = httpx.AsyncClient()
        self.room_url: Optional[str] = None
        self.token: Optional[str] = None
        self.audio_thread: Optional[AudioCaptureThread] = None

    async def connect_to_backend(self):
        """Connect to backend and get Daily.co room info"""
        logger.info("=" * 60)
        logger.info("🎬 Cinema Chat - Pi RTVI Client (Audio Sender)")
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

    def on_joined(self, data, error):
        """Called when we join the room"""
        if error:
            logger.error(f"Error joining room: {error}")
            return

        logger.info("✅ Joined Daily.co room")
        logger.info("🎤 Microphone active - speaking should now be captured")

    def on_participant_joined(self, participant):
        """Called when bot joins"""
        username = participant.get("user_name", participant.get("id", 'Unknown'))
        logger.info(f"🤖 Bot joined: {username}")

    def on_participant_left(self, participant, reason=None):
        """Called when bot leaves"""
        username = participant.get("user_name", participant.get("id", 'Unknown'))
        logger.info(f"Bot left: {username}")

    def on_app_message(self, message, sender):
        """Handle app messages from the bot"""
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

            elif msg_data.get("type") == "status":
                logger.info(f"📊 Status: {msg_data.get('message')}")

        except Exception as e:
            logger.error(f"Error handling app message: {e}")

    def on_transcription_message(self, message):
        """Handle transcription updates"""
        text = message.get("text", "")
        is_final = message.get("is_final", False)

        if is_final:
            logger.info(f"👤 User said: {text}")

    def on_error(self, error):
        """Called on error"""
        logger.error(f"❌ Daily.co error: {error}")

    def on_call_state_updated(self, state):
        """Called when call state changes"""
        logger.info(f"📞 Call state: {state}")

    def stop_audio(self):
        """Stop audio capture thread"""
        if self.audio_thread:
            self.audio_thread.stop()


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

    # Create event handler
    client = CinemaRTVIClient(backend_url, video_service_url)

    # Get room URL from backend
    if not await client.connect_to_backend():
        logger.error("Failed to connect to backend")
        return

    # Get audio device configuration
    audio_device = get_audio_device()
    device_index = get_pyaudio_device_index(audio_device)

    # Create virtual microphone device
    logger.info("Creating virtual microphone device...")
    microphone_device = Daily.create_microphone_device(
        "pi-microphone",
        sample_rate=SAMPLE_RATE,
        channels=CHANNELS,
        non_blocking=True
    )

    # Start audio capture thread
    logger.info("Starting audio capture thread...")
    audio_thread = AudioCaptureThread(microphone_device, device_index)
    audio_thread.start()
    client.audio_thread = audio_thread

    # Create call client
    call_client = CallClient(event_handler=client)

    try:
        logger.info(f"Joining room: {client.room_url}")
        logger.info(f"Audio device: {audio_device or 'default'}")

        # Join with virtual microphone
        logger.info("Calling join()...")
        call_client.join(
            client.room_url,
            meeting_token=client.token if client.token else None,
            client_settings={
                "inputs": {
                    "camera": {
                        "isEnabled": False
                    },
                    "microphone": {
                        "isEnabled": True,
                        "settings": {
                            "deviceId": "pi-microphone"
                        }
                    }
                }
            }
        )

        # Wait for join to complete
        logger.info("Waiting for join to complete...")
        await asyncio.sleep(3)  # Give time for join to process

        # Now update inputs to use our virtual microphone device
        logger.info("Configuring virtual microphone...")
        call_client.update_inputs({
            "camera": False,
            "microphone": {
                "isEnabled": True,
                "settings": {
                    "customAudioDeviceId": microphone_device
                }
            }
        })
        logger.info("✅ Virtual microphone configured")

        logger.info("✅ Client running. Press Ctrl+C to stop.")
        logger.info("🎤 Speak now - audio is being captured!")

        # Keep running - the async loop allows Daily SDK to process events
        while True:
            await asyncio.sleep(0.1)  # Shorter sleep for more responsive event processing

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            client.stop_audio()
            await call_client.leave()
            logger.info("Left room")
        except:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Exiting...")
