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
from openai import AsyncOpenAI

# Support both package and direct execution
try:
    from . import audio_pipeline, clip_search
except ImportError:
    import audio_pipeline, clip_search

load_dotenv(override=True)

# ── System prompt ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are the voice of a quirky, snarky art installation called Cinema Chat. You communicate ONLY through vintage movie and educational film clips from the 1930s-1970s.

You are NOT a helpful assistant. You're a conversational character — witty, playful, sometimes sarcastic, and often FUNNY. The participant speaks into a vintage telephone and sees your response as video clips on an old TV.

HOW TO RESPOND:
Don't just depict what the user said — RESPOND to it with personality! Be entertaining and try to make them laugh.

Bad: User says "I went to the supermarket" → searching "person shopping at supermarket" (boring, literal)
Good: User says "I went to the supermarket" → pick a clip about "fancy restaurant dining" (playful jab) or "housewife excited about groceries" (retro humor)

You will receive the user's speech and a list of available video clips with captions.
Pick THE SINGLE BEST clip that makes a witty, funny, or emotionally resonant response.

RESPOND WITH ONLY valid JSON (no markdown, no explanation):
{"pick": <rank_number>, "reasoning": "<brief explanation>"}

SELECTION CRITERIA:
- Caption — what words are SPOKEN in the clip (often perfect for witty responses)
- Visual — what's shown on screen
- Tone — does it match your snarky/playful vibe?
- Duration — prefer 5-15 second clips
- Humor — BE FUNNY above all else

All clips are already vintage — don't factor that in. Focus on the RESPONSE you want to give."""

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
        self.ws: WebSocket | None = None  # Reference for cleanup
        self.created_at: str = ""
        self.pi_client_pid: int | None = None

    def add_status(self, msg: str):
        """Add a status message visible to the dashboard."""
        self.status_messages.append(msg)


# ── Core pipeline ──────────────────────────────────────────────────────────

openai_client: AsyncOpenAI = None


async def handle_speech(ws: WebSocket, session: Session, pcm_audio: bytes):
    """Full pipeline: STT → Search → LLM pick → Play command."""
    if session.processing:
        logger.warning("Already processing — dropping overlapping speech")
        return

    session.processing = True
    pipeline_start = time.monotonic()

    try:
        # ── 1. Transcribe ──────────────────────────────────────────────
        await ws.send_json({"type": "status", "message": "Listening..."})
        text = audio_pipeline.transcribe(pcm_audio)

        if not text or len(text.strip()) < 2:
            logger.info("Empty transcription — ignoring")
            return

        await ws.send_json({"type": "transcript", "text": text})
        session.add_status(f"[USER] {text}")
        logger.info(f"[{session.session_id[:8]}] User: \"{text}\"")

        # ── 2. Semantic search ─────────────────────────────────────────
        t0 = time.monotonic()
        clips = await clip_search.search_clips(text, limit=5)
        search_time = time.monotonic() - t0
        logger.info(f"Search ({search_time:.2f}s): {len(clips)} clips")

        if not clips:
            await ws.send_json({"type": "status", "message": "No clips found"})
            return

        await ws.send_json({"type": "status", "message": "Choosing clip..."})

        # ── 3. LLM picks the best clip ─────────────────────────────────
        clips_text = clip_search.format_clips_for_llm(clips)

        # Build messages for this turn
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Add conversation history (last 6 turns for context)
        messages.extend(session.history[-6:])

        # Current turn
        messages.append({
            "role": "user",
            "content": f'The visitor said: "{text}"\n\nAvailable clips:\n{clips_text}',
        })

        t0 = time.monotonic()
        response = await openai_client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "gpt-4.1-mini"),
            messages=messages,
            temperature=0.9,
            max_tokens=150,
            response_format={"type": "json_object"},
        )
        llm_time = time.monotonic() - t0
        llm_text = response.choices[0].message.content.strip()
        logger.info(f"LLM ({llm_time:.2f}s): {llm_text}")

        # Parse LLM response
        try:
            choice = json.loads(llm_text)
            pick_rank = int(choice.get("pick", 1))
            reasoning = choice.get("reasoning", "")
        except (json.JSONDecodeError, ValueError, TypeError):
            logger.warning(f"Failed to parse LLM response, using top result: {llm_text}")
            pick_rank = 1
            reasoning = "top search result"

        # Find the chosen clip
        chosen = next((c for c in clips if c["rank"] == pick_rank), clips[0])

        # ── 4. Send play command ───────────────────────────────────────
        total_time = time.monotonic() - pipeline_start
        logger.info(
            f"Pipeline complete ({total_time:.2f}s): "
            f"playing {chosen['file']} [{chosen['start']}-{chosen['end']}s] — {reasoning}"
        )

        await ws.send_json({
            "type": "play",
            "video_path": chosen["file"],
            "start": chosen["start"],
            "end": chosen["end"],
            "fullscreen": True,
        })

        # Update conversation history
        caption_short = chosen["caption"][:80] if chosen["caption"] else ""
        session.history.append({"role": "user", "content": text})
        session.history.append({
            "role": "assistant",
            "content": f'[VIDEO: {caption_short}] (reasoning: {reasoning})',
        })

        # Track for dashboard
        session.add_status(f"[REASONING] {reasoning}")
        session.add_status(f"[VIDEO] {caption_short}")

        # Send timing info for debugging
        await ws.send_json({
            "type": "timing",
            "total_secs": round(total_time, 2),
            "search_secs": round(search_time, 2),
            "llm_secs": round(llm_time, 2),
        })

    except Exception as e:
        logger.exception(f"Pipeline error: {e}")
        await ws.send_json({"type": "error", "message": str(e)})
    finally:
        session.processing = False


