# Audio Device Setup for Cinema Chat

## Architecture Overview

The Cinema Chat system now uses a **headless Daily.co client** running on the Raspberry Pi instead of a browser-based client. This means audio device selection must be handled differently than the original browser-based approach.

### Old Architecture (Browser-based)
```
User's Browser
  ↓ (navigator.mediaDevices)
Enumerate local audio devices
  ↓
User selects device via AudioDeviceSelector
  ↓
Browser's Daily client uses selected device
```

### New Architecture (Pi-based)
```
Admin Panel (Browser on any computer)
  ↓ (API call to Pi)
Get list of Pi's audio devices
  ↓
User selects device via AudioDeviceSelector
  ↓ (API call to Pi)
Pi Daily client reconfigured to use selected device
  ↓
Pi captures audio from USB device
  ↓
Audio sent to Daily.co → Backend bot
```

## Current Status

### ✅ Completed
- USB audio device (card 1) detected on Pi: `hw:1,0`
- Audio recording tested and working: `arecord` successfully captures audio
- Environment variables configured: `ALSA_CARD=1` and `AUDIODEV=hw:1,0`
- Pi Daily client updated to set these environment variables

### ❌ Blocking Issues

#### 1. Backend API Port Forwarding (CRITICAL)
The backend API is not accessible from the Pi because port 8765 is not forwarded through Windows.

**Required Fix** (on Windows PowerShell as Administrator):
```powershell
# Add port proxy for backend API
netsh interface portproxy add v4tov4 listenport=8765 listenaddress=0.0.0.0 connectport=8765 connectaddress=172.28.172.5

# Add Windows Firewall rule
New-NetFirewallRule -DisplayName "Cinema Chat Backend API" -Direction Inbound -LocalPort 8765 -Protocol TCP -Action Allow

# Verify
netsh interface portproxy show all
```

Expected output should show BOTH ports:
```
Listen on ipv4:             Connect to ipv4:

Address         Port        Address         Port
--------------- ----------  --------------- ----------
0.0.0.0         9000        172.28.172.5    9000
0.0.0.0         8765        172.28.172.5    8765
```

#### 2. Audio Device Selection UI (TO BE IMPLEMENTED)
The current AudioDeviceSelector component enumerates devices from the **browser's** computer, not the Pi. We need to refactor it to work with remote devices.

## Implementation Plan

### Phase 1: Enable Backend Connectivity ⚠️ DO THIS FIRST
1. Set up Windows port forwarding for port 8765 (see above)
2. Verify Pi can reach backend: `curl http://192.168.1.143:8765/api/connect`
3. Test Pi Daily client connection

### Phase 2: Basic Audio (Current Approach)
The current implementation hardcodes the USB audio device in the Pi client:
- Environment: `ALSA_CARD=1`, `AUDIODEV=hw:1,0`
- This works if you only have one USB microphone
- **Pro**: Simple, no API needed
- **Con**: Not configurable via admin panel

### Phase 3: Dynamic Audio Device Selection (Future Enhancement)
To make audio device selection configurable via the admin panel:

#### A. Create Pi API Endpoints

**1. List Audio Devices** (`GET /api/pi/audio-devices`)
```python
# On Pi (or add to backend with SSH to Pi)
@app.get("/api/pi/audio-devices")
async def list_audio_devices():
    # Run: arecord -l
    # Parse output and return JSON
    return {
        "devices": [
            {
                "card": 1,
                "device": 0,
                "name": "USB Audio Device",
                "alsa_id": "hw:1,0"
            }
        ]
    }
```

**2. Set Audio Device** (`POST /api/pi/audio-device`)
```python
@app.post("/api/pi/audio-device")
async def set_audio_device(device_id: str):
    # Update environment variables for Pi client
    # Restart Pi Daily client with new settings
    # OR use Daily SDK's update_inputs() if available
    return {"success": True, "device": device_id}
```

#### B. Update AudioDeviceSelector Component

