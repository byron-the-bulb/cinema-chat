# TwistedTV Server

Server-side components for the TwistedTV art installation. This runs on the development/cloud machine and handles:
- Voice conversation orchestration (FastAPI backend)
- MCP (Model Context Protocol) server for video search
- Integration with GoodCLIPS semantic search API

## Architecture

```
User Phone → Pi Client → TwistedTV Server → GoodCLIPS API
                ↓               ↓
            Daily.co        MCP Server
                              ↓
                        Video Selection
```

## Components

### `cinema_bot/` - Voice Bot Backend
FastAPI-based bot orchestration with:
- Whisper STT for speech-to-text
- OpenAI GPT/Anthropic Claude for LLM
- Pipecat SDK for conversation pipeline
- MCP client integration for video selection
- Daily.co WebRTC for audio transport

### `mcp_server/` - MCP Video Search Server
Model Context Protocol server that:
- Exposes video search tools to LLM
- Integrates with GoodCLIPS semantic search API
- Returns video clip metadata for playback

## Setup

### Prerequisites
- Python 3.10+
- CUDA-capable GPU (recommended for Whisper)
- Access to GoodCLIPS API
- OpenAI or Anthropic API key
- Daily.co API key

### Installation

```bash
cd twistedtv-server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Environment Variables

Create `.env` file:

```bash
# LLM Configuration
OPENAI_API_KEY=sk-...
# or
ANTHROPIC_API_KEY=sk-ant-...

# Daily.co WebRTC
DAILY_API_KEY=...

# GoodCLIPS API
GOODCLIPS_API_URL=http://localhost:8080
GOODCLIPS_API_KEY=...  # if required

# Whisper STT
WHISPER_DEVICE=cuda  # or cpu

# AWS CloudWatch (optional)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
CLOUDWATCH_LOG_GROUP=/twistedtv
```

## Running Locally

### Start MCP Server

```bash
cd twistedtv-server
python mcp_server/mock_server.py  # For testing with keyword search
# or
python mcp_server/server.py  # For real GoodCLIPS integration
```

### Start Backend Server

```bash
cd twistedtv-server/cinema_bot
python server.py
```

The FastAPI server will start on `http://localhost:8765`

## Docker Deployment

### Build Image

```bash
cd twistedtv-server
bash build.sh
```

### Run Container

```bash
docker run --gpus all \
  -e DAILY_API_KEY="..." \
  -e OPENAI_API_KEY="..." \
  -e WHISPER_DEVICE="cuda" \
  -p 8765:8765 \
  twistedtv-server:latest
```

## RunPod Deployment

The Docker image can be deployed to RunPod for GPU-accelerated hosting:

1. Push image to Docker Hub:
   ```bash
   docker tag twistedtv-server:latest yourusername/twistedtv-server:latest
   docker push yourusername/twistedtv-server:latest
   ```

2. Create RunPod template with:
   - Docker image: `yourusername/twistedtv-server:latest`
   - GPU: NVIDIA RTX 4000 Ada or RTX 4090
   - Memory: 15-24GB
   - Environment variables (see above)

## API Endpoints

- `GET /health` - Health check
- `POST /connect` - Create new conversation room
- `POST /register-video-service` - Register Pi video service PID
- `GET /conversation-status/{identifier}` - Get conversation state
- `POST /cleanup-daily-rooms` - Clean up old Daily.co rooms

## Development

### File Structure

```
cinema_bot/
├── server.py              # FastAPI entry point
├── cinema_bot.py          # Main bot logic
├── cinema_script.py       # Conversation flows
├── mcp_client.py          # MCP client integration
├── custom_flow_manager.py # Flow state management
├── status_utils.py        # Status updates
└── cloudwatch_logger.py   # AWS logging

mcp_server/
├── server.py              # Real MCP server (GoodCLIPS)
├── mock_server.py         # Mock server (keywords)
├── config.py              # Configuration
└── goodclips_client.py    # GoodCLIPS API client
```

### Adding New Features

- **New conversation flows**: Edit `cinema_script.py`
- **New MCP tools**: Add to `mcp_server/server.py`
- **New API endpoints**: Add to `cinema_bot/server.py`

## Troubleshooting

### Whisper Not Using GPU
- Check CUDA installation: `nvidia-smi`
- Verify `WHISPER_DEVICE=cuda` in environment
- Check PyTorch CUDA support: `python -c "import torch; print(torch.cuda.is_available())"`

### MCP Connection Issues
- Ensure MCP server is running first
- Check stdio communication is working
- Review MCP server logs for errors

### Daily.co Connection Failures
- Verify Daily.co API key is valid
- Check network connectivity
- Review Daily.co dashboard for room status

## License

See root LICENSE file.
