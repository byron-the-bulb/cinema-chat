"""RTVI Bot Server Implementation for Cinema Chat Voice Bot.

This FastAPI server manages RTVI bot instances and provides endpoints for both
direct browser access and RTVI client connections. It handles:
- Creating Daily rooms
- Managing bot processes
- Providing connection credentials
- Monitoring bot status
"""

import argparse
import os
import subprocess
import sys
import urllib.parse
from contextlib import asynccontextmanager
from typing import Any, Dict, List
from datetime import datetime
import signal

import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
import uuid
import json
import base64

from pipecat.transports.services.helpers.daily_rest import DailyRESTHelper, DailyRoomParams

# Load environment variables from .env file
load_dotenv(override=True)

# Maximum number of bot instances allowed per room
MAX_BOTS_PER_ROOM = 1

# Dictionary to track bot processes: {pid: (process, room_url)}
bot_procs = {}

# Dictionary to track bot status: {room_url: {status: str, context: dict}}
bot_status = {}
participant_status = {}

# Dictionary to track active rooms: {room_url: {identifier, bot_pid, pi_client_pid, created_at}}
active_rooms = {}

# Store Daily API helpers
daily_helpers = {}


def kill_process_tree(pid: int) -> bool:
    """Kill a process and all its children.

    Args:
        pid (int): Process ID to kill

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Get process group and kill the entire tree
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        return True
    except (ProcessLookupError, PermissionError, OSError) as e:
        print(f"Error killing process {pid}: {e}")
        try:
            # Fallback: try direct kill
            os.kill(pid, signal.SIGTERM)
            return True
        except (ProcessLookupError, PermissionError, OSError) as e2:
            print(f"Error in fallback kill for {pid}: {e2}")
            return False


def cleanup_room(room_url: str) -> Dict[str, Any]:
    """Cleanup a specific room and all associated processes.

    Args:
        room_url (str): URL of the room to clean up

    Returns:
        Dict[str, Any]: Status of cleanup operations
    """
    result = {
        "room_url": room_url,
        "bot_terminated": False,
        "pi_client_terminated": False,
        "video_service_terminated": False,
        "errors": []
    }

    if room_url not in active_rooms:
        result["errors"].append(f"Room {room_url} not found in active rooms")
        return result

    room_info = active_rooms[room_url]

    # Terminate bot process
    bot_pid = room_info.get("bot_pid")
    if bot_pid:
        proc_entry = bot_procs.get(bot_pid)
        if proc_entry:
            proc = proc_entry[0]
            try:
                proc.terminate()
                proc.wait(timeout=5)
                result["bot_terminated"] = True
                print(f"Terminated bot process {bot_pid} for room {room_url}")
            except subprocess.TimeoutExpired:
                proc.kill()
                result["bot_terminated"] = True
                print(f"Force killed bot process {bot_pid} for room {room_url}")
            except Exception as e:
                result["errors"].append(f"Error terminating bot {bot_pid}: {e}")

            # Remove from tracking
            del bot_procs[bot_pid]

    # Terminate Pi client process (if tracked)
    # NOTE: Pi client runs on the Pi, so we send termination request via SSH
    pi_client_pid = room_info.get("pi_client_pid")
    if pi_client_pid:
        try:
            # Kill via SSH to avoid killing our own connection
            subprocess.run(
                ['ssh', 'twistedtv@192.168.1.201', f'kill {pi_client_pid}'],
                check=False,
                timeout=5
            )
            result["pi_client_terminated"] = True
            print(f"Terminated Pi client process {pi_client_pid} for room {room_url}")
        except Exception as e:
            result["errors"].append(f"Error terminating Pi client {pi_client_pid}: {e}")

    # Terminate video playback service (if tracked)
    video_service_pid = room_info.get("video_service_pid")
    if video_service_pid:
        try:
            # Kill via SSH
            subprocess.run(
                ['ssh', 'twistedtv@192.168.1.201', f'kill {video_service_pid}'],
                check=False,
                timeout=5
            )
            result["video_service_terminated"] = True
            print(f"Terminated video service {video_service_pid} for room {room_url}")
        except Exception as e:
            result["errors"].append(f"Error terminating video service {video_service_pid}: {e}")

    # Clean up status tracking
    if room_url in bot_status:
        del bot_status[room_url]

    identifier = room_info.get("identifier")
    if identifier and identifier in participant_status:
        del participant_status[identifier]

    # Remove from active rooms
    del active_rooms[room_url]

    return result


def cleanup():
    """Cleanup function to terminate all bot processes.

    Called during server shutdown.
    """
    # Clean up all active rooms
    room_urls = list(active_rooms.keys())
    for room_url in room_urls:
        cleanup_room(room_url)

    # Clean up any remaining bot processes
    for entry in bot_procs.values():
        proc = entry[0]
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        except Exception as e:
            print(f"Error during cleanup: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan manager that handles startup and shutdown tasks.

    - Creates aiohttp session
    - Initializes Daily API helper
    - Cleans up resources on shutdown
    """
    aiohttp_session = aiohttp.ClientSession()
    daily_helpers["rest"] = DailyRESTHelper(
        daily_api_key=os.getenv("DAILY_API_KEY", ""),
        daily_api_url=os.getenv("DAILY_API_URL", "https://api.daily.co/v1"),
        aiohttp_session=aiohttp_session,
    )
    yield
    await aiohttp_session.close()
    # Clear status on shutdown
    bot_status.clear()
    cleanup()


