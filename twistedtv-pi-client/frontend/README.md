# Cinema Chat Frontend (Next.js)

This is a Next.js 15.3 implementation of the Cinema Chat interface that provides real-time voice conversations where the bot responds through contextually appropriate movie clips displayed on a TV.

## Features

- Built with Next.js 15.3 and React 19
- Integrated with Pipecat SDK using Daily Transport for audio streaming
- Real-time speech-to-text using Whisper
- Semantic video search integration via MCP (Model Context Protocol)
- API endpoints for connecting to RunPod GPU instances
- Chat history and conversation visualization
- **No TTS** - Bot responds exclusively through video clips

## Key Difference from Traditional Voice Bots

Unlike traditional voice bots that use Text-to-Speech (TTS), Cinema Chat responds through old movie clips:
- LLM generates semantic descriptions of desired scenes/emotions
- MCP server searches video library using GoodCLIPS semantic search
- Selected video clips play on TV as the bot's "voice"

## Getting Started

First, install the dependencies:

```bash
npm install
# or
yarn install
```

Then, create a `.env.local` file with the necessary environment variables (see Environment Variables section below).

Finally, run the development server:

```bash
npm run dev
# or
yarn dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to interact with Cinema Chat.

## Environment Variables

Create a `.env.local` file with the following variables:

```
# API URLs
NEXT_PUBLIC_API_URL=http://localhost:3000/api
NEXT_PUBLIC_WS_URL=ws://localhost:3000

# RunPod Configuration (optional - for cloud deployment)
NEXT_PUBLIC_RUNPOD_TEMPLATE_ID=your_runpod_template_id
RUNPOD_API_KEY=your_runpod_api_key

# Daily.co Configuration (for WebRTC audio transport)
DAILY_API_KEY=your_daily_api_key

# LLM Configuration
OPENAI_API_KEY=your_openai_api_key

# AWS CloudWatch Configuration (optional)
AWS_ACCESS_KEY_ID=your_aws_access_key
AWS_SECRET_ACCESS_KEY=your_aws_secret_key
AWS_REGION=us-east-1
CLOUDWATCH_LOG_GROUP=/cinema-chat

# Whisper STT Configuration
WHISPER_DEVICE=cuda  # or cpu
```

## Architecture

The frontend application follows this flow:

1. User speaks into phone connected to computer's audio input
2. Browser captures audio via Web Audio API
3. Frontend calls `/api/connect` or `/api/connect_local` which:
   - Creates a Daily.co room for audio communication
   - Launches a Cinema Chat bot instance (locally or on RunPod with GPU acceleration)
   - Returns connection credentials to the frontend
4. Frontend establishes connection with the bot through Daily.co
5. Real-time audio is processed through the Pipecat SDK with Daily Transport
6. Conversation flow:
   - User audio → Whisper STT → Text
   - Text → LLM → Semantic video description
   - LLM calls MCP tools to search and play video
   - Video plays on TV (secondary monitor)
7. UI components update based on conversation state and video selections

## RunPod Execution Details

The frontend integrates with RunPod to provide on-demand GPU-accelerated bot instances. This section explains how RunPod integration works in detail.

### RunPod Integration Architecture

1. **Connection Flow**:
   - When a user initiates a conversation, the frontend calls the `/api/connect` endpoint
   - This endpoint performs two key operations:
     1. Creating a Daily.co room for audio communication
     2. Spawning a new Cinema Chat bot instance on RunPod

2. **RunPod Pod Provisioning**:
   - The system uses the RunPod GraphQL API to create a new pod instance
   - The API call specifies resource requirements (GPU type, CPU, memory)
   - A pre-configured Docker image with the Cinema Chat bot is deployed
   - Environment variables for API keys, room URL, and tokens are passed to the container

3. **Failover Mechanism**:
   - The system attempts to provision pods with different GPU configurations in priority order
   - If a preferred GPU is unavailable, it falls back to alternative configurations
   - The prioritized order is:
     1. NVIDIA RTX 4000 Ada Generation with 8 vCPUs and 24GB memory
     2. NVIDIA RTX 4000 Ada Generation with 4 vCPUs and 24GB memory
     3. NVIDIA RTX 4000 Ada Generation with 4 vCPUs and 15GB memory
     4. NVIDIA GeForce RTX 4090 with various configurations
     5. Additional fallback options with other GPUs

4. **Configuration and Environment**:
   - API keys for OpenAI and other services are securely passed as environment variables
   - AWS CloudWatch configuration is provided for logging
   - The pod connects to the Daily room using the provided credentials

### RunPod Template Configuration

The system requires a RunPod template with the following specifications:

- **Docker Image**: The Cinema Chat Docker image
- **Environment Variables**:
  - `DAILY_ROOM_URL` - Set at runtime
  - `DAILY_TOKEN` - Set at runtime
  - `IDENTIFIER` - Set at runtime
  - Other API keys passed from frontend environment

- **Resource Requirements**:
  - GPU: NVIDIA CUDA compatible (RTX 4000/4090 recommended) for Whisper STT
  - Memory: 15-24GB minimum
  - CPU: 4-8 cores recommended

### Implementation in `connect_runpod.ts`

The `/api/connect_runpod.ts` file contains the core implementation:

```typescript
// RunPod GraphQL mutation to create pod
const createPodMutation = `
  mutation createPod($input: PodRuntimeInput!) {
    podFindAndDeployOnDemand(input: $input) {
      id
      name
      runtime {
        ports {
          ip
          isIpPublic
          privatePort
          publicPort
          type
        }
      }
      desiredStatus
    }
  }
`;