```typescript
// New component: PiAudioDeviceSelector.tsx
import { useState, useEffect } from 'react';

interface PiAudioDevice {
  card: number;
  device: number;
  name: string;
  alsa_id: string;
}

const PiAudioDeviceSelector = () => {
  const [devices, setDevices] = useState<PiAudioDevice[]>([]);
  const [selectedDevice, setSelectedDevice] = useState<string>('');

  useEffect(() => {
    // Fetch devices from Pi API
    fetch('/api/pi/audio-devices')
      .then(res => res.json())
      .then(data => {
        setDevices(data.devices);
        if (data.devices.length > 0) {
          setSelectedDevice(data.devices[0].alsa_id);
        }
      });
  }, []);

  const handleDeviceChange = async (alsa_id: string) => {
    setSelectedDevice(alsa_id);

    // Send to Pi to update device
    await fetch('/api/pi/audio-device', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_id: alsa_id })
    });
  };

  return (
    <div>
      <label>Pi Microphone Device:</label>
      <select value={selectedDevice} onChange={(e) => handleDeviceChange(e.target.value)}>
        {devices.map(dev => (
          <option key={dev.alsa_id} value={dev.alsa_id}>
            {dev.name} ({dev.alsa_id})
          </option>
        ))}
      </select>
    </div>
  );
};
```

#### C. Update Pi Daily Client

The Pi client would need to support dynamic reconfiguration:

```python
# In pi_daily_client_rtvi.py

class CinemaRTVIClient(EventHandler):
    def __init__(self, ...):
        # ...
        self.current_audio_device = os.getenv("AUDIODEV", "hw:1,0")

    def update_audio_device(self, alsa_id: str):
        """Update audio device without restarting client"""
        # Set environment variables
        os.environ["ALSA_CARD"] = alsa_id.split(':')[1].split(',')[0]
        os.environ["AUDIODEV"] = alsa_id

        # If Daily SDK supports update_inputs(), use it here
        # Otherwise, may need to rejoin the room
        logger.info(f"Audio device updated to: {alsa_id}")
```

## Testing Plan

### Test 1: Verify Port Forwarding
```bash
# From Pi:
curl -I http://192.168.1.143:8765/api/connect

# Expected: HTTP 200 or 405 (not connection refused)
```

### Test 2: Verify Audio Device Detection
```bash
# On Pi:
arecord -l

# Expected output showing USB Audio Device
```

### Test 3: Test Audio Recording
```bash
# On Pi:
arecord -D hw:1,0 -d 3 -f S16_LE -r 44100 -c 1 /tmp/test.wav

# Expected: 3-second recording, file size ~250KB
```

### Test 4: Test Pi Daily Client Connection
```bash
# Start Pi client and check logs:
tail -f /tmp/pi_client_audio.log

# Expected: "✅ Joined Daily.co room"
# Expected: "🎤 Streaming USB mic audio to bot"
```

### Test 5: End-to-End Audio Test
1. Start backend on WSL2
2. Start Pi Daily client
3. Speak into USB microphone on Pi
4. Check backend logs for transcription
5. Verify bot responds with video

## Current Audio Device Configuration

The Pi Daily client is currently configured to use:
- **ALSA Card**: 1 (USB Audio Device)
- **Device ID**: hw:1,0
- **Sample Rate**: 44100 Hz (hardware default)
- **Channels**: Mono (1 channel)

This is hardcoded in `/home/twistedtv/pi_daily_client_rtvi.py`:
```python
# Line 27-28
os.environ["ALSA_CARD"] = "1"
os.environ["AUDIODEV"] = "hw:1,0"
```

## Recommendations

### Short-term (Current Implementation)
1. ✅ **PRIORITY**: Set up port forwarding for port 8765
2. Use hardcoded USB audio device (hw:1,0)
3. Test end-to-end audio flow
4. Verify bot can hear and respond

### Medium-term (After Working)
1. Add Pi API endpoints for device enumeration
2. Update AudioDeviceSelector to query Pi instead of browser
3. Allow device selection from admin panel
4. Persist device selection across restarts

### Long-term (Production)
1. Auto-detect optimal audio device
2. Monitor audio levels and quality
3. Provide audio troubleshooting diagnostics
4. Support hot-plugging USB audio devices

## Troubleshooting

### "No audio detected"
- Check `arecord -l` to verify device is present
- Test recording with `arecord -D hw:1,0 ...`
- Verify ALSA environment variables are set
- Check Pi client logs for audio initialization errors

### "Cannot connect to backend"
- Verify port 8765 is forwarded: `netsh interface portproxy show all`
- Check Windows Firewall allows port 8765
- Test from Pi: `curl http://192.168.1.143:8765/api/connect`
- Verify backend is listening: `ss -tlnp | grep 8765`

### "Audio cuts out"
- Check USB power supply (Pi may not provide enough power)
- Use powered USB hub for audio device
- Monitor system logs for USB errors: `dmesg | grep -i usb`
