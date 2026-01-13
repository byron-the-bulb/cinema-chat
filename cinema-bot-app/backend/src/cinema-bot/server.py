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
from typing import Any, Dict

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

# Store Daily API helpers
daily_helpers = {}


def cleanup():
    """Cleanup function to terminate all bot processes.

    Called during server shutdown.
    """
    for entry in bot_procs.values():
        proc = entry[0]
        proc.terminate()
        proc.wait()


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
async def get_conversation_status(identifier: str):
    """Get the conversation status for a specific participant or room.
    
    Args:
        identifier (str): Participant ID or room URL
        by_participant (bool): If True, use participant ID instead of room URL
        
    Returns:
        JSONResponse: Conversation status information
    """
    # Look up by participant ID
    print(f"Looking up conversation status for: {identifier}")
    if identifier in participant_status:
        print(f"Conversation status found for: {identifier}")
        return JSONResponse(participant_status[identifier])
    
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
        participant_status[identifier] = {}
    
    # Update the status with the provided data
    participant_status[identifier] = data
   
    return JSONResponse(participant_status[identifier])


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
