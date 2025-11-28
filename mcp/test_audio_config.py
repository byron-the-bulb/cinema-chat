#!/usr/bin/env python3
"""
Test script to verify audio device configuration logic
"""
import os
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

AUDIO_CONFIG_FILE = "/home/twistedtv/audio_device.conf"

def get_audio_device() -> str:
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
    device = os.getenv("AUDIO_DEVICE", "default")
    logger.info(f"Using audio device from environment: {device}")
    return device


def main():
    """Test the audio device configuration"""
    print("=" * 70)
    print("Testing Audio Device Configuration")
    print("=" * 70)
    print()

    # Test 1: Check config file
    print("Test 1: Config file check")
    print(f"  Config file path: {AUDIO_CONFIG_FILE}")
    if os.path.exists(AUDIO_CONFIG_FILE):
        with open(AUDIO_CONFIG_FILE, 'r') as f:
            content = f.read().strip()
            print(f"  ✅ Config file exists")
            print(f"  Content: '{content}'")
    else:
        print(f"  ⚠️  Config file does not exist (will use fallback)")
    print()

    # Test 2: Check environment variable
    print("Test 2: Environment variable check")
    env_device = os.getenv("AUDIO_DEVICE")
    if env_device:
        print(f"  ✅ AUDIO_DEVICE env var set: '{env_device}'")
    else:
        print(f"  ⚠️  AUDIO_DEVICE env var not set (will use 'default')")
    print()

    # Test 3: Get the actual device
    print("Test 3: Get audio device")
    device = get_audio_device()
    print(f"  📢 Selected device: '{device}'")
    print()

    # Test 4: Validate ALSA device format
    print("Test 4: Validate device format")
    import re
    if device == "default":
        print(f"  ✅ Using default device (valid)")
    elif re.match(r'^hw:\d+,\d+$', device):
        print(f"  ✅ Valid ALSA device format: {device}")
        card, dev = device.replace('hw:', '').split(',')
        print(f"     Card: {card}, Device: {dev}")
    else:
        print(f"  ⚠️  Unexpected device format: {device}")
        print(f"     Expected 'default' or 'hw:CARD,DEVICE' (e.g., 'hw:1,0')")
    print()

    print("=" * 70)
    print("Test Summary")
    print("=" * 70)
    print(f"Selected audio device: {device}")
    print()
    print("To set a specific device:")
    print("  1. Via config file: echo 'hw:1,0' > /home/twistedtv/audio_device.conf")
    print("  2. Via environment: export AUDIO_DEVICE='hw:1,0'")
    print()


if __name__ == "__main__":
    main()
