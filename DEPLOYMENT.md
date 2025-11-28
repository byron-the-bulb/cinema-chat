# Cinema Chat Deployment Guide

## Architecture Overview

The Cinema Chat system consists of three main components:

1. **Backend Server** (Python/FastAPI) - Runs on development machine (172.28.172.5:8765)
   - LLM conversation management
   - Daily.co room creation
   - MCP server integration
   - Conversation status tracking

2. **Dashboard** (Next.js) - Runs on Raspberry Pi (192.168.1.201:3000)
   - User interface for starting/stopping sessions
   - Real-time conversation monitoring
   - API client to backend server

3. **Pi Client** (Python/Daily.co) - Spawned per session on Raspberry Pi
   - RTVI-compatible Daily.co participant
   - Video playback via MCP tools
   - One process per Daily.co room

## Key Design Decisions

### Direct Spawn Architecture (v2)

After refactoring, the system uses a **direct spawn** pattern:

- ✅ Each new room spawns a dedicated Python client process
- ✅ No wrapper scripts or config file polling
- ✅ Environment variables passed directly to client
- ✅ Multiple concurrent sessions supported
- ✅ Simple, stateless design

**Old Architecture (v1 - deprecated)**:
- ❌ Wrapper script polling for config file
- ❌ Single client at a time
- ❌ File-based synchronization
- ❌ Complex lifecycle management

### Process Lifecycle

```
User clicks "Start Experience" in dashboard
    ↓
Dashboard → POST /api/connect (backend server)
    ↓
Backend creates Daily.co room, returns room_url + token
    ↓
Dashboard → POST /api/start_pi_client (Next.js API route)
    ↓
API route spawns Python client with env vars:
  - DAILY_ROOM_URL
  - DAILY_TOKEN
  - BACKEND_URL
  - VIDEO_SERVICE_URL
    ↓
Python client joins Daily.co room
    ↓
Backend detects participant_joined → initializes bot
    ↓
LLM sends greeting → Conversation begins
```

## Prerequisites

### Development Machine (172.28.172.5)
- Python 3.11+
- Docker + Docker Compose
- NVIDIA GPU (for Whisper STT)
- OpenAI/Anthropic API key
- Daily.co API key

### Raspberry Pi (192.168.1.201)
- Node.js 18+ and npm
- Python 3.11+ with venv
- Video output configured (HDMI/composite to TV)
- Network access to backend server

## Installation

### 1. Backend Server Setup

```bash
# On development machine (172.28.172.5)
cd /home/va55/code/cinema-chat/cinema-bot-app/backend

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys:
# - OPENAI_API_KEY
# - DAILY_API_KEY
# - DAILY_API_URL
```

### 2. Pi Dashboard Setup

```bash
# On Raspberry Pi (192.168.1.201)
cd /home/twistedtv/frontend-next

# Install dependencies
npm install

# Build for production
npm run build

# Or run in development mode
npm run dev
```

### 3. Pi Client Setup

```bash
# On Raspberry Pi (192.168.1.201)
cd /home/twistedtv

# Create virtual environment
python3 -m venv venv_daily
source venv_daily/bin/activate

# Install dependencies
pip install -r requirements_pi.txt

# Place the pi_daily_client_rtvi.py script in /home/twistedtv/
```

## Configuration

### Backend Server (.env)

```bash
# Daily.co Configuration
DAILY_API_KEY=your_daily_api_key
DAILY_API_URL=https://api.daily.co/v1

# LLM Configuration
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4o

# Whisper Configuration
WHISPER_DEVICE=cuda  # or 'cpu'
WHISPER_MODEL=base.en

# Server Configuration
BACKEND_SERVER_URL=http://172.28.172.5:8765
HOST=0.0.0.0
PORT=8765
```

### Dashboard (environment variables)

Set these in [.env.local](cinema-bot-app/frontend-next/.env.local):

```bash
NEXT_PUBLIC_API_URL=http://172.28.172.5:8765/api
```

### Pi Client Paths

Update these constants in [pages/api/start_pi_client.ts](cinema-bot-app/frontend-next/pages/api/start_pi_client.ts):

```typescript
const VENV_PYTHON = '/home/twistedtv/venv_daily/bin/python3';
const PYTHON_CLIENT = '/home/twistedtv/pi_daily_client_rtvi.py';
const LOG_FILE = '/tmp/pi_client.log';
```

## Running the System

### Start Backend Server

```bash
# On development machine
cd /home/va55/code/cinema-chat/cinema-bot-app/backend
source venv/bin/activate
cd src/cinema-bot
python3 server.py
```

Expected output:
```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8765
```

### Start Dashboard

