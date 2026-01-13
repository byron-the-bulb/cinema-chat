# Cinema-Chat MCP Server

Model Context Protocol (MCP) server for video clip search and playback. This server exposes tools that allow an LLM to search for and play video clips based on semantic descriptions.

## ⚠️ Current Status: BLOCKED

**This MCP server is complete but cannot be tested yet** because the GoodCLIPS API is missing required functionality:

1. **Scene persistence bug**: Scenes are not being saved to database after detection
2. **Missing text-to-video search**: No `/api/v1/search/semantic` endpoint yet (only scene-to-scene similarity exists)

See [STATUS.md](../STATUS.md) for details. Waiting on Massimo's GoodCLIPS API work stream.

## Overview

The MCP server acts as a bridge between:
- **LLM** (in the voice bot) - generates semantic descriptions
- **GoodCLIPS API** - performs semantic video search
- **ffmpeg** - handles video playback on TV

## Architecture

```
LLM → MCP Client → MCP Server → GoodCLIPS API
                       ↓
                   Video Player (ffmpeg)
                       ↓
                   TV Display
```

## Tools

### `search_and_play_video`
Primary tool for bot responses. Searches for a video clip matching a description and plays it.

**Input:**
- `description` (required): Semantic description of scene/emotion/action
- `limit` (optional): Number of results to consider (default: 5)

**Example:**
```json
{
  "description": "a person nodding in agreement",
  "limit": 5
}
```

### `stop_video`
Stops currently playing video.

### `search_video_clips`
Searches for clips WITHOUT playing them. Useful for exploring available content.

**Input:**
- `description` (required): Semantic description
- `limit` (optional): Max results (default: 5)

### `get_api_stats`
Returns GoodCLIPS database statistics.

## Installation

```bash
cd mcp
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the `mcp/` directory:

```bash
# GoodCLIPS API
GOODCLIPS_API_URL=http://localhost:8080
GOODCLIPS_API_KEY=  # Optional

# Video settings
VIDEOS_PATH=/data/videos
VIDEO_OUTPUT_DEVICE=  # Optional: specific display

# Search defaults
DEFAULT_SEARCH_LIMIT=5
MAX_SEARCH_LIMIT=20

# Logging
LOG_LEVEL=INFO
```

## Running the Server

### Standalone (for testing)
```bash
python server.py
```

The server will listen on STDIN/STDOUT following MCP protocol.

### With MCP Client
The server is designed to be called by an MCP client (like the voice bot). The client connects to the server and calls tools through the MCP protocol.

## Testing

Test individual components:

```bash
# Test GoodCLIPS API connection
python -c "
import asyncio
from goodclips_client import GoodCLIPSClient

async def test():
    async with GoodCLIPSClient('http://localhost:8080') as client:
        stats = await client.get_stats()
        print('Stats:', stats)

        results = await client.search_semantic('a person smiling', limit=3)
        for r in results:
            print(f'Scene {r.scene_index}: {r.duration:.1f}s')

asyncio.run(test())
"

# Test video playback
python -c "
import asyncio
from video_player import VideoPlayer

async def test():
    player = VideoPlayer()
    # Replace with actual video path
    await player.play_clip('/data/videos/test.mp4', 10.0, 15.0)
    await player.wait_for_completion()

asyncio.run(test())
"
```

## Dependencies

- **mcp**: Model Context Protocol SDK
- **httpx**: Async HTTP client for GoodCLIPS API
- **ffmpeg-python**: Python bindings for ffmpeg
- **pydantic**: Data validation
- **python-dotenv**: Environment configuration

## System Requirements

- Python 3.10+
- ffmpeg installed and in PATH
- Access to GoodCLIPS API
- Video files accessible at configured path

## How It Works

1. LLM decides to "respond" with a video
2. LLM calls `search_and_play_video` tool with description
3. MCP server searches GoodCLIPS API for matching scenes
4. Best matching clip is selected
5. ffmpeg plays the clip on TV
6. Tool returns success, bot waits for user response

## Troubleshooting

**"Connection refused" to GoodCLIPS API**
- Ensure GoodCLIPS API is running: `docker-compose up` in root directory
- Check GOODCLIPS_API_URL in .env

**"Video file not found"**
- Check VIDEOS_PATH matches actual video location
- Verify video files exist in `/data/videos/` (or configured path)

**Video doesn't play**
- Ensure ffmpeg is installed: `ffmpeg -version`
- Check ffplay works: `ffplay /data/videos/test.mp4`

**No results from search**
- Verify GoodCLIPS has processed videos (check `/api/v1/stats`)
- Try broader search descriptions

## Development

Run with debug logging:
```bash
LOG_LEVEL=DEBUG python server.py
```

## License

TBD
