"""
Audio processing pipeline — VAD + STT without Pipecat.

Receives raw PCM audio chunks, detects speech boundaries with Silero VAD,
and transcribes complete utterances with faster-whisper.
"""

import os
import time
import numpy as np
import torch
from loguru import logger

# Silero VAD
_vad_model = None
_vad_utils = None

# faster-whisper
_whisper_model = None

# Audio constants
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit = 2 bytes
CHUNK_SAMPLES = 512  # Silero VAD requires 512 samples at 16kHz


def init_vad():
    """Load Silero VAD model."""
    global _vad_model, _vad_utils
    logger.info("Loading Silero VAD model...")
    _vad_model, _vad_utils = torch.hub.load(
        repo_or_dir="snakers4/silero-vad",
        model="silero_vad",
        force_reload=False,
        onnx=True,
    )
    logger.info("Silero VAD loaded")


def init_whisper():
    """Load faster-whisper model."""
    global _whisper_model
    from faster_whisper import WhisperModel

    device = os.getenv("WHISPER_DEVICE", "cuda")
    model_id = os.getenv("WHISPER_MODEL", "Systran/faster-distil-whisper-medium.en")

    logger.info(f"Loading Whisper model {model_id} on {device}...")
    compute_type = "float16" if device == "cuda" else "int8"
    _whisper_model = WhisperModel(model_id, device=device, compute_type=compute_type)
    logger.info(f"Whisper model loaded on {device}")


def init():
    """Initialize both VAD and Whisper."""
    init_vad()
    init_whisper()


class VADState:
    """Tracks voice activity state across audio chunks."""

    def __init__(
        self,
        threshold: float = 0.3,
        min_speech_ms: int = 100,
        stop_secs: float = 0.8,
    ):
        self.threshold = threshold
        self.min_speech_ms = min_speech_ms
        self.stop_secs = stop_secs

        # State
        self.is_speaking = False
        self.speech_start_time: float = 0
        self.last_speech_time: float = 0
        self.audio_buffer = bytearray()
        self._pending_buffer = bytearray()  # Audio before speech confirmed

    def reset(self):
        self.is_speaking = False
        self.speech_start_time = 0
        self.last_speech_time = 0
        self.audio_buffer = bytearray()
        self._pending_buffer = bytearray()
        # Reset VAD model state
        if _vad_model is not None:
            _vad_model.reset_states()

    def process_chunk(self, pcm_bytes: bytes) -> tuple[bool, bool]:
        """
        Process a chunk of raw PCM audio.

        Returns:
            (speech_started, speech_ended) - booleans indicating transitions
        """
        self._pending_buffer.extend(pcm_bytes)

        speech_started = False
        speech_ended = False

        # Process in 512-sample windows (Silero requirement)
        window_bytes = CHUNK_SAMPLES * SAMPLE_WIDTH
        while len(self._pending_buffer) >= window_bytes:
            window = bytes(self._pending_buffer[:window_bytes])
            self._pending_buffer = self._pending_buffer[window_bytes:]

            # Convert to float tensor for VAD
            audio_int16 = np.frombuffer(window, dtype=np.int16)
            audio_float = audio_int16.astype(np.float32) / 32768.0
            tensor = torch.from_numpy(audio_float)

            # Run VAD
            speech_prob = _vad_model(tensor, SAMPLE_RATE).item()
            now = time.monotonic()

            if speech_prob >= self.threshold:
                if not self.is_speaking:
                    self.speech_start_time = now
                    self.is_speaking = True
                    speech_started = True
                    self.audio_buffer = bytearray()
                self.last_speech_time = now

            # Accumulate audio while speaking
            if self.is_speaking:
                self.audio_buffer.extend(window)

                # Check for speech end (silence timeout)
                if speech_prob < self.threshold:
                    silence_duration = now - self.last_speech_time
                    if silence_duration >= self.stop_secs:
                        speech_duration_ms = (self.last_speech_time - self.speech_start_time) * 1000
                        if speech_duration_ms >= self.min_speech_ms:
                            speech_ended = True
                        else:
                            # Too short, discard
                            self.reset()

        return speech_started, speech_ended

    def get_speech_audio(self) -> bytes:
        """Get the accumulated speech audio and reset state."""
        audio = bytes(self.audio_buffer)
        self.reset()
        return audio


def transcribe(pcm_bytes: bytes) -> str:
    """
    Transcribe raw PCM audio bytes using faster-whisper.

    Args:
        pcm_bytes: Raw 16kHz mono 16-bit PCM audio

    Returns:
        Transcribed text string
    """
    if _whisper_model is None:
        raise RuntimeError("Whisper model not initialized — call init() first")

    # Convert PCM bytes to float32 numpy array
    audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
    audio_float = audio_int16.astype(np.float32) / 32768.0

    t0 = time.monotonic()
    segments, info = _whisper_model.transcribe(
        audio_float,
        beam_size=1,
        language="en",
        vad_filter=False,  # We already did VAD
        no_speech_threshold=0.3,
    )

    text_parts = []
    for seg in segments:
        if seg.no_speech_prob < 0.3:
            text_parts.append(seg.text.strip())

    text = " ".join(text_parts).strip()
    elapsed = time.monotonic() - t0
    logger.info(f"STT ({elapsed:.2f}s): \"{text}\"")
    return text