```bash
# On Raspberry Pi
cd /home/twistedtv/frontend-next
npm run dev  # or 'npm start' for production
```

Expected output:
```
ready - started server on 0.0.0.0:3000, url: http://localhost:3000
```

### Access Dashboard

Open browser to: **http://192.168.1.201:3000**

## Testing the System

### 1. Start a Session

1. Navigate to http://192.168.1.201:3000
2. Enter backend server URL: `http://172.28.172.5:8765/api`
3. Click "Start Experience"

Expected dashboard messages:
```
Session started successfully
Room: https://cinema-chat.daily.co/xxxxx
Pi client started (PID: 12345)
```

### 2. Monitor Backend Logs

Backend should show:
```
Room created: <room_url>
Creating new bot instance for identifier: <identifier>
Participant joined: <participant_id>
Bot initialization complete
Greeting phase - waiting for bot greeting
```

### 3. Monitor Pi Client Logs

```bash
# On Raspberry Pi
tail -f /tmp/pi_client.log
```

Expected output:
```
Starting Pi Daily.co RTVI client...
Room URL: https://cinema-chat.daily.co/xxxxx
Backend URL: http://172.28.172.5:8765
Video Service URL: http://localhost:5000
Joining Daily.co room...
Successfully joined room
RTVI initialization complete
```

### 4. Verify Conversation Status

Check the backend API:
```bash
curl http://172.28.172.5:8765/conversation-status/<identifier> | jq
```

Expected response:
```json
{
  "identifier": "xxxxx",
  "status": "active",
  "context": {
    "messages": [
      {
        "role": "assistant",
        "content": "Welcome to Cinema Chat! ..."
      }
    ],
    "display_messages": []
  }
}
```

## Troubleshooting

### Issue: "Failed to start Pi client"

**Symptoms**: Dashboard shows error message, no PID returned

**Possible Causes**:
1. Python client script not found at `/home/twistedtv/pi_daily_client_rtvi.py`
2. Virtual environment not found at `/home/twistedtv/venv_daily/`
3. Missing dependencies in venv

**Fix**:
```bash
# Verify paths exist
ls -la /home/twistedtv/pi_daily_client_rtvi.py
ls -la /home/twistedtv/venv_daily/bin/python3

# Check log file for errors
tail -50 /tmp/pi_client.log
```

### Issue: "Repeated greeting messages, no LLM response"

**Symptoms**: Dashboard shows `{'node': 'greeting'}` repeatedly

**Possible Causes**:
1. Pi client not joining the Daily.co room
2. Backend not detecting participant_joined event
3. RTVI initialization failing

**Fix**:
```bash
# Check Pi client log
tail -50 /tmp/pi_client.log

# Verify client joined successfully
# Look for: "Successfully joined room"

# Check backend logs for participant_joined event
# Should see: "Participant joined: <id>"
```

### Issue: "Port 3000 already in use"

**Symptoms**: Next.js fails to start or runs on port 3001

**Fix**:
```bash
# Kill existing Next.js processes
ps aux | grep 'next\|node'
kill <PIDs>

# Restart on port 3000
cd /home/twistedtv/frontend-next
npm run dev
```

### Issue: "Connection timeout to backend"

**Symptoms**: Dashboard cannot reach backend server

**Fix**:
```bash
# Verify backend is running
curl http://172.28.172.5:8765/health

# Check firewall rules on development machine
sudo ufw status

# Verify network connectivity from Pi
ping 172.28.172.5
```

## Production Deployment

### systemd Services

For automatic startup on boot, create systemd service files:

#### Backend Server Service

Create `/etc/systemd/system/cinema-backend.service`:

```ini
[Unit]
Description=Cinema Chat Backend Server
After=network.target

[Service]
Type=simple
User=va55
WorkingDirectory=/home/va55/code/cinema-chat/cinema-bot-app/backend
ExecStart=/home/va55/code/cinema-chat/cinema-bot-app/backend/venv/bin/python3 src/cinema-bot/server.py
Restart=always
RestartSec=10
Environment="PATH=/home/va55/code/cinema-chat/cinema-bot-app/backend/venv/bin:/usr/local/bin:/usr/bin:/bin"

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable cinema-backend
sudo systemctl start cinema-backend
sudo systemctl status cinema-backend
```

#### Pi Dashboard Service

Create `/etc/systemd/system/cinema-dashboard.service` on the Pi:

```ini
[Unit]
Description=Cinema Chat Dashboard
After=network.target

[Service]
Type=simple
User=twistedtv
WorkingDirectory=/home/twistedtv/frontend-next
ExecStart=/usr/bin/npm start
Restart=always
RestartSec=10
Environment="NODE_ENV=production"
Environment="PORT=3000"

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable cinema-dashboard
sudo systemctl start cinema-dashboard
sudo systemctl status cinema-dashboard
```

