# WSL2 Port Forwarding Setup for Video Server

## Problem
The video HTTP server running in WSL2 is not accessible from the Raspberry Pi on the LAN.

## Root Cause
- **WSL2 IP**: 172.28.172.5 (isolated network)
- **Windows Host LAN IP**: 192.168.1.143
- **Pi IP**: 192.168.1.201

When Python HTTP server binds to `0.0.0.0:9000` inside WSL2, Windows only forwards it to `127.0.0.1:9000` (localhost), making it inaccessible from the LAN.

## CRITICAL ISSUE: Network Isolation

**Problem**: Raspberry Pi cannot reach Windows host at 192.168.1.143 (100% packet loss on ping).

This is likely caused by Windows Firewall blocking ALL incoming traffic from the LAN, not just port 9000. The port-specific firewall rule we created isn't enough.

### Recommended Solutions (Try in Order)

#### Option 1: Allow Pi IP Through Windows Firewall (Recommended)

Create a firewall rule allowing ALL traffic from the Pi's IP:

```powershell
New-NetFirewallRule -DisplayName "Allow Raspberry Pi" -Direction Inbound -RemoteAddress 192.168.1.201 -Action Allow
```

#### Option 2: Set Windows Network to Private Profile

Windows blocks more traffic on "Public" networks. Change to "Private":

```powershell
# Find your network interface
Get-NetConnectionProfile

# Set to Private (replace InterfaceIndex with actual value from above)
Set-NetConnectionProfile -InterfaceIndex <INDEX> -NetworkCategory Private
```

#### Option 3: Temporarily Disable Windows Firewall (Testing Only)

**NOT RECOMMENDED for production**, but useful for testing:

```powershell
Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled False
```

To re-enable later:
```powershell
Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled True
```

## Solution (After Fixing Network Access)

### Step 1: Create Port Proxy (Windows Administrator Required) ✅ COMPLETED

Open PowerShell **as Administrator** and run:

```powershell
netsh interface portproxy add v4tov4 listenport=9000 listenaddress=0.0.0.0 connectport=9000 connectaddress=172.28.172.5
```

This creates a port forward from Windows host's LAN interface to WSL2.

### Step 2: Verify Port Proxy

```powershell
netsh interface portproxy show all
```

Expected output:
```
Listen on ipv4:             Connect to ipv4:

Address         Port        Address         Port
--------------- ----------  --------------- ----------
0.0.0.0         9000        172.28.172.5    9000
```

### Step 3: Test from Pi

From the Raspberry Pi, test access to video server:

```bash
curl -I http://192.168.1.143:9000/hemo_the_magnificent.mp4.mkv
```

Expected response:
```
HTTP/1.0 200 OK
Server: SimpleHTTP/0.6 Python/3.11.x
Content-type: video/x-matroska
Content-Length: 85958451
```

### Step 4: Update MCP Configuration

Update `mcp/mock_server.py` line 31 to use Windows host IP:

```python
VIDEO_SERVER_URL = os.getenv("VIDEO_SERVER_URL", "http://192.168.1.143:9000")
```

## Current Status (UPDATED: 2025-11-24 21:00) ✅ FULLY OPERATIONAL!

### Network Infrastructure ✅
- ✅ Windows Firewall rule created for port 9000 inbound
- ✅ Port proxy configured (0.0.0.0:9000 → 172.28.172.5:9000)
- ✅ HTTP server running on WSL2 0.0.0.0:9000
- ✅ Videos available: `hemo_the_magnificent.mp4.mkv` (82MB)
- ✅ Port proxy tested working from WSL2 → Windows host IP
- ✅ Windows network set to Private profile (was Public)
- ✅ Pi can now reach Windows host (192.168.1.143) - 0% packet loss
- ✅ Pi can access video server via HTTP (200 OK)

### Application Stack ✅
- ✅ MCP mock server configured to use Windows host IP (192.168.1.143:9000)
- ✅ Pi video playback service running (PID 74288) and healthy
- ✅ Pi Daily.co RTVI client supports video playback commands
- ✅ Backend sends RTVI video-playback-command messages
- ✅ Manual video streaming test: SUCCESSFUL
- ✅ End-to-end architecture complete and ready for testing

### Video Playback Flow
```
User speaks → STT → LLM → MCP → Backend Handler
                                      ↓
                            RTVI video-playback-command
                                      ↓
                            Pi Daily RTVI Client
                                      ↓
                            Pi Video Playback Service
                                      ↓
                          HTTP Stream from Windows Host
                                      ↓
                               TV via mpv/DRM
```

## Alternative: Direct WSL2 Access (Not Recommended)

If you don't want to use Windows host IP, you could try accessing WSL2 IP directly from Pi, but this requires:
1. WSL2 network bridge configuration
2. More complex firewall rules
3. Less reliable across WSL2 restarts

The port proxy approach is simpler and more robust.

## Cleanup (if needed)

To remove the port proxy:
```powershell
netsh interface portproxy delete v4tov4 listenport=9000 listenaddress=0.0.0.0
```

## Notes

- Port proxy persists across reboots
- If Windows host IP changes (DHCP), update `VIDEO_SERVER_URL`
- Consider using Windows host hostname instead of IP for stability
- The Pi video playback service supports both local files and HTTP URLs