# Initialize FastAPI app with lifespan manager
app = FastAPI(lifespan=lifespan)

# Configure CORS to allow requests from any origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def create_room_and_token() -> tuple[str, str]:
    """Helper function to create a Daily room and generate an access token.

    Returns:
        tuple[str, str]: A tuple containing (room_url, token)

    Raises:
        HTTPException: If room creation or token generation fails
    """
    room_url = os.getenv("DAILY_SAMPLE_ROOM_URL", None)
    token = os.getenv("DAILY_SAMPLE_ROOM_TOKEN", None)
    if not room_url:
        room = await daily_helpers["rest"].create_room(DailyRoomParams())
        if not room.url:
            raise HTTPException(status_code=500, detail="Failed to create room")
        room_url = room.url
        print(f"Created room: {room_url}")

    if not token:
        token = await daily_helpers["rest"].get_token(room_url)
        if not token:
            raise HTTPException(status_code=500, detail=f"Failed to get token for room: {room_url}")
        else:
            print(f"Generated token for room: {room_url} : {token}")

    return room_url, token


@app.get("/")
async def start_agent(request: Request):
    """Endpoint for direct browser access to the bot.

    Creates a room, starts a bot instance, and redirects to the Daily room URL.

    Returns:
        RedirectResponse: Redirects to the Daily room URL

    Raises:
        HTTPException: If room creation, token generation, or bot startup fails
    """
    print("Creating room")
    room_url, token = await create_room_and_token()
    print(f"Room URL: {room_url}")

    # Check if there is already an existing process running in this room
    num_bots_in_room = sum(
        1 for proc in bot_procs.values() if proc[1] == room_url and proc[0].poll() is None
    )
    if num_bots_in_room >= MAX_BOTS_PER_ROOM:
        raise HTTPException(status_code=500, detail=f"Max bot limit reached for room: {room_url}")

    # Spawn a new bot process with a unique identifier
    # generate a uuid
    identifier = str(uuid.uuid4())

    # Get the src/ directory for PYTHONPATH (parent of cinema-bot/)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.dirname(current_dir)

    # Use sys.executable to get correct Python from venv, set PYTHONPATH
    env = os.environ.copy()
    env['PYTHONPATH'] = src_dir

    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "cinema-bot", "-u", room_url, "-t", token, "-i", identifier],
            bufsize=1,
            cwd=src_dir,
            env=env,
        )
        bot_procs[proc.pid] = (proc, room_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start subprocess: {e}")

    return RedirectResponse(room_url)


@app.post("/connect")
async def rtvi_connect(request: Request) -> Dict[Any, Any]:
    """RTVI connect endpoint that creates a room and returns connection credentials.

    This endpoint is called by RTVI clients to establish a connection.
    It extracts data from the request body and passes it to the cinema_bot subprocess.

    Returns:
        Dict[Any, Any]: Authentication bundle containing room_url and token

    Raises:
        HTTPException: If room creation, token generation, or bot startup fails
    """
    print("Creating room for RTVI connection")
    room_url, token = await create_room_and_token()
    print(f"Room URL: {room_url}")

    # Extract data from request body
    try:
        request_data = await request.json()
        print(f"Received request data: {request_data}")
    except Exception as e:
        print(f"Error parsing request body: {e}")
        request_data = {}

    # Start the bot process with a unique identifier
    identifier = str(uuid.uuid4())

    # Get the src/ directory for PYTHONPATH (parent of cinema-bot/)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.dirname(current_dir)

    # Use sys.executable to get correct Python from venv, set PYTHONPATH
    env = os.environ.copy()
    env['PYTHONPATH'] = src_dir

    # Build command arguments list
    cmd_args = [sys.executable, "-m", "cinema-bot", "-u", room_url, "-t", token, "-i", identifier]

    # Add request data as a JSON-encoded command line argument if available
    if request_data:
        # Use base64 encoding to avoid command line escaping issues
        encoded_data = base64.b64encode(json.dumps(request_data).encode()).decode()
        cmd_args.extend(["-d", encoded_data])

    try:
        proc = subprocess.Popen(
            cmd_args,
            bufsize=1,
            cwd=src_dir,
            env=env,
        )
        bot_procs[proc.pid] = (proc, room_url)

        # Track this room in active_rooms
        active_rooms[room_url] = {
            "identifier": identifier,
            "bot_pid": proc.pid,
            "pi_client_pid": None,  # Will be updated by /register-pi-client
            "video_service_pid": None,  # Will be updated by /register-video-service
            "created_at": datetime.now().isoformat(),
            "status": "bot_started"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start subprocess: {e}")

    print(f"Bot subprocess started with identifier: {identifier}")

    # Return the authentication bundle in format expected by DailyTransport
    return {"room_url": room_url, "token": token, "identifier": identifier}


@app.get("/status/{pid}")
def get_process_status(pid: int):
    """Get the status of a specific bot process.

    Args:
        pid (int): Process ID of the bot

    Returns:
        JSONResponse: Status information for the bot

    Raises:
        HTTPException: If the specified bot process is not found
    """
    # Look up the subprocess
    proc = bot_procs.get(pid)

    # If the subprocess doesn't exist, return an error
    if not proc:
        raise HTTPException(status_code=404, detail=f"Bot with process id: {pid} not found")

    # Get process info
    process, room_url = proc
    process_status = "running" if process.poll() is None else "finished"
    
    # Build response with process status and conversation status if available
    response = {
        "bot_id": pid, 
        "process_status": process_status,
        "room_url": room_url
    }
    
    # Add conversation status if available
    if room_url in bot_status:
        response["conversation_status"] = bot_status[room_url]
    
    return JSONResponse(response)


@app.get("/conversation-status/{identifier}")
async def get_conversation_status(identifier: str, last_seen: int = 0):
    """Get the conversation status for a specific participant or room.

    Args:
        identifier (str): Participant ID or room URL
        last_seen (int): Index of last seen status message (for pagination)

    Returns:
        JSONResponse: Conversation status information with only new messages
    """
    # Look up by participant ID
    print(f"Looking up conversation status for: {identifier} (last_seen={last_seen})")
    if identifier in participant_status:
        print(f"Conversation status found for: {identifier}")
        status_data = participant_status[identifier].copy()

        # Only return new status messages (pagination)
        if "context" in status_data and "status_messages" in status_data["context"]:
            all_messages = status_data["context"]["status_messages"]
            new_messages = all_messages[last_seen:]
            status_data["context"]["status_messages"] = new_messages
            status_data["context"]["total_message_count"] = len(all_messages)
            print(f"Returning {len(new_messages)} new status messages (total: {len(all_messages)})")

        return JSONResponse(status_data)

    # Default status if not found
    return JSONResponse({"status": "initializing", "context": {}})


@app.post("/update-status")
async def update_conversation_status(request: Request):
    """Update the conversation status using participant ID as primary identifier.

    Args:
        request (Request): Request containing the new status with identifier

    Returns:
        JSONResponse: Updated conversation status
    """
    data = await request.json()
    print(f"Status update data: {data}")

    # Check for required identifier
    if "identifier" not in data:
        return JSONResponse(
            {"error": "identifier is required"},
            status_code=400
        )

    identifier = data["identifier"]
    print(f"Updating status for identifier: {identifier}")

    # Create or update the status for this participant
    if identifier not in participant_status:
        print(f"Creating new status entry for identifier: {identifier}")
        participant_status[identifier] = {
            "status": "initializing",
            "identifier": identifier,
            "context": {
                "messages": [],
                "status_messages": []  # All status updates (including reasoning/video)
            }
        }

    # Initialize context if it doesn't exist
    if "context" not in participant_status[identifier]:
        participant_status[identifier]["context"] = {
            "messages": [],
            "status_messages": []
        }

    # Update main status field
    participant_status[identifier]["status"] = data.get("status", participant_status[identifier].get("status"))
    participant_status[identifier]["status_context"] = data.get("status_context")
    participant_status[identifier]["ui_override"] = data.get("ui_override")
    participant_status[identifier]["identifier"] = identifier

    # Also add status to status_messages array for display
    status_text = data.get("status", "")
    if status_text:
        if "status_messages" not in participant_status[identifier]["context"]:
            participant_status[identifier]["context"]["status_messages"] = []
        participant_status[identifier]["context"]["status_messages"].append(status_text)
        print(f"Added status message: {status_text[:100]}...")

    return JSONResponse(participant_status[identifier])


@app.get("/api/pi/audio-devices")
async def get_pi_audio_devices():
    """Get list of available audio input devices on the Raspberry Pi.

    Returns:
        JSON response with list of audio devices
    """
    try:
        # SSH to Pi and run arecord -l to list audio capture devices
        pi_host = os.getenv("PI_HOST", "192.168.1.201")
        pi_user = os.getenv("PI_USER", "twistedtv")

        result = subprocess.run(
            ["ssh", f"{pi_user}@{pi_host}", "arecord -l"],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode != 0:
            raise Exception(f"arecord command failed: {result.stderr}")

        # Parse arecord output to extract devices
        # Format: card 1: Device [USB Audio Device], device 0: USB Audio [USB Audio]
        devices = []
        for line in result.stdout.split('\n'):
            if line.startswith('card'):
                # Extract card and device numbers
                parts = line.split(':')
                if len(parts) >= 2:
                    card_part = parts[0].strip()
                    device_part = parts[1].strip() if len(parts) > 1 else ""

                    # Extract card number
                    card_num = int(card_part.split()[1])

                    # Extract device name
                    device_name = device_part.split('[')[1].split(']')[0] if '[' in device_part else "Unknown"

                    # Extract device number from "device 0:" format
                    device_num = 0
                    for part in parts:
                        if 'device' in part:
                            device_num = int(part.split()[1].replace(':', ''))
                            break

                    # Create ALSA device ID
                    alsa_id = f"hw:{card_num},{device_num}"

                    devices.append({
                        "card": card_num,
                        "device": device_num,
                        "name": device_name,
                        "alsa_id": alsa_id
                    })

        return JSONResponse({
            "devices": devices,
            "raw_output": result.stdout
        })

    except Exception as e:
        print(f"Error getting Pi audio devices: {e}")
        return JSONResponse(
            {"error": str(e), "devices": []},
            status_code=500
        )


@app.post("/api/pi/audio-device")
async def set_pi_audio_device(request: Request):
    """Set the active audio input device on the Raspberry Pi.

    Request body:
        {
            "device_id": "hw:1,0"  # ALSA device ID
        }

    Returns:
        JSON response with success status
    """
    try:
        data = await request.json()
        device_id = data.get("device_id")

        if not device_id:
            return JSONResponse(
                {"error": "device_id is required"},
                status_code=400
            )

        # Store the selected device in an environment variable file on the Pi
        # This will be used by the Pi client when it starts
        pi_host = os.getenv("PI_HOST", "192.168.1.201")
        pi_user = os.getenv("PI_USER", "twistedtv")

        # Create a config file on the Pi with the selected device
        config_content = f"AUDIO_DEVICE={device_id}\n"

        result = subprocess.run(
            ["ssh", f"{pi_user}@{pi_host}",
             f"echo '{config_content}' > /home/{pi_user}/audio_device.conf"],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode != 0:
            raise Exception(f"Failed to set audio device: {result.stderr}")

        return JSONResponse({
            "success": True,
            "message": f"Audio device set to {device_id}",
            "device_id": device_id
        })

    except Exception as e:
        print(f"Error setting Pi audio device: {e}")
        return JSONResponse(
            {"error": str(e)},
            status_code=500
        )


@app.get("/rooms")
async def list_active_rooms() -> JSONResponse:
    """List all active rooms with their details.

    Returns:
        JSONResponse: List of active rooms with status information
    """
    # Clean up dead processes first
    rooms_to_remove = []
    for room_url, room_info in active_rooms.items():
        bot_pid = room_info.get("bot_pid")
        if bot_pid and bot_pid in bot_procs:
            proc = bot_procs[bot_pid][0]
            if proc.poll() is not None:
                # Process is dead, mark for removal
                rooms_to_remove.append(room_url)

    for room_url in rooms_to_remove:
        print(f"Removing dead room: {room_url}")
        cleanup_room(room_url)

    # Return active rooms with detailed status
    rooms_list = []
    for room_url, room_info in active_rooms.items():
        bot_pid = room_info.get("bot_pid")
        bot_running = False
        if bot_pid and bot_pid in bot_procs:
            proc = bot_procs[bot_pid][0]
            bot_running = proc.poll() is None

        rooms_list.append({
            "room_url": room_url,
            "identifier": room_info.get("identifier"),
            "bot_pid": bot_pid,
            "bot_running": bot_running,
            "pi_client_pid": room_info.get("pi_client_pid"),
            "created_at": room_info.get("created_at"),
            "status": room_info.get("status")
        })

    return JSONResponse({
        "active_rooms": rooms_list,
        "total_count": len(rooms_list)
    })


@app.post("/cleanup-room")
async def cleanup_room_endpoint(request: Request) -> JSONResponse:
    """Cleanup a specific room and all associated processes.

    Request body:
        {
            "room_url": "https://..."
        }

    Returns:
        JSONResponse: Cleanup result with status of each operation
    """
    data = await request.json()
    room_url = data.get("room_url")

    if not room_url:
        return JSONResponse(
            {"error": "room_url is required"},
            status_code=400
        )

    result = cleanup_room(room_url)

    # Also try to delete the Daily room
    try:
        if daily_helpers.get("rest"):
            deleted = await daily_helpers["rest"].delete_room_by_url(room_url)
            result["daily_room_deleted"] = deleted
    except Exception as e:
        result["errors"].append(f"Error deleting Daily room: {e}")

    return JSONResponse(result)


@app.post("/cleanup-all-rooms")
async def cleanup_all_rooms_endpoint() -> JSONResponse:
    """Cleanup all active rooms.

    Returns:
        JSONResponse: Cleanup results for all rooms
    """
    results = []
    room_urls = list(active_rooms.keys())

    for room_url in room_urls:
        result = cleanup_room(room_url)

        # Try to delete the Daily room
        try:
            if daily_helpers.get("rest"):
                deleted = await daily_helpers["rest"].delete_room_by_url(room_url)
                result["daily_room_deleted"] = deleted
        except Exception as e:
            result["errors"].append(f"Error deleting Daily room: {e}")

        results.append(result)

    return JSONResponse({
        "cleaned_rooms": results,
        "total_cleaned": len(results)
    })


@app.post("/register-pi-client")
async def register_pi_client(request: Request) -> JSONResponse:
    """Register a Pi client PID with a room for tracking.

    Request body:
        {
            "room_url": "https://...",
            "pi_client_pid": 12345
        }

    Returns:
        JSONResponse: Registration status
    """
    data = await request.json()
    room_url = data.get("room_url")
    pi_client_pid = data.get("pi_client_pid")

    if not room_url or not pi_client_pid:
        return JSONResponse(
            {"error": "room_url and pi_client_pid are required"},
            status_code=400
        )

    if room_url in active_rooms:
        active_rooms[room_url]["pi_client_pid"] = pi_client_pid
        active_rooms[room_url]["status"] = "pi_client_connected"
        print(f"Registered Pi client PID {pi_client_pid} for room {room_url}")
        return JSONResponse({
            "success": True,
            "message": f"Pi client {pi_client_pid} registered for room {room_url}"
        })
    else:
        return JSONResponse(
            {"error": f"Room {room_url} not found in active rooms"},
            status_code=404
        )


@app.post("/register-video-service")
async def register_video_service(request: Request) -> JSONResponse:
    """Register a video playback service PID with a room for tracking.

    Request body:
        {
            "room_url": "https://...",
            "video_service_pid": 12345
        }

    Returns:
        JSONResponse: Registration status
    """
    data = await request.json()
    room_url = data.get("room_url")
    video_service_pid = data.get("video_service_pid")

    if not room_url or not video_service_pid:
        return JSONResponse(
            {"error": "room_url and video_service_pid are required"},
            status_code=400
        )

    if room_url in active_rooms:
        active_rooms[room_url]["video_service_pid"] = video_service_pid
        print(f"Registered video service PID {video_service_pid} for room {room_url}")
        return JSONResponse({
            "success": True,
            "message": f"Video service {video_service_pid} registered for room {room_url}"
        })
    else:
        return JSONResponse(
            {"error": f"Room {room_url} not found in active rooms"},
            status_code=404
        )


# Debug catch-all endpoint to help diagnose 404 issues
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def catch_all(request: Request, path: str):
    """Catch-all route for debugging purposes."""
    print(f"CATCH-ALL: Received request for path: {path}")
    print(f"CATCH-ALL: Method: {request.method}")
    print(f"CATCH-ALL: Headers: {request.headers}")
    
    try:
        if request.method in ["POST", "PUT"]:
            body = await request.json()
            print(f"CATCH-ALL: Body: {body}")
    except Exception as e:
        print(f"CATCH-ALL: Error parsing body: {e}")
    
    return JSONResponse({"message": f"Debug endpoint - received request for {path}"})


if __name__ == "__main__":
    import uvicorn

    # Parse command line arguments for server configuration
    default_host = os.getenv("HOST", "0.0.0.0")
    default_port = int(os.getenv("FAST_API_PORT", "8765"))

    parser = argparse.ArgumentParser(description="Cinema Chat Voice Bot FastAPI server")
    parser.add_argument(
        "--host", type=str, default=default_host, help="Host to run the server on"
    )
    parser.add_argument(
        "--port", type=int, default=default_port, help="Port to run the server on"
    )

    args = parser.parse_args()

    # Start the server
    uvicorn.run(app, host=args.host, port=args.port)