## Architecture Diagrams

### System Flow

```
┌─────────────────────────────────────────────────────────┐
│  Raspberry Pi (192.168.1.201)                           │
│                                                          │
│  ┌────────────────────┐                                 │
│  │  Next.js Dashboard │ (port 3000)                     │
│  │  User Interface    │                                 │
│  └─────────┬──────────┘                                 │
│            │                                             │
│            │ 1. POST /api/connect                        │
│            ├───────────────────────────────────┐         │
│            │                                   │         │
│            │ 2. POST /api/start_pi_client      │         │
│            │    (spawns process)               │         │
│            ↓                                   │         │
│  ┌────────────────────┐                       │         │
│  │  Pi Daily Client   │                       │         │
│  │  (Python process)  │                       │         │
│  └─────────┬──────────┘                       │         │
│            │                                   │         │
│            │ 3. Join Daily.co room             │         │
│            ↓                                   ↓         │
└────────────┼───────────────────────────────────┼─────────┘
             │                                   │
             │                                   │
    ┌────────┼───────────────────────────────────┼─────┐
    │ Daily.co WebRTC Room                       │     │
    │                                            │     │
    │  ┌─────────────┐      ┌────────────────┐  │     │
    │  │  Pi Client  │◄────►│  Backend Bot   │  │     │
    │  │ Participant │      │   Participant  │  │     │
    │  └─────────────┘      └────────────────┘  │     │
    │                                            │     │
    └────────────────────────────────────────────┘     │
                                                       │
             ┌─────────────────────────────────────────┘
             │ 4. participant_joined event
             ↓
┌────────────────────────────────────────────────────────┐
│  Development Machine (172.28.172.5)                    │
│                                                         │
│  ┌──────────────────────────┐                          │
│  │  Cinema Bot Backend      │ (port 8765)              │
│  │  - FastAPI Server        │                          │
│  │  - LLM Integration       │                          │
│  │  - Whisper STT           │                          │
│  │  - MCP Server            │                          │
│  │  - Status Tracking       │                          │
│  └──────────────────────────┘                          │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Data Flow for One Session

```
1. User clicks "Start Experience"
   Dashboard → Backend: POST /api/connect

2. Backend creates Daily.co room
   Backend → Daily.co API: Create room
   Backend ← Daily.co API: room_url, token

3. Dashboard spawns Pi client
   Dashboard → API Route: POST /api/start_pi_client
   API Route: spawn(python3, [pi_daily_client_rtvi.py], {env: {...}})
   API Route → Dashboard: {pid: 12345}

4. Pi client joins room
   Pi Client → Daily.co: Join room with token
   Pi Client: Initialize RTVI

5. Backend detects participant
   Backend ← Daily.co: participant_joined event
   Backend: Initialize bot for this session

6. Bot sends greeting
   Backend → LLM: Generate greeting
   Backend → MCP: search_video_clips("greeting")
   Backend → Daily.co: Send RTVI message

7. Conversation loop
   User speaks → Pi mic → Daily.co → Backend
   Backend → Whisper: Transcribe
   Backend → LLM: Process + generate response
   Backend → MCP: Select video clip
   Backend → Daily.co: Play video via RTVI
   Daily.co → Pi: Video playback
   Pi → TV: Display video

8. Status updates
   Backend → Status API: POST /update-status
   Dashboard → Status API: GET /conversation-status/<id>
   Dashboard: Display messages in UI
