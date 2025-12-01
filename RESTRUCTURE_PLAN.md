# TwistedTV Restructuring Plan

**Date:** 2025-11-30
**Purpose:** Prepare clean PR for Massimo's cinema-chat repository

## Background

The cinema-chat repository is owned by Massimo and contains the GoodCLIPS API (Go backend). We've added TwistedTV components in `cinema-bot-app/` and `mcp/` directories, which creates a messy structure for the PR.

## Goal

Reorganize all TwistedTV code into three clean, isolated directories:
1. `twistedtv-server/` - All server-side code (runs on development/cloud machine)
2. `twistedtv-pi-client/` - All Raspberry Pi code (runs on Pi at installation)
3. `twistedtv-video-server/` - Video file storage and streaming server (runs on development machine)

This makes it easy for Massimo to:
- Review the PR without confusion
- Understand what runs where
- Merge without affecting his existing code structure

---

## Current Structure (Before)

```
cinema-chat/
├── cmd/                              # Massimo's Go API
├── internal/                         # Massimo's Go internals
├── migrations/                       # Massimo's DB migrations
├── docker-compose.yml               # Massimo's Docker config
├── cinema-bot-app/                  # OUR CODE (to be moved)
│   ├── backend/
│   │   ├── Dockerfile
│   │   ├── build.sh
│   │   ├── requirements.txt
│   │   └── src/cinema-bot/         # Backend bot logic
│   │       ├── server.py
│   │       ├── cinema_bot.py
│   │       ├── cinema_script.py
│   │       ├── mcp_client.py
│   │       ├── mcp_video_tools.py
│   │       ├── custom_flow_manager.py
│   │       ├── status_utils.py
│   │       ├── cloudwatch_logger.py
│   │       └── cleanup_daily_rooms.py
│   ├── frontend-next/              # Next.js (runs on Pi)
│   │   ├── pages/
│   │   ├── components/
│   │   ├── styles/
│   │   └── package.json
│   └── scripts/
│       └── generate-favicon.js
├── mcp/                             # OUR CODE (to be moved)
│   ├── server.py                    # MCP server (server-side)
│   ├── mock_server.py               # Mock MCP (server-side)
│   ├── config.py
│   ├── goodclips_client.py
│   ├── video_player.py
│   ├── pi_daily_client_rtvi.py     # Pi client (Pi-side)
│   ├── pi_daily_client_rtvi_v2.py  # Pi client V2 (Pi-side)
│   ├── video_playback_service_mpv.py  # Video playback (Pi-side)
│   ├── video_playback_service_vlc.py  # Alternative playback
│   ├── test_pi_audio.py            # Pi tests
│   ├── deploy_to_pi.sh
│   └── requirements.txt
└── data/                            # OUR CODE (to be moved)
    └── videos/                      # Video file storage
        ├── streaming_server.py      # Flask video streaming server
        ├── threaded_server.py       # Alternative server
        ├── hemo_the_magnificent.mp4.mkv  # Video files
        └── video_2_keyframes/       # Processed video data
```

---

## New Structure (After)

