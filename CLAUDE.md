# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Cinema-Chat** is an art installation where users speak into an old phone and converse with a chatbot that responds exclusively through old movie clips displayed on a TV. The system uses semantic search to find contextually appropriate video clips that serve as the bot's "voice."

## Architecture

### System Components

1. **Voice Bot Frontend (Python/FastAPI)** - Located in `frontend/`
   - Speech-to-Text (Whisper) for phone audio input
   - LLM conversation management (OpenAI/Anthropic)
   - MCP client integration for video selection
   - Based on simplified version of `the-turning-point` project
   - **Removed from the-turning-point**: Hume AI emotion analysis, TTS (replaced by video), Daily.co/WebRTC (direct audio input), Next.js web interface

2. **MCP Server (Python)** - Located in `mcp/`
   - Interfaces with GoodCLIPS semantic search API
   - Video playback control via ffmpeg
   - Converts LLM responses into video clip selections
   - Exposes tools that LLM can call to search and play videos

3. **GoodCLIPS API Backend (Go)** - Located in root directory
   - Developed by Massimo (separate work stream)
   - Go + Postgres (pgvector) + Redis
   - Multi-modal video embeddings (visual, audio, text)
   - Provides REST API endpoints for semantic scene search
   - Repository: https://github.com/byron-the-bulb/cinema-chat

## Reference Projects

### The Turning Point
Repository: https://github.com/byron-the-bulb/the-turning-point
**Located in**: `frontend/` directory (cloned as base)

**Components we're using:**
- FastAPI backend for bot orchestration
- Pipecat SDK for conversation pipeline (simplified)
- Whisper STT for voice recognition
- OpenAI GPT for LLM
- GPU-accelerated Docker containers

**Components we're keeping (minimal changes):**
- ✅ Next.js web frontend - runs locally on installation computer
- ✅ Daily.co WebRTC - for audio transport (phone mic → browser)
- ✅ Whisper STT, OpenAI GPT, Pipecat pipeline
- ✅ FastAPI backend orchestration

**Components we're removing:**
- ❌ Hume AI emotion analysis (optional, can keep for future)
- ❌ TTS providers (Cartesia, ElevenLabs, OpenAI TTS) - **replaced by video clips**
- ❌ Resolume VJ integration - not needed

**Key adaptations for cinema-chat:**
- **Installation setup**: Browser runs on local computer, not accessed remotely
- **Audio input**: Phone connected to computer's audio input → browser captures via Web Audio API
- **Output**: Video clips via MCP **instead of TTS audio**
- **Video display**: TV is secondary monitor showing video output
- **LLM role**: Generates semantic descriptions for video search, not text to be spoken
- **Frontend purpose**: Shows conversation state, selected clips, debugging (curator can monitor)

### GoodCLIPS Semantic Search
Repository: https://github.com/byron-the-bulb/cinema-chat

**Key API endpoint:**
- `POST /api/v1/search/scenes` - Search for scenes matching a text query
- Returns top-K most similar video clips based on multi-modal embeddings

**Embedding modalities:**
- Visual (InternVL3.5/InternVideo2)
- Visual (CLIP ViT-B/32)
- Audio (LAION-CLAP)
- Text (e5-base-v2 captions)

## Tech Stack

### Core Technologies
- **Language**: Python 3.11+
- **Framework**: FastAPI (following the-turning-point pattern)
- **Speech Recognition**: Whisper (OpenAI)
- **LLM**: OpenAI GPT or Anthropic Claude
- **MCP**: Model Context Protocol for tool calling
- **Video Playback**: ffmpeg
- **Containerization**: Docker + Docker Compose

### Dependencies

**Frontend (Voice Bot):**
- `fastapi` - API framework
- `pipecat-ai` - Conversation pipeline (simplified from the-turning-point)
- `openai-whisper` - STT
- `openai` or `anthropic` - LLM providers
- `mcp` - Model Context Protocol SDK (client)
- `pyaudio` or `sounddevice` - Direct audio input from phone

**MCP Server:**
- `mcp` - Model Context Protocol SDK (server)
- `ffmpeg-python` - Video playback control
- `httpx` - HTTP client for GoodCLIPS API
- `pydantic` - Data validation

## Development Setup

### Prerequisites
- Docker + Docker Compose
- NVIDIA GPU (recommended for Whisper STT)
- Access to GoodCLIPS API instance
- OpenAI/Anthropic API key
- Raspberry Pi (for video playback on TV)

### Raspberry Pi File Management Workflow

**CRITICAL: Always edit files locally first, then sync to Pi**