```

## API Reference

### Backend Endpoints

#### POST /api/connect
Create a new Daily.co room and bot instance.

**Request**:
```json
{
  "config": [{
    "service": "tts",
    "options": [{
      "name": "provider",
      "value": "cartesia"
    }]
  }]
}
```

**Response**:
```json
{
  "room_url": "https://cinema-chat.daily.co/xxxxx",
  "token": "eyJhbGc...",
  "identifier": "uuid-here"
}
```

#### GET /conversation-status/{identifier}
Get conversation status for a session.

**Response**:
```json
{
  "identifier": "uuid-here",
  "status": "active",
  "context": {
    "messages": [...],
    "display_messages": [...]
  }
}
```

#### POST /update-status
Update conversation status (called by Pi client).

**Request**:
```json
{
  "identifier": "uuid-here",
  "status": "active",
  "context": {
    "messages": [...],
    "display_messages": [...]
  }
}
```

### Dashboard API Routes

#### POST /api/start_pi_client
Spawn a new Pi client process for a Daily.co room.

**Request**:
```json
{
  "roomUrl": "https://cinema-chat.daily.co/xxxxx",
  "token": "eyJhbGc...",
  "backendUrl": "http://172.28.172.5:8765"
}
```

**Response**:
```json
{
  "success": true,
  "message": "Pi client started successfully",
  "pid": 12345,
  "roomUrl": "https://cinema-chat.daily.co/xxxxx"
}
```

## File Locations

### Development Machine (172.28.172.5)
```
/home/va55/code/cinema-chat/
├── cinema-bot-app/
│   └── backend/
│       ├── venv/                   # Python virtual environment
│       ├── requirements.txt        # Python dependencies
│       └── src/cinema-bot/
│           ├── server.py           # FastAPI server
│           ├── cinema_bot.py       # Bot logic
│           ├── cinema_script.py    # Conversation flow
│           ├── mcp_client.py       # MCP integration
│           └── status_utils.py     # Status tracking
├── mcp/
│   ├── mock_server.py              # MCP mock server
│   ├── video_playback_service_mpv.py
│   └── requirements_pi.txt
└── .env                            # Environment configuration
```

### Raspberry Pi (192.168.1.201)
```
/home/twistedtv/
├── frontend-next/
│   ├── node_modules/               # npm dependencies
│   ├── pages/
│   │   ├── index.tsx               # Main dashboard UI
│   │   └── api/
│   │       └── start_pi_client.ts  # API route for spawning clients
│   ├── components/                 # React components
│   ├── .env.local                  # Next.js environment
│   └── package.json
├── venv_daily/                     # Python virtual environment
│   └── bin/python3
├── pi_daily_client_rtvi.py         # Daily.co client script
└── requirements_pi.txt             # Python dependencies
```

### Log Files
```
/tmp/pi_client.log                  # Pi client stdout/stderr
/tmp/nextjs.log                     # Next.js dashboard logs (if using nohup)
```

## Network Ports

- **3000**: Next.js Dashboard (Pi)
- **5000**: Video Service (Pi) - for MCP video playback
- **8765**: Backend Server (Development machine)
- **443**: Daily.co WebRTC (external)

## Security Considerations

1. **API Keys**: Never commit `.env` files. Use `.env.example` as template.
2. **Network**: Ensure firewall allows traffic between Pi and development machine.
3. **Daily.co Tokens**: Tokens are scoped per room and expire after session.
4. **Process Management**: Each room gets isolated Python process.
5. **Log Files**: Contain sensitive info, rotate regularly.

## Performance Tuning

### Backend Server
- Use GPU for Whisper STT (`WHISPER_DEVICE=cuda`)
- Adjust `WHISPER_MODEL` based on accuracy vs. speed needs
- Monitor memory usage with multiple concurrent sessions

### Pi Client
- Ensure video output device is configured correctly
- Check network bandwidth for WebRTC streams
- Monitor CPU usage during video playback

### Dashboard
- Use production build (`npm run build && npm start`) for better performance
- Enable polling optimization if needed (currently polls every 2 seconds)

## Maintenance

### Log Rotation
```bash
# Rotate Pi client logs
sudo logrotate -f /etc/logrotate.d/cinema-chat
```

### Database Cleanup (if applicable)
```bash
# Clear old session data
curl -X DELETE http://172.28.172.5:8765/api/cleanup-old-sessions
```

### Process Monitoring
```bash
# Check running processes
ps aux | grep 'cinema\|pi_daily_client'

# Monitor system resources
htop
```

## Known Issues

1. **Port Conflicts**: Next.js may fall back to port 3001 if 3000 is occupied. Always kill old processes before starting.

2. **SSH Disconnects**: Using `pkill` can kill SSH sessions. Use specific PIDs with `kill` instead.

3. **Multiple Instances**: Old Pi client processes may persist if not cleaned up properly. Check with `ps aux | grep pi_daily_client`.

## Future Enhancements

1. **Graceful Shutdown**: Implement proper cleanup when rooms are closed
2. **Health Checks**: Add `/health` endpoints for monitoring
3. **Session Management**: Track and clean up old sessions
4. **Video Service Integration**: Connect real MCP video playback server
5. **Error Recovery**: Auto-restart failed clients
6. **Metrics**: Add Prometheus/Grafana monitoring
7. **Multi-Pi Support**: Scale to multiple Pi devices

## Support

For issues and questions:
- Check logs: `/tmp/pi_client.log`, backend console output
- Review conversation status: `GET /conversation-status/{identifier}`
- Verify network connectivity between components
- Ensure all services are running (backend, dashboard, video service)

## Version History

- **v2.0** (2025-11-24): Direct spawn architecture, removed wrapper scripts
- **v1.0** (2025-11-20): Initial release with wrapper script polling