```
cinema-chat/
├── cmd/                              # Massimo's (unchanged)
├── internal/                         # Massimo's (unchanged)
├── migrations/                       # Massimo's (unchanged)
├── docker-compose.yml               # Massimo's (unchanged)
│
├── twistedtv-server/                # NEW: All server-side code
│   ├── cinema_bot/                  # Backend bot orchestration
│   │   ├── __init__.py
│   │   ├── server.py               # FastAPI server entry point
│   │   ├── cinema_bot.py           # Main bot logic
│   │   ├── cinema_script.py        # Conversation flows
│   │   ├── mcp_client.py           # MCP client integration
│   │   ├── mcp_video_tools.py      # MCP video tools
│   │   ├── custom_flow_manager.py  # Flow state management
│   │   ├── status_utils.py         # Status updates
│   │   ├── cloudwatch_logger.py    # AWS CloudWatch
│   │   └── cleanup_daily_rooms.py  # Daily.co cleanup
│   │
│   ├── mcp_server/                  # MCP server for video search
│   │   ├── __init__.py
│   │   ├── server.py               # Real MCP server (GoodCLIPS)
│   │   ├── mock_server.py          # Mock server (keyword search)
│   │   ├── config.py               # Configuration
│   │   ├── goodclips_client.py     # GoodCLIPS API client
│   │   └── video_player.py         # Video player utilities
│   │
│   ├── requirements.txt             # Python dependencies
│   ├── Dockerfile                   # Docker image for server
│   ├── build.sh                     # Build script
│   ├── .env.example                # Environment variables template
│   └── README.md                    # Server setup & usage
│
├── twistedtv-pi-client/             # NEW: All Raspberry Pi code
│   ├── pi_daily_client/             # Daily.co client for Pi
│   │   ├── __init__.py
│   │   ├── pi_daily_client_rtvi.py     # RTVI client V1
│   │   ├── pi_daily_client_rtvi_v2.py  # RTVI client V2 (current)
│   │   └── test_audio.py               # Audio testing utilities
│   │
│   ├── video_playback/              # Video playback service
│   │   ├── __init__.py
│   │   ├── video_playback_service_mpv.py  # MPV playback (current)
│   │   ├── video_playback_service_vlc.py  # VLC playback (alternative)
│   │   └── video_player.py                # Shared utilities
│   │
│   ├── frontend/                    # Next.js UI (runs on Pi)
│   │   ├── pages/
│   │   │   ├── index.tsx            # Main page
│   │   │   ├── _app.tsx
│   │   │   ├── _document.tsx
│   │   │   └── api/                 # API routes
│   │   │       ├── connect_local.ts
│   │   │       ├── connect_runpod.ts
│   │   │       ├── start_pi_client.ts
│   │   │       ├── cleanup_pi.ts
│   │   │       └── trigger_video.ts
│   │   ├── components/
│   │   │   ├── ChatLog.tsx
│   │   │   ├── LoadingSpinner.tsx
│   │   │   ├── AudioDeviceSelector.tsx
│   │   │   └── PiAudioDeviceSelector.tsx
│   │   ├── styles/
│   │   ├── public/
│   │   │   └── cinema-chat.svg
│   │   ├── package.json
│   │   ├── next.config.js
│   │   └── tsconfig.json
│   │
│   ├── scripts/
│   │   ├── generate-favicon.js      # Favicon generation
│   │   └── deploy_to_pi.sh          # Deployment script
│   │
│   ├── requirements.txt             # Python dependencies for Pi
│   ├── .env.example                # Environment variables template
│   └── README.md                    # Pi setup & usage
│
└── twistedtv-video-server/          # NEW: Video storage and streaming
    ├── videos/                      # Video file storage
    │   ├── hemo_the_magnificent.mp4.mkv
    │   └── video_2_keyframes/       # Processed video data
    ├── streaming_server.py          # Flask video streaming server (current)
    ├── threaded_server.py           # Alternative streaming implementation
    ├── requirements.txt             # Flask dependencies
    ├── .gitignore                   # Ignore large video files
    └── README.md                    # Video server setup & usage
```

---

## Migration Mapping

### Server-Side Files → `twistedtv-server/`

| Current Location | New Location |
|-----------------|--------------|
| `cinema-bot-app/backend/src/cinema-bot/*.py` | `twistedtv-server/cinema_bot/*.py` |
| `cinema-bot-app/backend/requirements.txt` | `twistedtv-server/requirements.txt` |
| `cinema-bot-app/backend/Dockerfile` | `twistedtv-server/Dockerfile` |
| `cinema-bot-app/backend/build.sh` | `twistedtv-server/build.sh` |
| `mcp/server.py` | `twistedtv-server/mcp_server/server.py` |
| `mcp/mock_server.py` | `twistedtv-server/mcp_server/mock_server.py` |
| `mcp/config.py` | `twistedtv-server/mcp_server/config.py` |
| `mcp/goodclips_client.py` | `twistedtv-server/mcp_server/goodclips_client.py` |
| `mcp/video_player.py` | `twistedtv-server/mcp_server/video_player.py` (shared copy) |