The Raspberry Pi runs several components:
- Video playback service (`video_playback_service_mpv.py`)
- Daily.co client (`pi_daily_client_rtvi.py`)
- Next.js frontend (started via API call from frontend)

**Key files that run on Pi:**
- **MCP/Backend**:
  - Local: `mcp/video_playback_service_mpv.py` → Pi: `/home/twistedtv/video_playback_service_mpv.py`
  - Local: `mcp/pi_daily_client_rtvi.py` → Pi: `/home/twistedtv/pi_daily_client_rtvi.py`
  - Local: `mcp/pi_daily_client_rtvi_v2.py` → Pi: `/home/twistedtv/pi_daily_client_rtvi_v2.py`
- **Frontend API**:
  - Local: `cinema-bot-app/frontend-next/pages/api/start_pi_client.ts` (runs on Pi via Next.js)
  - Local: `data/videos/streaming_server.py` (HTTP video server, runs on development machine)

**Workflow:**
1. **Edit locally FIRST**: Always make changes to files in the local repo
   - MCP files: Edit in `mcp/` directory
   - Frontend API files: Edit in `cinema-bot-app/frontend-next/pages/api/` directory
   - Video server: Edit in `data/videos/` directory
2. **Sync to Pi**: Use scp/rsync to copy updated files to the Pi:
   ```bash
   # Sync MCP/backend files
   scp mcp/video_playback_service_mpv.py twistedtv@192.168.1.201:/home/twistedtv/
   scp mcp/pi_daily_client_rtvi.py twistedtv@192.168.1.201:/home/twistedtv/
   scp mcp/pi_daily_client_rtvi_v2.py twistedtv@192.168.1.201:/home/twistedtv/

   # Sync frontend (Next.js runs on Pi)
   rsync -av --exclude node_modules cinema-bot-app/frontend-next/ twistedtv@192.168.1.201:~/cinema-chat/frontend-next/
   ```
3. **Restart services on Pi**: After syncing, restart the affected services
   - Video playback service: `pkill -f video_playback_service_mpv.py && python3 /home/twistedtv/video_playback_service_mpv.py &`
   - Pi Daily client: Automatically started by Next.js API
   - Next.js: `cd ~/cinema-chat/frontend-next && npm run dev`
4. **Commit to git**: Commit the local changes so they're tracked in version control

**Never:**
- Edit files directly on the Pi via SSH
- Make changes on Pi without syncing back to local repo
- Assume local and Pi files are in sync - always verify before making changes
- Edit Pi files and forget to commit changes to git

### Environment Variables
```bash
# LLM Configuration
OPENAI_API_KEY=sk-...
# or
ANTHROPIC_API_KEY=sk-ant-...

# GoodCLIPS API
GOODCLIPS_API_URL=http://localhost:8080
GOODCLIPS_API_KEY=... (if required)

# Video Configuration
VIDEO_OUTPUT_DEVICE=/dev/video0  # TV output
AUDIO_INPUT_DEVICE=hw:0,0        # Phone input

# Paths
VIDEOS_PATH=/data/videos
```

### Project Structure
```
cinema-chat/
├── cinema-bot-app/             # Voice bot (adapted from the-turning-point)
│   └── backend/
│       ├── Dockerfile
│       ├── build.sh
│       ├── requirements.txt
│       └── src/
│           └── cinema-bot/     # Bot implementation
│               ├── server.py              # FastAPI server
│               ├── cinema_bot.py          # Main bot logic
│               ├── cinema_script.py       # Conversation flow definitions
│               ├── mcp_client.py          # MCP client for video selection
│               ├── custom_flow_manager.py # Flow state management
│               ├── status_utils.py        # Status updates to frontend
│               ├── cloudwatch_logger.py   # AWS CloudWatch integration
│               └── video_only_filter.py   # Filter LLM text (unused)
├── mcp/                        # MCP server for video selection ✅ IMPLEMENTED
│   ├── mock_server.py          # Mock MCP server with keyword search
│   ├── server.py               # Real MCP server (for GoodCLIPS integration)
│   └── requirements.txt
├── cmd/                        # Go API (Massimo's work)
├── internal/                   # Go API internals (Massimo's work)
├── migrations/                 # Database migrations (Massimo's work)
├── docker-compose.yml          # For GoodCLIPS API
├── CLAUDE.md                   # This file - primary documentation for Claude
└── .env.example
```

## How It Works

### Simplified Architecture

