# Cinema Chat Voice Bot

A conversational AI art installation that responds through movie clips instead of speech.

## Overview

Cinema Chat is an interactive art installation where users speak into a vintage telephone and converse with a chatbot that responds exclusively through old movie clips displayed on a TV. The system uses semantic search to find contextually appropriate video clips that serve as the bot's "voice."

## Key Features

- **Voice Input** - Phone audio captured and transcribed using Whisper STT
- **LLM Conversation** - OpenAI GPT-4.1 processes conversation and generates video search queries
- **Semantic Video Search** - MCP server with keyword/semantic search for video clips
- **Video Responses** - Bot "speaks" through carefully selected movie clips
- **Real-time Processing** - Low-latency pipeline for natural conversation flow
- **GPU Acceleration** - CUDA support for fast speech recognition

## Architecture

The system uses a two-conversation architecture:

1. **User-Facing Conversation**: User hears only video descriptions/captions
2. **Behind-the-Scenes**: LLM reasoning → MCP function calls → Video selection

### Components

- **Voice Bot Backend** (`backend/`) - FastAPI server with Pipecat pipeline, Whisper STT, GPT-4.1 LLM, MCP client
- **MCP Server** (`../mcp/`) - Model Context Protocol server for video search and playback
- **Frontend** (`frontend-next/`) - Next.js web interface for monitoring (optional)

## Getting Started

See [backend/README.md](backend/README.md) for setup instructions.

### Prerequisites

- Docker with NVIDIA support (for GPU acceleration)
- Python 3.11+
- API keys for:
  - Daily.co (for WebRTC audio transport)
  - OpenAI (for GPT-4.1 and Whisper)

### Quick Start

```bash
# Terminal 1: Start MCP mock server
cd ../mcp
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 mock_server.py

# Terminal 2: Start Cinema Chat backend
cd backend/src/cinema-bot
python3 server.py
```

## Documentation

- [Backend Documentation](backend/README.md) - Complete backend setup and API reference
- [CLAUDE.md](../CLAUDE.md) - Primary development documentation for Claude Code

## Technical Details

- **Speech-to-Text**: OpenAI Whisper (distil-medium-en)
- **LLM**: OpenAI GPT-4.1
- **Framework**: Pipecat SDK for audio pipeline
- **Transport**: Daily.co WebRTC
- **Video Search**: MCP (Model Context Protocol)
- **Deployment**: Docker containers with GPU support

## Project Status

✅ Voice bot backend functional
✅ MCP mock server with keyword search
✅ Two-conversation architecture implemented
⏳ GoodCLIPS API integration (pending)
⏳ Actual video playback via ffmpeg (pending)
⏳ Hardware setup (phone input, TV output)

See [CLAUDE.md](../CLAUDE.md) for detailed status and implementation roadmap.
