# Sphinx Voice Bot Frontend (Next.js)

This is a Next.js 15.3 implementation of the Sphinx Voice Bot guide interface that provides real-time voice conversations with emotion analysis and feedback.

## Features

- Built with Next.js 15.3 and React 19
- Integrated with Pipecat SDK using Daily Transport for audio streaming
- Real-time emotion analysis through Hume AI integration
- API endpoints for connecting to RunPod GPU instances
- Multiple TTS providers (Cartesia, ElevenLabs, OpenAI)
- Voice selection and configuration with emotion customization
- Chat history and conversation visualization

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

Open [http://localhost:3000](http://localhost:3000) with your browser to interact with the Sphinx Voice Bot.

## Environment Variables

Create a `.env.local` file with the following variables:

```
# API URLs
NEXT_PUBLIC_API_URL=http://localhost:3000/api
NEXT_PUBLIC_WS_URL=ws://localhost:3000

# RunPod Configuration
NEXT_PUBLIC_RUNPOD_TEMPLATE_ID=your_runpod_template_id

# TTS Configuration
DEFAULT_VOICE_ID=ec58877e-44ae-4581-9078-a04225d42bd4
DEFAULT_TTS_MODEL=sonic-turbo-2025-03-07

# External API keys for TTS
NEXT_PUBLIC_CARTESIA_API_KEY=your_cartesia_api_key
CARTESIA_API_KEY=your_cartesia_api_key
ELEVENLABS_API_KEY=your_elevenlabs_api_key
OPENAI_API_KEY=your_openai_api_key

# For API routes (server-side)
RUNPOD_API_KEY=your_runpod_api_key
DAILY_API_KEY=your_daily_api_key
HUME_API_KEY=your_hume_api_key

# AWS CloudWatch Configuration (optional)
AWS_ACCESS_KEY_ID=your_aws_access_key
AWS_SECRET_ACCESS_KEY=your_aws_secret_key
AWS_REGION=us-east-1
CLOUDWATCH_LOG_GROUP=/sphinx-voice-bot

# Whisper STT Configuration
SPHINX_WHISPER_DEVICE=cuda
```

## Architecture

The frontend application follows this flow:

1. User accesses the web interface and initiates a conversation
2. Frontend calls `/api/connect` which:
   - Creates a Daily.co room for audio communication
   - Launches a Sphinx bot instance on RunPod with GPU acceleration
   - Returns connection credentials to the frontend
3. Frontend establishes connection with the bot through Daily.co
4. Real-time audio is processed through the Pipecat SDK with Daily Transport
5. Conversation is managed by the backend bot with emotion analysis
6. UI components update based on conversation state and analysis results

## RunPod Execution Details

The frontend integrates with RunPod to provide on-demand GPU-accelerated bot instances. This section explains how RunPod integration works in detail.

### RunPod Integration Architecture

1. **Connection Flow**:
   - When a user initiates a conversation, the frontend calls the `/api/connect` endpoint
   - This endpoint performs two key operations:
     1. Creating a Daily.co room for audio communication
     2. Spawning a new Sphinx bot instance on RunPod

2. **RunPod Pod Provisioning**:
   - The system uses the RunPod GraphQL API to create a new pod instance
   - The API call specifies resource requirements (GPU type, CPU, memory)
   - A pre-configured Docker image with the Sphinx bot is deployed
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
   - The TTS configuration (voice, model, speed, emotion) from the frontend UI is passed to the pod
   - API keys for OpenAI, Hume, Cartesia/ElevenLabs are securely passed as environment variables
   - AWS CloudWatch configuration is provided for logging
   - The pod connects to the Daily room using the provided credentials

### RunPod Template Configuration

The system requires a RunPod template with the following specifications:

- **Docker Image**: The Sphinx Voice Bot Docker image
- **Environment Variables**:
  - `DAILY_ROOM_URL` - Set at runtime
  - `DAILY_TOKEN` - Set at runtime
  - `IDENTIFIER` - Set at runtime
  - `TTS_CONFIG` - Set at runtime based on user preferences
  - Other API keys passed from frontend environment

- **Resource Requirements**:
  - GPU: NVIDIA CUDA compatible (RTX 4000/4090 recommended)
  - Memory: 15-24GB minimum
  - CPU: 4-8 cores recommended

### Implementation in `connect.ts`

The `/api/connect.ts` file contains the core implementation:

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
  - `index.tsx` - Main application page with voice bot UI
  - `api/connect.ts` - Creates a Daily room and launches a Sphinx bot on RunPod
  - `api/connect_local.ts` - Local development version of connect endpoint
- `components/` - React components
  - `ChatLog.tsx` - Displays conversation history
  - `EmotionSelector.tsx` - UI for selecting emotions
  - `SpeedSelector.tsx` - Controls for TTS speed
  - `VoiceSelector.tsx` - Voice selection interface
  - `VoiceSettingsPanel.tsx` - TTS configuration panel
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
- **Cartesia** - Text-to-speech service
- **Styled Components** - CSS-in-JS styling solution

## Development Guide

### Running with Local Backend

To use a local backend instead of RunPod:

1. Start the backend server locally (see backend README)
2. Set `NEXT_PUBLIC_API_URL` to use the local endpoint: `http://localhost:3000/api/connect_local`

### Adding New Features

- **New UI Components**: Add to the `components` directory following the existing patterns
- **API Extensions**: Extend functionality in the `pages/api` directory
- **TTS Customization**: Modify voice settings in the VoiceSelector and related components

### Troubleshooting

- **Daily.co Connection Issues**: Verify your Daily API key and check browser permissions for microphone access
- **RunPod Deployment Failures**: Check RunPod availability and template configuration
- **TTS Not Working**: Verify API keys for Cartesia, ElevenLabs, or OpenAI
