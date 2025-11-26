# Static Noise Idle Display Solution

## Problem
When MPV plays video with DRM (`--drm-device=/dev/dri/card1`) and display management commands (`chvt`, framebuffer blanking), the network stack gets completely blocked on the Raspberry Pi.

## Solution
Instead of managing display sleep/wake states, continuously play a looping white static noise video (like old TV "no signal") when the system is idle.

## Components

1. **[generate_static.py](mcp/generate_static.py)** - Generates a 10-second white noise video
   - Uses OpenCV and NumPy to create random grayscale noise frames
   - Output: `/home/twistedtv/videos/static.mp4`

2. **[play_static_loop.sh](mcp/play_static_loop.sh)** - Plays static video in infinite loop
   - Wakes up display on start
   - Loops MPV with `--loop=inf` flag
   - Auto-restarts if MPV exits

3. **[video_playback_service_mpv.py](mcp/video_playback_service_mpv.py)** - Video playback service
   - `stop_playback()` kills BOTH the static loop script AND all mpv processes
   - Uses `pkill -f play_static_loop.sh` to stop the bash script
   - Uses `pkill -9 mpv` to kill all MPV instances
   - Plays actual content when requested
   - **NO display management commands** - display is always on after static loop starts

## How It Works

1. **Startup**: Static loop script starts playing `/home/twistedtv/videos/static.mp4` in infinite loop
2. **Idle State**: Display shows white noise static continuously
3. **Content Request**: Video playback service kills static loop via `stop_playback()`, plays content
4. **After Content**: Static loop automatically restarts (or restart manually)

## Benefits

- Display always active (no sleep/wake needed)
- No problematic `chvt`/framebuffer commands during playback
- Network remains accessible at all times
- Aesthetically appropriate for art installation
- Simple, reliable solution

## Usage

```bash
# Generate static video (one-time setup)
python3 /home/twistedtv/generate_static.py

# Start static loop (run at startup or in background)
/home/twistedtv/play_static_loop.sh &

# Play actual content (automatically stops static)
curl -X POST http://192.168.1.201:5000/play \
  -H 'Content-Type: application/json' \
  -d '{"video_path":"test.mp4","start":0,"end":5}'

# Restart static loop after content (if needed)
/home/twistedtv/play_static_loop.sh &
```

## Future Enhancement
Create a systemd service to auto-start the static loop on boot and auto-restart after content playback completes.