```
                Installation Computer
    ┌───────────────────────────────────────────────┐
    │                                               │
    │  Phone Audio Input                            │
    │         ↓                                     │
    │  Next.js Web App (Browser)                    │
    │         ↓                                     │
    │  Daily.co WebRTC → FastAPI Backend            │
    │         ↓                                     │
    │  Whisper STT → LLM → MCP Client               │
    │                        ↓                      │
    │                   MCP Server                  │
    │                        ↓                      │
    │                 GoodCLIPS API                 │
    │                        ↓                      │
    │                     ffmpeg                    │
    │                        ↓                      │
    └────────────────────────┼─────────────────────┘
                             ↓
                        TV Output
```

**The flow is:**
1. **Audio Input**: Phone connected to computer's audio input
2. **Browser**: Next.js app running in browser captures audio via Web Audio API
3. **Transport**: Audio sent via Daily.co WebRTC to FastAPI backend
4. **Transcription**: Whisper STT converts speech to text
5. **Understanding**: LLM processes conversation and decides what to "say" back
6. **Video Selection**: LLM calls MCP tool with semantic description (e.g., "a person nodding in agreement")
7. **Search**: MCP server queries GoodCLIPS API for matching video clips
8. **Playback**: MCP server plays best matching clip via ffmpeg
9. **Display**: Video shows on TV (secondary monitor/output)
10. **Monitor**: Browser shows conversation state, selected clips, debugging info

**Key Point**: The LLM doesn't generate text to be spoken - it generates semantic descriptions of scenes/emotions to search for in the video library. TTS is completely replaced by video playback.

### Conversation Flow

1. **User speaks into phone** → Audio captured via microphone
2. **Whisper STT** → Audio transcribed to text
3. **LLM processes** → Generates response intent/meaning
4. **LLM calls MCP tool** → Requests video clip with semantic description
5. **MCP server queries GoodCLIPS** → Semantic search for matching scene
6. **MCP returns video path** → Best matching clip identified
7. **ffmpeg plays video** → Clip displayed on TV
8. **Wait for user** → User responds to video, cycle continues

### MCP Tools

The MCP server should expose tools for:

**`search_and_play_clip`**
- Input: Text description of desired scene/emotion/context
- Process: Query GoodCLIPS API, select best match
- Output: Play video on TV, return clip metadata

**`stop_playback`** (optional)
- Stop current video playback

### GoodCLIPS API Integration

**Search endpoint:**
```python
POST {GOODCLIPS_API_URL}/api/v1/search/scenes
{
  "query": "a person looking confused",
  "top_k": 5,
  "modalities": ["visual", "text", "audio"]
}
```

**Response:**
```json
{
  "scenes": [
    {
      "video_id": "movie_1.mp4",
      "start_time": 123.45,
      "end_time": 128.90,
      "similarity_score": 0.89,
      "caption": "Character scratches head in confusion"
    }
  ]
}
```

## Current Status (Updated: 2025-11-20)

### ✅ Implemented and Working

1. **MCP Mock Server** (`mcp/mock_server.py`)
   - Keyword-based video search with fallback defaults
   - `search_video_clips` tool - searches mock video library
   - `play_video_by_params` tool - returns video metadata
   - Fixed infinite loop bug in scene matching
   - 5 test videos from educational films (Hemo the Magnificent, Gateway to the Mind)

2. **Cinema Bot Backend** (`cinema-bot-app/backend/src/cinema-bot/`)
   - FastAPI server for bot instances
   - Whisper STT for speech-to-text
   - OpenAI GPT-4.1 for LLM
   - Pipecat pipeline for audio processing
   - Daily.co WebRTC for audio transport
   - MCP client with stdio communication
   - Two-conversation architecture:
     - User-facing: User input → Video description (via function calls)
     - Behind-the-scenes: User input → LLM reasoning → MCP tools → Video selection
   - Function handlers for `search_video_clips` and `play_video_by_params`
   - Status updates to frontend via RTVIServerMessageFrame
   - Conversation flow management with Pipecat-Flows

3. **Environment Configuration**
   - `.env` files updated with Cinema Chat naming
   - Environment variables: `WHISPER_DEVICE`, `REPO_ID`, `CLOUDWATCH_LOG_GROUP`
   - Backward compatibility maintained for old `SPHINX_*` variables

4. **Docker Infrastructure**
   - Dockerfile updated for `cinema-bot` directory structure
   - Build scripts updated to `cinema-chat-bot` image name
   - CloudWatch logging integration

### 🔄 Architecture Decisions Made

- **No TTS**: Videos serve as the bot's voice, no text-to-speech
- **No Hume AI**: Emotion detection not used (removed from reference project)
- **Stdio MCP**: Using stdin/stdout for MCP communication (not HTTP)
- **Mock before Real**: Using mock MCP server with keywords before integrating GoodCLIPS API
- **Function Calling**: LLM uses function calls to search/play videos, text responses blocked
- **Display Messages**: Reasoning and video metadata sent to frontend but NOT added to LLM context