// Pod configuration options in priority order
const podConfigs: RunPodConfig[] = [
  {
    gpuTypeId: "NVIDIA RTX 4000 Ada Generation", // Preferred
    minVcpuCount: 8,
    minMemoryInGb: 24
  },
  // Additional fallback configurations...
];
```

Which is then used in the `launchRunPodInstance` and `attemptRunPodLaunch` functions to provision pods with proper environment variables.

## Project Structure

- `pages/` - Next.js pages and API routes
  - `index.tsx` - Main application page with Cinema Chat UI
  - `api/connect_runpod.ts` - Creates a Daily room and launches a Cinema Chat bot on RunPod
  - `api/connect_local.ts` - Local development version of connect endpoint
  - `api/start_pi_client.ts` - Starts Raspberry Pi Daily client for audio/video
  - `api/cleanup_pi.ts` - Cleans up Pi processes
- `components/` - React components
  - `ChatLog.tsx` - Displays conversation history and transcriptions
  - `LoadingSpinner.tsx` - Loading indicator
  - `AudioDeviceSelector.tsx` - Local audio device selection
  - `PiAudioDeviceSelector.tsx` - Raspberry Pi audio device selection
- `styles/` - CSS and styling
- `lib/` - Utility functions and API clients
- `types/` - TypeScript type definitions
- `public/` - Static assets

## Core Dependencies

- **Next.js** - React framework for server-rendered applications
- **Daily.co SDK** - Audio/video room capabilities
- **Pipecat SDK** - Voice interaction processing
  - `@pipecat-ai/client-js` - Core client library
  - `@pipecat-ai/client-react` - React components and hooks
  - `@pipecat-ai/daily-transport` - Integration with Daily.co
- **Styled Components** - CSS-in-JS styling solution

## Development Guide

### Running with Local Backend

To use a local backend instead of RunPod:

1. Start the backend server locally (see backend README):
   ```bash
   cd ../backend/src/cinema-bot
   python server.py
   ```
2. Start the MCP server:
   ```bash
   cd ../../../../mcp
   python mock_server.py  # or python server.py for real GoodCLIPS integration
   ```
3. Use `NEXT_PUBLIC_API_URL` to use the local endpoint: `http://localhost:3000/api/connect_local`

### Raspberry Pi Setup

For installation deployment with Raspberry Pi handling video playback:

1. Deploy necessary files to Pi:
   ```bash
   cd ../../../../mcp
   ./deploy_to_pi.sh
   ```
2. The Pi runs:
   - `video_playback_service_mpv.py` - MPV-based video playback
   - `pi_daily_client_rtvi.py` or `pi_daily_client_rtvi_v2.py` - Daily.co client for audio
   - Next.js frontend (for local monitoring)

### Adding New Features

- **New UI Components**: Add to the `components` directory following the existing patterns
- **API Extensions**: Extend functionality in the `pages/api` directory
- **Video Search Customization**: Modify MCP server integration in backend

### Troubleshooting

- **Daily.co Connection Issues**: Verify your Daily API key and check browser permissions for microphone access
- **RunPod Deployment Failures**: Check RunPod availability and template configuration
- **Video Not Playing**: Check MCP server connection and video playback service on Pi
- **Audio Issues**: Verify phone input device configuration and Pi audio settings