# ── FastAPI app ────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global openai_client
    logger.info("Starting TwistedTV WebSocket server...")

    # Initialize audio pipeline (VAD + Whisper)
    audio_pipeline.init()

    # Initialize clip search (HTTP client + DB pool)
    await clip_search.init()

    # Initialize OpenAI client
    openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    logger.info("All services initialized — ready for connections")
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
    session_id = str(uuid.uuid4())
    session = Session(session_id)
    session.ws = ws
    session.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    active_sessions[session_id] = session
    logger.info(f"Pi connected: session {session_id[:8]}")

    try:
        while True:
            data = await ws.receive()

            if data.get("type") == "websocket.disconnect":
                break

            if "bytes" in data:
                # Binary frame = PCM audio
                pcm_chunk = data["bytes"]
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
                            # Simulate speech pipeline but skip STT
                            fake_session = Session(session_id)
                            fake_session.history = session.history
                            fake_session.processing = False

                            clips = await clip_search.search_clips(text, limit=5)
                            if clips:
                                clips_text = clip_search.format_clips_for_llm(clips)
                                messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                                messages.extend(session.history[-6:])
                                messages.append({
                                    "role": "user",
                                    "content": f'The visitor said: "{text}"\n\nAvailable clips:\n{clips_text}',
                                })
                                response = await openai_client.chat.completions.create(
                                    model=os.getenv("LLM_MODEL", "gpt-4.1-mini"),
                                    messages=messages,
                                    temperature=0.9,
                                    max_tokens=150,
                                    response_format={"type": "json_object"},
                                )
                                llm_text = response.choices[0].message.content.strip()
                                try:
                                    choice = json.loads(llm_text)
                                    pick_rank = int(choice.get("pick", 1))
                                except (json.JSONDecodeError, ValueError, TypeError):
                                    pick_rank = 1
                                chosen = next((c for c in clips if c["rank"] == pick_rank), clips[0])
                                await ws.send_json({
                                    "type": "play",
                                    "video_path": chosen["file"],
                                    "start": chosen["start"],
                                    "end": chosen["end"],
                                    "fullscreen": True,
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
        "ws_url": f"ws://{ws_host}:{ws_port}/ws/audio",
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