### 🐛 Bugs Fixed

1. **MCP Server infinite loop** - Scene matching could loop forever when insufficient scenes available
2. **MCP Client deadlocks** - Added timeouts to prevent lock being held forever
3. **Messages not appearing** - Changed from `queue_frame()` to `status_updater.update_status()`
4. **Continuous video playback** - Removed display messages from LLM context to prevent triggering responses
5. **Incorrect captions** - Updated 5 video captions with actual dialogue

### 🚧 Known Issues / TODO

1. **GoodCLIPS integration** - Mock server works, real API integration pending
2. **Video playback** - Currently returns metadata, actual ffmpeg playback not implemented
3. **Frontend** - Web UI exists but needs testing with current architecture
4. **Hardware setup** - Phone input and TV output not yet configured

## Development Commands

```bash
# Run MCP mock server (terminal 1)
cd mcp
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 mock_server.py

# Run cinema bot backend (terminal 2)
cd cinema-bot-app/backend/src/cinema-bot
python3 server.py
```

## Key Design Considerations

### Video Playback Strategy
- Pre-buffer next likely clip for faster response
- Maintain library of "fallback" clips for common situations
- Handle interruptions gracefully (user speaks during playback)

### LLM Prompt Engineering
- Instruct LLM to think about visual metaphors
- Guide LLM to describe scenes it wants (not dialogue)
- Example: Instead of "I understand," request "a person nodding thoughtfully"

### Conversation Memory
- Track conversation history for context
- Consider emotional arc of interaction
- Select clips that build narrative continuity

### Performance
- GoodCLIPS search should return in <500ms
- Video playback should start within 1 second of query
- Use GPU acceleration for Whisper (real-time transcription)

## Hardware Setup Notes

### Phone Input
- Connect vintage phone to audio interface
- Configure as system microphone input
- May need impedance matching for old phone hardware

### TV Output
- HDMI or composite video output
- Configure as secondary display
- Full-screen video playback mode

## Testing Strategy

1. **Unit tests**: Test individual components (STT, MCP, video player)
2. **Integration tests**: Test conversation flow end-to-end
3. **Performance tests**: Measure latency at each stage
4. **User tests**: Actual conversations with phone/TV setup

## Troubleshooting

### Common Issues
- **Slow video search**: Check GoodCLIPS API performance, reduce top_k
- **Audio quality**: Adjust microphone gain, test with different phones
- **Video stuttering**: Check ffmpeg hardware acceleration, disk I/O
- **Context mismatch**: Improve LLM prompting, expand video library

## Implementation Roadmap

### ✅ Phase 1: MCP Server (COMPLETED)
1. ✅ Build basic MCP server with video search and playback tools
2. ⏳ Integrate with GoodCLIPS API (mock server working, real API pending)
3. ⏳ Implement ffmpeg video playback control (metadata only currently)
4. ✅ Test with manual MCP client

### ✅ Phase 2: Voice Bot Adaptation (COMPLETED)
1. ✅ Minimal changes to the-turning-point:
   - ✅ Replace TTS output with MCP video selection calls
   - ✅ Add MCP client integration to bot logic
   - ✅ Remove Hume AI emotion detection
   - ✅ Clean up all old project naming
2. ✅ Update LLM prompts to generate video search descriptions
3. ✅ Adapt Pipecat pipeline: audio in → transcription → LLM → MCP (no TTS out)

### ✅ Phase 3: Integration & Testing (MOSTLY COMPLETED)
1. ✅ Connect voice bot to MCP server (via stdio)
2. ✅ Test end-to-end conversation flow (working with mock data)
3. ✅ Optimize LLM prompts for video search
4. ✅ Performance tuning (fixed deadlocks, infinite loops, message routing)

### ⏳ Phase 4: Hardware Integration (PENDING)
1. ⏳ Connect phone to computer's audio input
2. ⏳ Configure browser to capture from correct audio device
3. ⏳ Set up TV as secondary monitor for video output
4. ⏳ Configure ffmpeg to output to TV display
5. ⏳ Test end-to-end: phone → browser → bot → video → TV

### Next Steps
1. Test the complete system with mock MCP server and frontend
2. Integrate real GoodCLIPS API (replace mock keyword search)
3. Implement actual video playback via ffmpeg
4. Set up hardware (phone input, TV output)
5. End-to-end testing with real hardware

## Future Enhancements
- Multi-turn conversation optimization
- Curator mode: Manual override for clip selection
- Analytics: Track which clips resonate most with users
- Emotion detection in user's voice (optional, like the-turning-point's Hume AI)
