# TwistedTV Pi Client

Raspberry Pi components for the TwistedTV art installation. All components in this directory run on the Raspberry Pi at the installation site.

## Components

### `pi_daily_client/` - Daily.co Audio Client
Handles real-time audio transport between Pi and server:
- Connects to Daily.co rooms
- Captures audio from phone/microphone using ALSA
- Receives audio responses from server
- Single production-ready client: `pi_daily_client.py`

### `video_playback/` - Video Playback Service
Plays video clips on the TV:
- MPV-based video player (current)
- VLC-based player (alternative)
- Listens for video playback commands
- Fetches videos from video streaming server

### `frontend/` - Next.js Web Interface
Local monitoring and control interface:
- Shows conversation state
- Displays video selections
- Audio device configuration
- Debugging tools
- **Runs on the Pi, not the server**

## Hardware Requirements

- Raspberry Pi 4 (4GB+ RAM recommended)
- HDMI connection to TV
- Audio input (USB audio interface or built-in)
- Network connection (Ethernet recommended)
- SD card (32GB+)

## Setup

### 1. System Dependencies

```bash
sudo apt-get update
sudo apt-get install -y python3-pip nodejs npm mpv alsa-utils
```

### 2. Python Environment

```bash
cd /home/twistedtv
python3 -m venv venv_daily
source venv_daily/bin/activate
cd twistedtv-pi-client
pip install -r requirements.txt
```

### 3. Node.js Frontend

```bash
cd twistedtv-pi-client/frontend
npm install
```

### 4. Audio Configuration

```bash
# List audio devices
arecord -L

# Test audio capture
arecord -D <device> -f cd test.wav

# Configure default device in /etc/asound.conf or ~/.asoundrc
```

### 5. Environment Variables

Create `.env` in `twistedtv-pi-client/`:

```bash
# Daily.co
DAILY_API_KEY=...

# Video Server
VIDEO_SERVER_URL=http://192.168.1.100:9000  # Your dev machine IP

# Audio Device
AUDIO_INPUT_DEVICE=hw:1,0  # From arecord -L

# Server URL
BACKEND_URL=http://192.168.1.100:8765  # Your server IP
```

## Deployment

### Deploy from Development Machine

```bash
# From the development machine
cd twistedtv-pi-client/scripts
./deploy_to_pi.sh
```

This will:
1. Sync all Pi client files to the Pi
2. Update Python environment
3. Restart services if needed

### Manual Deployment

```bash
# From development machine
rsync -av --exclude node_modules \
  twistedtv-pi-client/ \
  twistedtv@192.168.1.201:~/twistedtv-pi-client/
```

## Running

### Start Frontend (Next.js)

```bash
cd ~/twistedtv-pi-client/frontend
npm run dev
# or for production
npm run build && npm start
```

Access at: `http://localhost:3000`

### Services Are Auto-Started

The video playback and Daily client services are automatically started by the frontend when a conversation begins. You don't need to start them manually.

If you need to start them manually:

```bash
# Video Playback Service
cd ~/twistedtv-pi-client/video_playback
python3 video_playback_service_mpv.py &

# Pi Daily Client (started automatically by API)
cd ~/twistedtv-pi-client/pi_daily_client
python3 pi_daily_client.py <room_url> <token>
```

## File Structure

```
pi_daily_client/
└── pi_daily_client.py              # Daily.co client with ALSA audio

video_playback/
├── video_playback_service_mpv.py  # MPV player (current)
├── video_playback_service_vlc.py  # VLC player (alt)
└── video_player.py                 # Shared utilities

frontend/
├── pages/
│   ├── index.tsx                # Main UI
│   ├── api/
│   │   ├── start_pi_client.ts   # Start Pi services
│   │   └── cleanup_pi.ts        # Cleanup processes
│   └── ...
├── components/
│   ├── ChatLog.tsx               # Conversation display
│   └── AudioDeviceSelector.tsx  # Audio config
└── package.json

scripts/
└── deploy_to_pi.sh              # Deployment script
```

## Troubleshooting

### No Audio Input
```bash
# Check devices
arecord -L
arecord -l

# Test recording
arecord -D hw:1,0 -f cd test.wav

# Check ALSA config
cat ~/.asoundrc
```

### Video Not Playing
```bash
# Check MPV installation
mpv --version

# Test video manually
mpv http://192.168.1.100:9000/test_video.mp4

# Check video service logs
tail -f /tmp/video_mpv.log
```

### Daily.co Connection Issues
```bash
# Check network
ping daily.co

# Check Pi client logs
ps aux | grep pi_daily_client

# Kill and restart
pkill -f pi_daily_client
```

### Frontend Not Accessible
```bash
# Check if Next.js is running
ps aux | grep next

# Check port
netstat -tulpn | grep 3000

# Restart frontend
cd ~/twistedtv-pi-client/frontend
npm run dev
```

## Development

### Testing Audio
```bash
cd pi_daily_client
python3 test_audio.py
```

### Testing Video Playback
```bash
cd frontend
npm run dev

# Then navigate to:
# http://localhost:3000
# Click "Trigger Video" button
```

### Viewing Logs
```bash
# Video playback logs
tail -f /tmp/video_mpv.log

# Pi client logs (if running manually)
tail -f /tmp/pi_client.log

# Frontend logs
# Check terminal where npm run dev is running
```

## Auto-Start on Boot (Optional)

Create systemd service for frontend:

```bash
sudo nano /etc/systemd/system/twistedtv-frontend.service
```

```ini
[Unit]
Description=TwistedTV Frontend
After=network.target

[Service]
Type=simple
User=twistedtv
WorkingDirectory=/home/twistedtv/twistedtv-pi-client/frontend
ExecStart=/usr/bin/npm start
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable twistedtv-frontend
sudo systemctl start twistedtv-frontend
```

## License

See root LICENSE file.
