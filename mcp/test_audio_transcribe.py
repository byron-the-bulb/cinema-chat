#!/usr/bin/env python3
"""
Simple test script to verify audio capture and transcription

This tests:
1. PyAudio can capture from USB microphone (hw:1,0)
2. Audio can be converted to WAV format
3. Backend /transcribe endpoint works
"""

import pyaudio
import wave
import io
import httpx
import os

# Configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://192.168.1.143:8765")
AUDIO_DEVICE = "hw:1,0"
SAMPLE_RATE = 16000
CHANNELS = 1
DURATION = 3  # Record 3 seconds

print("=" * 60)
print("Audio Capture and Transcription Test")
print("=" * 60)
print(f"Backend: {BACKEND_URL}")
print(f"Audio device: {AUDIO_DEVICE}")
print(f"Sample rate: {SAMPLE_RATE} Hz")
print(f"Duration: {DURATION} seconds")
print("=" * 60)

# Initialize PyAudio
audio = pyaudio.PyAudio()

# Find device
device_index = None
for i in range(audio.get_device_count()):
    info = audio.get_device_info_by_index(i)
    if "hw:1,0" in str(info['name']) or i == 1:
        device_index = i
        print(f"Found audio device: {info['name']} at index {i}")
        break

if device_index is None:
    print(f"WARNING: Device {AUDIO_DEVICE} not found, using default")

# Open stream
print(f"\nOpening audio stream...")
stream = audio.open(
    format=pyaudio.paInt16,
    channels=CHANNELS,
    rate=SAMPLE_RATE,
    input=True,
    input_device_index=device_index,
    frames_per_buffer=1024
)

print(f"Recording {DURATION} seconds...")
print("SPEAK NOW!")

# Record audio
frames = []
for _ in range(0, int(SAMPLE_RATE / 1024 * DURATION)):
    data = stream.read(1024, exception_on_overflow=False)
    frames.append(data)

print("Recording complete")

# Stop stream
stream.stop_stream()
stream.close()
audio.terminate()

# Create WAV file in memory
print("Creating WAV file...")
wav_buffer = io.BytesIO()
with wave.open(wav_buffer, 'wb') as wav_file:
    wav_file.setnchannels(CHANNELS)
    wav_file.setsampwidth(2)  # 16-bit = 2 bytes
    wav_file.setframerate(SAMPLE_RATE)
    wav_file.writeframes(b''.join(frames))

wav_buffer.seek(0)
audio_data = wav_buffer.read()

print(f"WAV file size: {len(audio_data)} bytes")

# Send to transcription endpoint
print(f"\nSending to {BACKEND_URL}/transcribe...")
try:
    response = httpx.post(
        f"{BACKEND_URL}/transcribe",
        files={"file": ("test.wav", audio_data, "audio/wav")},
        timeout=30.0
    )

    if response.status_code == 200:
        result = response.json()
        text = result.get("text", "")
        language = result.get("language", "unknown")

        print("=" * 60)
        print("SUCCESS!")
        print("=" * 60)
        print(f"Transcribed text: {text}")
        print(f"Language: {language}")
        print("=" * 60)
    else:
        print(f"ERROR: {response.status_code}")
        print(response.text)

except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
