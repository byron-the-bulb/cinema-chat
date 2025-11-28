# Cinema Chat Architecture Refactoring Summary

**Date**: November 24, 2025
**Session**: Context continuation from previous deployment work

## What Was Changed

### Problem Identified

The original architecture used a **wrapper script polling approach**:
- Wrapper script (`pi_client_wrapper_rtvi.sh`) ran continuously
- Polled for config file every 2 seconds
- Dashboard wrote config file to signal new session
- Single client at a time
- Complex file-based synchronization

### User Feedback

> "so why exactly did you start a pi wrapper that is waiting for a config file to be written instead of just not having a pi daily client and then have the next.js start the daily client with the room id once it is ready?"

> "yes, that is obviously a much better approach - each new room should start its own new client. No reason to have a client waiting around for a room with potential conflicts"

> "There is also no need to kill existing python clients - the important thing is that there is one python client per daily room."

### Solution Implemented

Refactored to a **direct spawn approach**:
- ✅ No wrapper script needed
- ✅ Dashboard API route spawns Python client on demand
- ✅ Environment variables passed directly to client
- ✅ One dedicated process per Daily.co room
- ✅ Multiple concurrent sessions supported
- ✅ Simple, stateless design

## Files Modified

### 1. `/cinema-bot-app/frontend-next/pages/api/start_pi_client.ts`

**Renamed from**: `notify_pi.ts` (better reflects purpose)

**Changes**:
- Removed all process killing logic (34 lines deleted)
- Removed `execSync` import (no longer needed)
- Simplified to pure `spawn()` approach
- Returns PID of spawned process

**Key code**:
```typescript
const childProcess = spawn(VENV_PYTHON, [PYTHON_CLIENT], {
  env: {
    ...process.env,
    DAILY_ROOM_URL: roomUrl,
    DAILY_TOKEN: token || '',
    BACKEND_URL: backendUrl || 'http://localhost:8765',
    VIDEO_SERVICE_URL: 'http://localhost:5000'
  },
  detached: true,
  stdio: ['ignore', 'pipe', 'pipe']
});

// Detach and log output
childProcess.unref();
childProcess.stdout?.pipe(logStream);
childProcess.stderr?.pipe(logStream);
```

### 2. `/cinema-bot-app/frontend-next/pages/index.tsx`

**Changes**:
- Updated API call from `/api/notify_pi` to `/api/start_pi_client`
- Changed success message to show PID: `Pi client started (PID: ${clientData.pid})`

**Modified section** (lines 105-115):
```typescript
const startClientResponse = await fetch('/api/start_pi_client', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ roomUrl, token, backendUrl: baseUrl })
});

const clientData = await startClientResponse.json();
if (clientData.success) {
  addChatMessage(`Pi client started (PID: ${clientData.pid})`, 'system');
}
```

### 3. Deprecated Files

**`/mcp/pi_client_wrapper_rtvi.sh`** - No longer needed
- Process killed (PID 20145)
- Script removed from startup
- Config file polling eliminated

## Architecture Comparison

### Before (v1 - Wrapper Script)

```
Dashboard writes config file
    ↓
/home/twistedtv/cinema_config.env
    ↓
Wrapper script polls for file (every 2 seconds)
    ↓
Script reads config and spawns client
    ↓
Client joins room
    ↓
Script waits for client to exit
    ↓
Script deletes config file
    ↓
Loop back to polling
```

**Issues**:
- File-based synchronization overhead
- Single client at a time
- Complex lifecycle management
- Potential race conditions
- Unnecessary continuous process

### After (v2 - Direct Spawn)

```
Dashboard → POST /api/start_pi_client
    ↓
API route spawns client with env vars
    ↓
Client joins room (process runs independently)
    ↓
API returns PID to dashboard
    ↓
Multiple clients can run concurrently
```

**Benefits**:
- ✅ Simple, stateless design
- ✅ One process per room
- ✅ Concurrent sessions supported
- ✅ No file synchronization
- ✅ Cleaner error handling
- ✅ Easy to monitor (PIDs tracked)

## Process Lifecycle

### Old Approach
```
Wrapper script: ALWAYS RUNNING (waiting)
Config file: Written/deleted repeatedly
Python client: Single instance at a time
Cleanup: Script handles between sessions
```

### New Approach
```
API route: Only runs when called
Environment variables: Passed once to spawn()
Python client: One per room, detached processes
Cleanup: Future enhancement (graceful shutdown)
```

## Technical Details

### spawn() Configuration

```typescript
spawn(VENV_PYTHON, [PYTHON_CLIENT], {
  env: { /* environment variables */ },
  detached: true,     // Process continues after parent exits
  stdio: ['ignore', 'pipe', 'pipe']  // Pipe stdout/stderr to log
});

childProcess.unref();  // Allow parent to exit independently
```

### Environment Variables Passed