### Video Server Files → `twistedtv-video-server/`

| Current Location | New Location |
|-----------------|--------------|
| `data/videos/streaming_server.py` | `twistedtv-video-server/streaming_server.py` |
| `data/videos/threaded_server.py` | `twistedtv-video-server/threaded_server.py` |
| `data/videos/*.mp4`, `data/videos/*.mkv` | `twistedtv-video-server/videos/*.mp4`, etc. |
| `data/videos/video_*_keyframes/` | `twistedtv-video-server/videos/video_*_keyframes/` |

### Pi-Side Files → `twistedtv-pi-client/`

| Current Location | New Location |
|-----------------|--------------|
| `cinema-bot-app/frontend-next/*` | `twistedtv-pi-client/frontend/*` |
| `cinema-bot-app/scripts/*` | `twistedtv-pi-client/scripts/*` |
| `mcp/pi_daily_client_rtvi.py` | `twistedtv-pi-client/pi_daily_client/pi_daily_client_rtvi.py` |
| `mcp/pi_daily_client_rtvi_v2.py` | `twistedtv-pi-client/pi_daily_client/pi_daily_client_rtvi_v2.py` |
| `mcp/video_playback_service_mpv.py` | `twistedtv-pi-client/video_playback/video_playback_service_mpv.py` |
| `mcp/video_playback_service_vlc.py` | `twistedtv-pi-client/video_playback/video_playback_service_vlc.py` |
| `mcp/video_player.py` | `twistedtv-pi-client/video_playback/video_player.py` (shared copy) |
| `mcp/test_pi_audio.py` | `twistedtv-pi-client/pi_daily_client/test_audio.py` |
| `mcp/deploy_to_pi.sh` | `twistedtv-pi-client/scripts/deploy_to_pi.sh` |
| `mcp/requirements.txt` | `twistedtv-pi-client/requirements.txt` |

### Files to Review/Archive

These files may be old/test versions - review before moving:
- `mcp/pi_daily_client.py` (old version?)
- `mcp/pi_daily_client_v2.py` (old version?)
- `mcp/video_playback_service.py` (old version?)
- `mcp/test_audio_config.py`
- `mcp/test_audio_transcribe.py`
- `mcp/generate_static.py`

---

## Import Path Changes Required

### Python Import Updates

**Server-side (`twistedtv-server/`):**

Old:
```python
from cinema-bot.server import *
from cinema-bot.mcp_client import MCPClient
```

New:
```python
from cinema_bot.server import *
from cinema_bot.mcp_client import MCPClient
```

**Pi-side (`twistedtv-pi-client/`):**

Old:
```python
# No imports between files currently
```

New:
```python
from pi_daily_client.pi_daily_client_rtvi_v2 import *
from video_playback.video_playback_service_mpv import *
```

### TypeScript/API Path Updates

**Frontend API routes need to update Pi script paths:**

Old (in `start_pi_client.ts`):
```typescript
const PI_SCRIPT_PATH = '/home/twistedtv/pi_daily_client_rtvi_v2.py';
const VIDEO_SCRIPT_PATH = '/home/twistedtv/video_playback_service_mpv.py';
```

New:
```typescript
const PI_SCRIPT_PATH = '/home/twistedtv/twistedtv-pi-client/pi_daily_client/pi_daily_client_rtvi_v2.py';
const VIDEO_SCRIPT_PATH = '/home/twistedtv/twistedtv-pi-client/video_playback/video_playback_service_mpv.py';
```

### Deployment Script Updates

**`deploy_to_pi.sh` needs to sync from new structure:**

Old:
```bash
scp mcp/video_playback_service_mpv.py twistedtv@192.168.1.201:/home/twistedtv/
scp mcp/pi_daily_client_rtvi_v2.py twistedtv@192.168.1.201:/home/twistedtv/
```

