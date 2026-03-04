# TwistedTV Video Server

Video file storage and HTTP streaming server for the TwistedTV installation. This runs on the development machine and serves video files to the Raspberry Pi.

## Overview

The video server provides:
- HTTP streaming of video files
- Range request support for efficient playback
- Video file storage and organization
- Simple Flask-based implementation

## Architecture

```
Development Machine              Raspberry Pi
┌──────────────────┐            ┌──────────────┐
│ Video Server     │──HTTP──────>│ MPV Player   │
│ (Flask)          │            │              │
│ Port 9000        │            │              │
└──────────────────┘            └──────────────┘
        │
        ├── videos/
        │   ├── video1.mp4
        │   ├── video2.mkv
        │   └── ...
```

## Setup

### Prerequisites
- Python 3.8+
- Video files in supported formats (MP4, MKV, AVI, etc.)

### Installation

```bash
cd twistedtv-video-server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Running

### Start Streaming Server

```bash
cd twistedtv-video-server
python3 streaming_server.py
```

The server will start on `http://0.0.0.0:9000`

### Alternative Server (Threaded)

For better performance with multiple clients:

```bash
python3 threaded_server.py
```

## Adding Videos

1. Place video files in `twistedtv-video-server/videos/` directory
2. Supported formats: MP4, MKV, AVI, MOV, WebM
3. Videos are accessed via: `http://<server-ip>:9000/<filename>`

### Video Organization

```
videos/
├── hemo_the_magnificent.mp4.mkv    # Full video files
├── gateway_to_the_mind.mp4
└── video_2_keyframes/              # Processed video data
    ├── keyframe_0001.jpg
    └── ...
```

## Configuration

### Port Configuration

Default port: `9000`

To change, edit `streaming_server.py`:

```python
app.run(host='0.0.0.0', port=9000, threaded=True)
```

### Firewall Configuration

If the Pi can't connect, ensure port 9000 is open:

```bash
# Linux (ufw)
sudo ufw allow 9000

# Linux (iptables)
sudo iptables -A INPUT -p tcp --dport 9000 -j ACCEPT
```

## File Structure

```
twistedtv-video-server/
├── streaming_server.py     # Main Flask server (current)
├── threaded_server.py      # Threaded variant
├── requirements.txt        # Python dependencies (Flask)
├── .gitignore             # Ignore large video files
├── README.md              # This file
└── videos/                # Video file storage
    ├── *.mp4
    ├── *.mkv
    └── video_*_keyframes/ # Processed data
```

## API

### GET /<filename>

Stream a video file with range request support.

**Request:**
```http
GET /video1.mp4 HTTP/1.1
Host: localhost:9000
Range: bytes=0-1023
```

**Response:**
```http
HTTP/1.1 206 Partial Content
Content-Range: bytes 0-1023/1048576
Content-Type: video/mp4

[Binary video data]
```

### Features

- ✅ Range request support (HTTP 206)
- ✅ Proper MIME type detection
- ✅ Concurrent client support
- ✅ Directory listing disabled (security)

## Video File Requirements

### Recommended Formats
- **Container**: MP4 (best compatibility)
- **Video Codec**: H.264 (most compatible)
- **Audio Codec**: AAC

### Converting Videos

```bash
# Convert to H.264 MP4
ffmpeg -i input.mkv -c:v libx264 -c:a aac output.mp4

# Optimize for streaming
ffmpeg -i input.mp4 -movflags +faststart output_optimized.mp4
```

### File Size Considerations

- Keep individual clips under 50MB for faster loading
- Use lower bitrates for better network performance
- Consider video resolution (720p recommended for installation)

## Troubleshooting

### Pi Can't Connect to Server

```bash
# Check server is running
curl http://localhost:9000/

# Check from Pi
curl http://192.168.1.100:9000/

# Check firewall
sudo ufw status
```

### Videos Won't Play

```bash
# Check video file format
ffprobe video.mp4

# Test with curl
curl -I http://localhost:9000/video.mp4

# Check file permissions
ls -la videos/
```

### Performance Issues

```bash
# Use threaded server
python3 threaded_server.py

# Check network bandwidth
iperf3 -s  # On server
iperf3 -c <server-ip>  # On Pi

# Monitor server load
htop
```

## Storage Management

### Large Video Library

For large video collections, consider:

1. **Symbolic links** to external storage:
   ```bash
   ln -s /mnt/external_drive/videos/* twistedtv-video-server/videos/
   ```

2. **Network mount** (NAS):
   ```bash
   sudo mount -t nfs nas:/videos twistedtv-video-server/videos/
   ```

3. **Git LFS** for version control:
   ```bash
   git lfs track "*.mp4"
   git lfs track "*.mkv"
   ```

### .gitignore

Large video files should be git-ignored:

```gitignore
# Large video files
videos/*.mp4
videos/*.mkv
videos/*.avi

# Keep metadata
!videos/*.json
!videos/*.txt
```

## Development

### Adding New Features

Example: Add authentication:

```python
from flask import Flask, request, abort
app = Flask(__name__)

API_KEY = "your-secret-key"

@app.before_request
def check_auth():
    if request.headers.get('X-API-Key') != API_KEY:
        abort(401)
```

### Logging

Add request logging:

```python
import logging
logging.basicConfig(level=logging.INFO)

@app.route('/<path:filename>')
def serve_video(filename):
    logging.info(f"Serving {filename} to {request.remote_addr}")
    return send_from_directory(VIDEO_DIR, filename)
```

## Security Considerations

- Server runs on local network only (not exposed to internet)
- No authentication required (local installation)
- Directory listing disabled
- Only serves files from `videos/` directory
- No write access via HTTP

## Production Deployment

For production use:

```bash
# Install gunicorn
pip install gunicorn

# Run with gunicorn
gunicorn -w 4 -b 0.0.0.0:9000 streaming_server:app
```

## License

See root LICENSE file.