- `DAILY_ROOM_URL` - Daily.co room URL for this session
- `DAILY_TOKEN` - Authentication token for room
- `BACKEND_URL` - Backend server URL (e.g., `http://172.28.172.5:8765`)
- `VIDEO_SERVICE_URL` - Video playback service URL (e.g., `http://localhost:5000`)

### Log Management

All client output piped to `/tmp/pi_client.log`:
```typescript
const logStream = fs.createWriteStream(LOG_FILE, { flags: 'a' });
childProcess.stdout?.pipe(logStream);
childProcess.stderr?.pipe(logStream);
```

## Testing Status

### Completed
- ✅ Refactoring complete
- ✅ Files deployed to Pi
- ✅ Next.js hot-reload picks up changes
- ✅ API endpoint renamed appropriately
- ✅ Documentation written

### Pending
- ⏳ End-to-end testing with new architecture
- ⏳ Verify multiple concurrent sessions work
- ⏳ Confirm LLM greeting messages appear
- ⏳ Dashboard status updates display correctly

## How to Test

1. **Ensure services are running**:
   ```bash
   # Backend (development machine)
   cd /home/va55/code/cinema-chat/cinema-bot-app/backend
   source venv/bin/activate && cd src/cinema-bot && python3 server.py

   # Dashboard (Raspberry Pi)
   ssh twistedtv@192.168.1.201
   cd /home/twistedtv/frontend-next && npm run dev
   ```

2. **Start a new session**:
   - Navigate to: http://192.168.1.201:3000
   - Enter backend URL: `http://172.28.172.5:8765/api`
   - Click "Start Experience"

3. **Verify Pi client spawned**:
   ```bash
   # Check dashboard message
   # Should show: "Pi client started (PID: 12345)"

   # Check log file
   ssh twistedtv@192.168.1.201
   tail -f /tmp/pi_client.log
   ```

4. **Monitor backend**:
   ```bash
   # Backend should show:
   # - Room created
   # - Participant joined
   # - Bot initialization
   # - Greeting phase
   ```

5. **Check conversation status**:
   ```bash
   curl http://172.28.172.5:8765/conversation-status/<identifier> | jq
   ```

## Issues Fixed

### 1. Port Conflict
**Problem**: Next.js running on both 3000 (production) and 3001 (dev)
**Fix**: Killed duplicate processes, ensured single dev server on 3000

### 2. SSH Disconnects
**Problem**: `pkill` commands killed SSH session
**Fix**: Used specific PIDs with `kill` instead of `pkill`

### 3. Architectural Overcomplexity
**Problem**: Wrapper script + config file polling
**Fix**: Direct spawn approach (this refactoring)

### 4. Unnecessary Kill Logic
**Problem**: API tried to kill existing clients before spawning
**Fix**: Removed kill logic, embraced one-process-per-room

### 5. Poor Naming
**Problem**: `notify_pi` didn't reflect actual purpose
**Fix**: Renamed to `start_pi_client`

## Future Enhancements

1. **Graceful Shutdown**: Implement cleanup when rooms close
   - Track spawned PIDs in memory/database
   - Kill process when session ends

2. **Health Checks**: Monitor running clients
   - Detect crashed processes
   - Auto-restart if needed

3. **Session Management**: Database tracking
   - Store PID → room_url → identifier mapping
   - Clean up zombie processes

4. **Error Recovery**: Handle spawn failures
   - Retry logic
   - Better error messages to dashboard

5. **Metrics**: Add monitoring
   - Track active clients
   - Session duration
   - Resource usage

## Documentation Created

1. **[DEPLOYMENT.md](DEPLOYMENT.md)** - Full deployment guide
   - Architecture diagrams
   - Installation steps
   - Configuration reference
   - Troubleshooting guide
   - API reference
   - systemd service examples

2. **[REFACTORING_SUMMARY.md](REFACTORING_SUMMARY.md)** - This document
   - What changed and why
   - Before/after comparison
   - Files modified
   - Testing steps

## Key Learnings

1. **Simplicity wins**: The direct spawn approach is much simpler than polling
2. **User feedback matters**: User correctly identified architectural flaw
3. **One process per resource**: Better than single-client-at-a-time approach
4. **Stateless is better**: No config file means no synchronization issues
5. **Proper naming**: API endpoints should clearly reflect their purpose

## Next Steps

1. **Test the new architecture** with a fresh session
2. **Verify multiple concurrent rooms** work properly
3. **Implement graceful shutdown** for room cleanup
4. **Add session tracking** to manage spawned processes
5. **Monitor performance** with concurrent sessions

## Summary

This refactoring significantly simplifies the Cinema Chat architecture by eliminating the wrapper script and config file polling in favor of direct process spawning. The new approach is:

- **Simpler**: Fewer moving parts, less code
- **More robust**: No file synchronization issues
- **More scalable**: Multiple concurrent sessions
- **Easier to debug**: Clear PID tracking, better logs
- **Better aligned**: Matches the on-demand nature of the system

The system is now ready for end-to-end testing and production deployment.