New:
```bash
rsync -av twistedtv-pi-client/ twistedtv@192.168.1.201:~/twistedtv-pi-client/
```

---

## Step-by-Step Migration Process

### Phase 1: Create New Structure
1. Create `twistedtv-server/` directory structure
2. Create `twistedtv-pi-client/` directory structure
3. Create `__init__.py` files for Python packages

### Phase 2: Copy Files
4. Copy backend Python files to `twistedtv-server/cinema_bot/`
5. Copy MCP server files to `twistedtv-server/mcp_server/`
6. Copy Pi Daily client to `twistedtv-pi-client/pi_daily_client/`
7. Copy video playback to `twistedtv-pi-client/video_playback/`
8. Copy frontend to `twistedtv-pi-client/frontend/`
9. Copy scripts appropriately

### Phase 3: Update Code
10. Update Python imports in server code
11. Update Python imports in Pi code
12. Update TypeScript paths in API routes
13. Update deployment scripts
14. Update Docker configuration
15. Update all documentation references

### Phase 4: Clean & Document
16. Remove all Sphinx/Hume/Turning Point references
17. Create comprehensive README.md for server
18. Create comprehensive README.md for Pi client
19. Update root CLAUDE.md to reflect new structure
20. Create PR preparation documentation

### Phase 5: Test & Verify
21. Test server startup with new structure
22. Test MCP server with new imports
23. Test frontend with updated paths
24. Test deployment script
25. Verify all old references removed

### Phase 6: Finalize
26. Remove old `cinema-bot-app/` directory
27. Remove old `mcp/` directory
28. Final commit
29. Create PR summary for Massimo

---

## Benefits of This Structure

### For Massimo (Reviewer)
- ✅ Clear separation: Two directories, easy to review
- ✅ No interference with his existing code
- ✅ Obvious what runs where (server vs Pi)
- ✅ Can merge without restructuring his repo

### For Development
- ✅ Logical organization by deployment target
- ✅ Clear dependencies (server vs Pi vs video server)
- ✅ Easier to maintain and debug
- ✅ Better separation of concerns

### For Deployment
- ✅ Easy to deploy server components separately
- ✅ Easy to sync only Pi components to Pi
- ✅ Video server can run independently
- ✅ Clear environment variable separation
- ✅ Simplified Docker setup

---

## Documentation to Create

### `twistedtv-server/README.md`
- What this is (backend bot + MCP server)
- How to set up environment
- How to run locally
- How to build Docker image
- How to deploy to cloud/RunPod
- Environment variables explained
- Integration with GoodCLIPS API

### `twistedtv-pi-client/README.md`
- What this is (Pi components + frontend)
- How to set up Pi
- How to deploy to Pi
- How to run frontend locally
- How to start Pi services
- Environment variables explained
- Troubleshooting audio/video issues

### `twistedtv-video-server/README.md`
- What this is (video storage + streaming server)
- How to set up video server
- How to add new video files
- How to run Flask streaming server
- Port configuration (default: 9000)
- Video file format requirements
- Storage and organization guidelines

### Root Documentation Updates
- Update `CLAUDE.md` with new structure
- Update `ARCHITECTURE.md` with new paths
- Update `DEPLOYMENT.md` with new process
- Create `PR_SUMMARY.md` for Massimo

---

## Timeline Estimate

- Phase 1-2 (Structure + Copy): 30 minutes
- Phase 3 (Update Code): 1-2 hours
- Phase 4 (Clean & Document): 2-3 hours
- Phase 5 (Test & Verify): 1 hour
- Phase 6 (Finalize): 30 minutes

**Total: 5-7 hours of focused work**

---

## Risk Mitigation

- ✅ Commit frequently during migration
- ✅ Test after each phase before proceeding
- ✅ Keep old directories until fully verified
- ✅ Document all path changes in migration log
- ✅ Create rollback plan if needed

---

## Next Steps

1. Get approval on this structure
2. Begin Phase 1: Create directory structure
3. Proceed systematically through phases
4. Test thoroughly before removing old directories
5. Create PR with comprehensive documentation
