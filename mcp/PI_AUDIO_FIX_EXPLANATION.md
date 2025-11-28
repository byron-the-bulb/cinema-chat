# Pi Audio Input Fix - Complete Explanation

## The Problem

The Pi Daily client was not sending audio - no `userIsSpeaking` indicator and no transcriptions appeared.

## Root Cause

The Daily Python SDK works **fundamentally differently** from the browser Daily SDK:

### Browser (JavaScript) SDK
- Automatically captures audio from selected hardware device (microphone)
- Specifying `deviceId` tells the browser which mic to use
- Browser handles all the audio capture internally

### Python SDK
- **Does NOT automatically capture from hardware devices**
- You must explicitly:
  1. Create a "virtual microphone device" with `Daily.create_microphone_device()`
  2. Capture audio from hardware yourself (e.g., with PyAudio)
  3. Write audio frames to the virtual microphone using `write_frames()`
- Specifying `deviceId` in client_settings refers to a virtual device name, NOT hardware

## The Fix

Created a new Pi client that properly captures and sends audio:

**File**: `pi_daily_client_audio_sender.py`

### How It Works

```
Hardware Mic → PyAudio → Audio Capture Thread → write_frames() → Daily Virtual Mic → Daily Room
```

1. **Create virtual microphone**:
   ```python
   microphone_device = Daily.create_microphone_device(
       "pi-microphone",
       sample_rate=16000,
       channels=1
   )
   ```

2. **Capture audio from hardware** (in background thread):
   ```python
   # PyAudio captures from hardware microphone
   stream = audio.open(
       format=pyaudio.paInt16,
       channels=1,
       rate=16000,
       input=True,
       input_device_index=device_index,  # Hardware device
       frames_per_buffer=1600
   )
   ```

3. **Write frames to Daily** (in audio callback):
   ```python
   def audio_callback(in_data, frame_count, ...):
       samples = struct.unpack(f'{frame_count}h', in_data)
       microphone_device.write_frames(list(samples))
   ```

4. **Join room with virtual microphone**:
   ```python
   call_client.join(
       room_url,
       client_settings={
           "inputs": {
               "microphone": {
                   "isEnabled": True,
                   "settings": {
                       "deviceId": "pi-microphone"  # Virtual device, not hardware!
                   }
               }
           }
       }
   )
   ```

## Why the Original Approach Didn't Work

The original `pi_daily_client_rtvi.py` was based on a misunderstanding:

```python
# ❌ This doesn't work in Python SDK
client_settings={
    "inputs": {
        "microphone": {
            "isEnabled": True,
            "settings": {
                "deviceId": "hw:1,0"  # This is a HARDWARE device
            }
        }
    }
}
```

The Python SDK interprets `deviceId` as the name of a **virtual microphone device** you've created, not a hardware ALSA device. Since we never created a virtual device with that name, no audio was captured.

## Comparison: Browser vs Python Approach

### Browser (Next.js Frontend)
```javascript
// Browser automatically handles hardware capture
navigator.mediaDevices.getUserMedia({
    audio: {
        deviceId: "hw:1,0"  // Browser knows this is hardware
    }
})
```

### Python (Pi Client)
```python
# Step 1: You must capture from hardware yourself
import pyaudio
stream = pyaudio.PyAudio().open(
    input_device_index=1,  # Hardware device
    ...
)

# Step 2: Create virtual Daily device
mic = Daily.create_microphone_device("my-mic")

# Step 3: Pipe hardware audio to virtual device
def callback(in_data, ...):
    mic.write_frames(parse_audio(in_data))

# Step 4: Tell Daily to use the virtual device
call_client.join(room, client_settings={
    "inputs": {
        "microphone": {
            "settings": {"deviceId": "my-mic"}  # Virtual, not hardware!
        }
    }
})
```

## Dependencies

The new approach requires PyAudio:

```bash
# On Raspberry Pi
sudo apt-get install portaudio19-dev
pip3 install pyaudio
```

## Usage

```bash
cd /home/va55/code/cinema-chat/mcp

# Make sure dependencies are installed
pip3 install -r requirements.txt
pip3 install pyaudio

# Set audio device (optional - uses default if not set)
echo "hw:1,0" > /home/twistedtv/audio_device.conf

# Run the client
export BACKEND_URL="http://YOUR_SERVER_IP:8765/api"
python3 pi_daily_client_audio_sender.py
```

## Key Differences from Original Client

| Feature | Original (rtvi) | New (audio_sender) |
|---------|----------------|-------------------|
| Audio capture | Expected Daily SDK to handle | Uses PyAudio to capture |
| Virtual mic | Not created | Created with `create_microphone_device()` |
| Audio frames | Never sent | Continuously written with `write_frames()` |
| deviceId | Tried to use hardware name | Uses virtual device name |
| Threading | None | Background thread for audio capture |
| Dependencies | daily, httpx | daily, httpx, pyaudio |

## Testing

Once running, you should see:

```
Creating virtual microphone device...
Starting audio capture thread...
Opening audio stream (device_index=1)
✅ Audio capture started
Joining room: https://...
✅ Joined Daily.co room
🎤 Microphone active - speaking should now be captured
🎤 Speak now - audio is being captured!
```

Then speak into the microphone and watch the backend logs for transcription!

## Why This is Complicated

The Daily Python SDK is designed primarily for **bots** (services that receive audio and send synthesized speech), not **participants** (humans using microphones). For bots:
- Input: Receive audio from participants (automatic)
- Output: Send TTS audio (you write frames)

For participants (like our Pi client):
- Input: Send mic audio (you write frames) ← This is what we needed to add
- Output: Receive bot audio (automatic)

The browser SDK handles both directions automatically, but the Python SDK requires manual frame writing for anything you want to SEND.

## References

- [Daily Python SDK - Create Microphone Device](https://reference-python.daily.co/api_reference.html#daily.Daily.create_microphone_device)
- [Daily Python SDK - Virtual Microphone](https://reference-python.daily.co/types.html#virtualmicrophonedevice)
- [PyAudio Documentation](https://people.csail.mit.edu/hubert/pyaudio/docs/)
