"""
TwistedTV WebSocket Server — Direct LAN pipeline.

Replaces the Daily.co + Pipecat + MCP architecture with a simple
WebSocket server that processes audio directly on the LAN.

Pipeline: Pi audio → WebSocket → VAD → STT → Search → LLM → Play command → WebSocket → Pi
Target latency: <5 seconds end-to-end.
"""

import argparse
import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

# Support both package and direct execution
try:
    from . import audio_pipeline, clip_search
except ImportError:
    import audio_pipeline, clip_search

load_dotenv(override=True)

# ── System prompt ──────────────────────────────────────────────────────────

# ── Session tracking ───────────────────────────────────────────────────────

# Active sessions keyed by identifier
active_sessions: dict[str, "Session"] = {}


class Session:
    """Per-connection conversation state."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.history: list[dict] = []  # User/assistant turns for context
        self.status_messages: list[str] = []  # For dashboard polling
        self.vad = audio_pipeline.VADState(
            threshold=0.3,
            min_speech_ms=100,
            stop_secs=0.8,
        )
        self.processing = False  # Guard against overlapping requests
        self.playback_mute_until: float = 0  # Suppress VAD during clip playback
        self.ws: WebSocket | None = None  # Reference for cleanup
        self.created_at: str = ""
        self.pi_client_pid: int | None = None

    def mute_for_playback(self, clip_duration: float):
        """Mute audio processing while a clip is playing to prevent feedback."""
        # Add 1s buffer after clip ends for audio tail-off
        self.playback_mute_until = time.monotonic() + clip_duration + 1.0
        self.vad.reset()
        logger.info(f"Muting VAD for {clip_duration + 1.0:.1f}s (clip + buffer)")

    @property
    def is_muted(self) -> bool:
        return time.monotonic() < self.playback_mute_until

    def add_status(self, msg: str):
        """Add a status message visible to the dashboard."""
        self.status_messages.append(msg)


# ── Core pipeline ──────────────────────────────────────────────────────────


async def handle_greeting(ws: WebSocket, session: Session):
    """Play an opening greeting clip when a new session starts."""
    session.processing = True
    try:
        await ws.send_json({"type": "status", "message": "Starting up..."})
        session.add_status("[SYSTEM] Cinema Chat is waking up...")

        # Brief delay to let Pi's video service finish starting
        await asyncio.sleep(2)

        greeting_query = "person waving hello, friendly greeting"
        clips = await clip_search.search_clips(greeting_query, limit=5)
        if not clips:
            logger.warning("No greeting clips found")
            session.add_status("[SYSTEM] Ready — no movies ingested yet")
            return

        chosen = clips[0]
        clip_duration = chosen["end"] - chosen["start"]
        session.mute_for_playback(clip_duration)

        await ws.send_json({
            "type": "play",
            "video_path": chosen["file"],
            "start": chosen["start"],
            "end": chosen["end"],
            "fullscreen": True,
            "captions": chosen.get("captions", []),
        })

        caption_short = chosen["caption"][:80] if chosen.get("caption") else chosen["file"]
        session.add_status(f"[VIDEO: {caption_short}]")
        logger.info(f"Greeting: playing {chosen['file']} [{chosen['start']}-{chosen['end']}s]")

    except Exception as e:
        logger.exception(f"Greeting error: {e}")
    finally:
        session.processing = False


async def handle_speech(ws: WebSocket, session: Session, pcm_audio: bytes):
    """Fast pipeline: STT → Search → Play top result. No LLM step."""
    if session.processing:
        logger.warning("Already processing — dropping overlapping speech")
        return

    session.processing = True
    pipeline_start = time.monotonic()

    try:
        # ── 1. Transcribe ──────────────────────────────────────────────
        await ws.send_json({"type": "status", "message": "Listening..."})
        text = audio_pipeline.transcribe(pcm_audio)
        stt_time = time.monotonic() - pipeline_start

        if not text or len(text.strip()) < 2:
            logger.info("Empty transcription — ignoring")
            return

        await ws.send_json({"type": "transcript", "text": text})
        session.add_status(f"User: {text}")
        logger.info(f"[{session.session_id[:8]}] User: \"{text}\"")

        # ── 2. Search + Play ───────────────────────────────────────────
        t0 = time.monotonic()
        clips = await clip_search.search_clips(text, limit=5)
        search_time = time.monotonic() - t0

        if not clips:
            await ws.send_json({"type": "status", "message": "No clips found"})
            session.add_status("[SYSTEM] No clips found — database may be empty")
            return

        # Play the top search result directly — no LLM needed
        chosen = clips[0]
        total_time = time.monotonic() - pipeline_start
        clip_duration = chosen["end"] - chosen["start"]
        session.mute_for_playback(clip_duration)

        logger.info(
            f"Pipeline ({total_time:.2f}s | stt={stt_time:.2f} search={search_time:.2f}): "
            f"playing {chosen['file']} [{chosen['start']}-{chosen['end']}s]"
        )

        await ws.send_json({
            "type": "play",
            "video_path": chosen["file"],
            "start": chosen["start"],
            "end": chosen["end"],
            "fullscreen": True,
            "transcript": text,
            "captions": chosen.get("captions", []),
        })

        # Update conversation history
        caption_short = chosen["caption"][:80] if chosen["caption"] else ""
        session.history.append({"role": "user", "content": text})
        session.history.append({
            "role": "assistant",
            "content": f'[VIDEO: {caption_short}]',
        })

        # Track for dashboard — include search details + timing
        session.add_status(
            f"[SEARCH] \"{text}\" → #{chosen['rank']} {chosen['similarity']} "
            f"[{chosen['title']}] {chosen['duration']}s"
        )
        session.add_status(f"[VIDEO: {caption_short}]")

        await ws.send_json({
            "type": "timing",
            "total_secs": round(total_time, 2),
            "stt_secs": round(stt_time, 2),
            "search_secs": round(search_time, 2),
        })

    except Exception as e:
        logger.exception(f"Pipeline error: {e}")
        await ws.send_json({"type": "error", "message": str(e)})
    finally:
        session.processing = False


# ── FastAPI app ────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting TwistedTV WebSocket server...")

    # Initialize audio pipeline (VAD + Whisper)
    audio_pipeline.init()

    # Initialize clip search (HTTP client + DB pool)
    await clip_search.init()

    logger.info("All services initialized — ready for connections (no-LLM fast mode)")
    yield

    logger.info("Shutting down...")
    await clip_search.close()


app = FastAPI(title="TwistedTV WebSocket Server", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.websocket("/ws/audio")
async def audio_websocket(ws: WebSocket):
    """
    Main WebSocket endpoint for Pi audio streaming.

    Protocol:
        Pi → Server: binary PCM frames (16kHz mono 16-bit)
        Server → Pi: JSON messages (play, status, transcript, timing, error)
    """
    await ws.accept()

    # Reuse session from /connect if identifier provided, otherwise create new
    session_id = ws.query_params.get("session", "")
    session = active_sessions.get(session_id) if session_id else None

    if session:
        # Link the pre-created session to this WebSocket
        session.ws = ws
        logger.info(f"Pi connected: session {session_id[:8]} (linked to /connect)")
    else:
        # Direct connection without /connect — create a fresh session
        session_id = session_id or str(uuid.uuid4())
        session = Session(session_id)
        session.ws = ws
        session.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        active_sessions[session_id] = session
        logger.info(f"Pi connected: session {session_id[:8]} (new)")

    # Play opening greeting clip
    asyncio.create_task(handle_greeting(ws, session))

    frame_count = 0
    try:
        while True:
            data = await ws.receive()

            if data.get("type") == "websocket.disconnect":
                break

            if "bytes" in data:
                # Binary frame = PCM audio
                pcm_chunk = data["bytes"]
                frame_count += 1
                if frame_count == 1:
                    logger.info(f"First audio frame received: {len(pcm_chunk)} bytes")
                elif frame_count % 500 == 0:
                    logger.info(f"Audio frames received: {frame_count} (VAD speaking={session.vad.is_speaking}, muted={session.is_muted})")

                # Skip VAD while a clip is playing to prevent feedback loop
                if session.is_muted:
                    continue

                speech_started, speech_ended = session.vad.process_chunk(pcm_chunk)

                if speech_started:
                    await ws.send_json({"type": "status", "message": "Listening..."})

                if speech_ended:
                    speech_audio = session.vad.get_speech_audio()
                    if len(speech_audio) > 0:
                        # Process in background to keep receiving audio
                        asyncio.create_task(handle_speech(ws, session, speech_audio))

            elif "text" in data:
                # JSON text frame = control message from Pi
                try:
                    msg = json.loads(data["text"])
                    msg_type = msg.get("type")

                    if msg_type == "ping":
                        await ws.send_json({"type": "pong"})

                    elif msg_type == "text_input":
                        # Direct text input (for testing without audio)
                        text = msg.get("text", "")
                        if text:
                            clips = await clip_search.search_clips(text, limit=5)
                            if clips:
                                chosen = clips[0]
                                clip_duration = chosen["end"] - chosen["start"]
                                session.mute_for_playback(clip_duration)
                                await ws.send_json({
                                    "type": "play",
                                    "video_path": chosen["file"],
                                    "start": chosen["start"],
                                    "end": chosen["end"],
                                    "fullscreen": True,
                                    "transcript": text,
                                    "captions": chosen.get("captions", []),
                                })

                except json.JSONDecodeError:
                    pass

    except WebSocketDisconnect:
        logger.info(f"Pi disconnected: session {session_id[:8]}")
    except Exception as e:
        logger.exception(f"WebSocket error: {e}")
    finally:
        session.vad.reset()
        active_sessions.pop(session_id, None)
        logger.info(f"Session {session_id[:8]} cleaned up")


# ── HTTP endpoints for dashboard / monitoring ──────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "twistedtv-ws-server"}


@app.post("/connect")
async def connect():
    """
    Create a new session. Returns WebSocket URL for the Pi client.
    The actual session starts when the Pi connects to the WebSocket.
    """
    identifier = str(uuid.uuid4())
    ws_host = os.getenv("WS_HOST", "192.168.1.106")
    ws_port = os.getenv("FAST_API_PORT", "8765")

    # Pre-create session so /rooms shows it immediately
    session = Session(identifier)
    session.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    active_sessions[identifier] = session

    return {
        "ws_url": f"ws://{ws_host}:{ws_port}/ws/audio?session={identifier}",
        "identifier": identifier,
    }


@app.get("/rooms")
async def list_rooms():
    """List active sessions (backward-compatible with old /rooms endpoint)."""
    rooms_list = []

    for sid, session in active_sessions.items():
        # Check if WebSocket is still alive
        ws_connected = session.ws is not None
        rooms_list.append({
            "room_url": sid,  # Use session_id as room_url for compat
            "identifier": sid,
            "bot_pid": None,
            "bot_running": ws_connected,
            "pi_client_pid": session.pi_client_pid,
            "created_at": session.created_at,
            "status": "connected" if ws_connected else "waiting",
        })

    return JSONResponse({
        "active_rooms": rooms_list,
        "total_count": len(rooms_list),
    })


@app.post("/cleanup-room")
async def cleanup_room(request: Request):
    """Stop a session and close its WebSocket."""
    data = await request.json()
    room_url = data.get("room_url")

    result = {
        "room_url": room_url,
        "bot_terminated": False,
        "pi_client_terminated": False,
        "errors": [],
    }

    if not room_url:
        result["errors"].append("room_url is required")
        return JSONResponse(result, status_code=400)

    session = active_sessions.pop(room_url, None)
    if session:
        # Close WebSocket if still open
        if session.ws:
            try:
                await session.ws.close()
                result["bot_terminated"] = True
            except Exception as e:
                result["errors"].append(f"Error closing WebSocket: {e}")

        # Kill Pi client if tracked
        if session.pi_client_pid:
            import subprocess
            try:
                pi_host = os.getenv("PI_HOST", "192.168.1.109")
                pi_user = os.getenv("PI_USER", "twistedtv")
                subprocess.run(
                    ["ssh", f"{pi_user}@{pi_host}", f"kill {session.pi_client_pid}"],
                    check=False, timeout=5,
                )
                result["pi_client_terminated"] = True
            except Exception as e:
                result["errors"].append(f"Error killing Pi client: {e}")
    else:
        result["errors"].append(f"Session {room_url} not found")

    return JSONResponse(result)


@app.post("/cleanup-all-rooms")
async def cleanup_all_rooms():
    """Stop all active sessions."""
    results = []
    for sid in list(active_sessions.keys()):
        session = active_sessions.pop(sid, None)
        if session and session.ws:
            try:
                await session.ws.close()
                results.append({"identifier": sid, "closed": True})
            except Exception:
                results.append({"identifier": sid, "closed": False})
    return JSONResponse({"cleaned_rooms": results, "total_cleaned": len(results)})


@app.get("/conversation-status/{identifier}")
async def get_conversation_status(identifier: str, last_seen: int = 0):
    """
    Get conversation status for the dashboard.
    Returns new status messages since last_seen index.
    """
    session = active_sessions.get(identifier)
    if not session:
        return JSONResponse({"status": "not_found", "context": {}})

    all_messages = session.status_messages
    new_messages = all_messages[last_seen:]

    return JSONResponse({
        "status": "connected" if session.ws else "waiting",
        "identifier": identifier,
        "context": {
            "status_messages": new_messages,
            "total_message_count": len(all_messages),
            "messages": [
                {"role": h["role"], "content": h["content"]}
                for h in session.history
            ],
        },
    })


@app.post("/update-status")
async def update_status(request: Request):
    """Receive status updates (backward compat)."""
    data = await request.json()
    identifier = data.get("identifier")
    status = data.get("status", "")

    session = active_sessions.get(identifier)
    if session and status:
        session.add_status(status)

    return JSONResponse({"success": True})


@app.post("/register-pi-client")
async def register_pi_client(request: Request):
    """Track the Pi client PID for cleanup."""
    data = await request.json()
    identifier = data.get("room_url") or data.get("identifier")
    pid = data.get("pi_client_pid")

    session = active_sessions.get(identifier)
    if session and pid:
        session.pi_client_pid = pid
        return JSONResponse({"success": True})

    return JSONResponse({"success": False, "error": "Session not found"}, status_code=404)


if __name__ == "__main__":
    import uvicorn

    default_host = os.getenv("HOST", "0.0.0.0")
    default_port = int(os.getenv("FAST_API_PORT", "8765"))

    parser = argparse.ArgumentParser(description="TwistedTV WebSocket Server")
    parser.add_argument("--host", type=str, default=default_host)
    parser.add_argument("--port", type=int, default=default_port)
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port)
