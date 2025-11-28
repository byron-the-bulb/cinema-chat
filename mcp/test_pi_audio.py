#!/usr/bin/env python3
"""
Simple audio test script for Raspberry Pi.
Records audio from microphone and plays it back.
"""

import os
import sys
import time
import subprocess

# Audio configuration
AUDIO_DEVICE = os.getenv("AUDIODEV", "hw:1,0")  # USB Audio Device
ALSA_CARD = os.getenv("ALSA_CARD", "1")
SAMPLE_RATE = 16000  # 16kHz (same as Whisper)
DURATION = 5  # seconds
OUTPUT_FILE = "test_recording.wav"

def list_audio_devices():
    """List all available audio input devices"""
    print("=" * 60)
    print("Available Audio Input Devices:")
    print("=" * 60)
    try:
        result = subprocess.run(
            ["arecord", "-l"],
            capture_output=True,
            text=True,
            check=True
        )
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error listing devices: {e}")
        print(e.stderr)
    print()

def test_record():
    """Record audio from the microphone"""
    print("=" * 60)
    print(f"Recording {DURATION} seconds of audio...")
    print(f"Device: {AUDIO_DEVICE} (ALSA_CARD={ALSA_CARD})")
    print(f"Sample Rate: {SAMPLE_RATE} Hz")
    print("=" * 60)
    print()
    print("🎤 SPEAK NOW! Recording will start in 1 second...")
    time.sleep(1)
    print("🔴 RECORDING...")

    try:
        # Record audio using arecord
        cmd = [
            "arecord",
            "-D", AUDIO_DEVICE,
            "-f", "S16_LE",  # 16-bit signed little-endian
            "-r", str(SAMPLE_RATE),
            "-c", "1",  # Mono
            "-d", str(DURATION),
            OUTPUT_FILE
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            print("✅ Recording complete!")

            # Check file size
            file_size = os.path.getsize(OUTPUT_FILE)
            print(f"📊 File size: {file_size:,} bytes ({file_size / 1024:.1f} KB)")

            # Expected size calculation
            expected_size = SAMPLE_RATE * 2 * DURATION + 44  # 2 bytes per sample + WAV header
            print(f"📊 Expected size: {expected_size:,} bytes ({expected_size / 1024:.1f} KB)")

            if file_size < 1000:
                print("⚠️  WARNING: File is very small - microphone may not be working!")
            elif file_size < expected_size * 0.5:
                print("⚠️  WARNING: File is smaller than expected - audio may be incomplete")
            else:
                print("✅ File size looks good!")

            return True
        else:
            print(f"❌ Recording failed!")
            print(f"Error: {result.stderr}")
            return False

    except Exception as e:
        print(f"❌ Error during recording: {e}")
        return False

def test_playback():
    """Play back the recorded audio"""
    print()
    print("=" * 60)
    print("Playing back recording...")
    print("=" * 60)
    print()

    if not os.path.exists(OUTPUT_FILE):
        print(f"❌ Recording file not found: {OUTPUT_FILE}")
        return False

    print("🔊 Playing in 1 second...")
    time.sleep(1)

    try:
        # Play audio using aplay
        cmd = ["aplay", OUTPUT_FILE]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            print("✅ Playback complete!")
            return True
        else:
            print(f"❌ Playback failed!")
            print(f"Error: {result.stderr}")
            return False

    except Exception as e:
        print(f"❌ Error during playback: {e}")
        return False

def analyze_recording():
    """Analyze the recording to check if it contains actual audio"""
    print()
    print("=" * 60)
    print("Analyzing recording...")
    print("=" * 60)
    print()

    if not os.path.exists(OUTPUT_FILE):
        print(f"❌ Recording file not found: {OUTPUT_FILE}")
        return

    try:
        # Use sox to get audio statistics
        cmd = ["sox", OUTPUT_FILE, "-n", "stat"]
        result = subprocess.run(cmd, capture_output=True, text=True)

        # sox outputs to stderr
        stats = result.stderr
        print(stats)

        # Check for silence
        if "Maximum amplitude" in stats:
            for line in stats.split('\n'):
                if "Maximum amplitude" in line:
                    try:
                        max_amp = float(line.split(':')[1].strip())
                        print()
                        if max_amp < 0.01:
                            print("⚠️  WARNING: Audio is very quiet or silent!")
                            print("   The microphone may not be capturing audio.")
                        elif max_amp < 0.1:
                            print("⚠️  Audio level is low - check microphone gain")
                        else:
                            print(f"✅ Audio level looks good! (max amplitude: {max_amp:.3f})")
                    except:
                        pass

    except FileNotFoundError:
        print("ℹ️  sox not installed - skipping detailed analysis")
        print("   Install with: sudo apt-get install sox")
    except Exception as e:
        print(f"⚠️  Could not analyze recording: {e}")

def main():
    """Main test sequence"""
    print()
    print("🎬 Cinema Chat - Audio Test")
    print()

    # Step 1: List devices
    list_audio_devices()

    # Step 2: Record
    success = test_record()

    if not success:
        print()
        print("=" * 60)
        print("❌ Recording failed. Troubleshooting tips:")
        print("=" * 60)
        print()
        print("1. Check if the USB microphone is connected:")
        print("   arecord -l")
        print()
        print("2. Try recording with default device:")
        print("   arecord -d 5 test.wav")
        print()
        print("3. Check ALSA configuration:")
        print("   cat /proc/asound/cards")
        print()
        print("4. Set the correct device:")
        print("   export AUDIODEV=hw:X,Y  (where X,Y match your device)")
        print()
        sys.exit(1)

    # Step 3: Analyze
    analyze_recording()

    # Step 4: Playback
    test_playback()

    print()
    print("=" * 60)
    print("✅ Audio test complete!")
    print("=" * 60)
    print()
    print(f"Recording saved to: {OUTPUT_FILE}")
    print()
    print("Next steps:")
    print("1. If you heard your voice clearly, the microphone is working!")
    print("2. If recording was silent, check the microphone connection")
    print("3. If playback didn't work, check speaker/headphone connection")
    print()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(0)
