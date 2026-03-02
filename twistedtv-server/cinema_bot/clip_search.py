"""
Direct clip search module — replaces MCP client/server with direct HTTP calls.

Calls GoodCLIPS API for semantic search and PostgreSQL for captions.
"""

import os
import httpx
import asyncpg
from typing import Optional
from loguru import logger

GOODCLIPS_API_URL = os.getenv("GOODCLIPS_API_URL", "http://localhost:8080")
VIDEO_SERVER_URL = os.getenv("VIDEO_SERVER_URL", "http://192.168.1.106:9000")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_USER = os.getenv("DB_USER", "goodclips")
DB_PASSWORD = os.getenv("DB_PASSWORD", "goodclips_dev_password")
DB_NAME = os.getenv("DB_NAME", "goodclips")

_http_client: Optional[httpx.AsyncClient] = None
_db_pool: Optional[asyncpg.Pool] = None


async def init():
    """Initialize HTTP client and database pool."""
    global _http_client, _db_pool
    _http_client = httpx.AsyncClient(timeout=10.0)
    _db_pool = await asyncpg.create_pool(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        min_size=1,
        max_size=3,
    )
    logger.info(f"clip_search initialized: API={GOODCLIPS_API_URL}, DB={DB_HOST}:{DB_PORT}")


async def close():
    """Clean up resources."""
    global _http_client, _db_pool
    if _http_client:
        await _http_client.aclose()
    if _db_pool:
        await _db_pool.close()


def _build_video_url(filepath: str) -> str:
    filename = os.path.basename(filepath)
    return f"{VIDEO_SERVER_URL}/{filename}"


MIN_CLIP_SECS = float(os.getenv("MIN_CLIP_SECS", "2"))
MAX_CLIP_SECS = float(os.getenv("MAX_CLIP_SECS", "20"))


async def search_clips(query: str, limit: int = 5) -> list[dict]:
    """
    Search for video clips matching a semantic description.
    Returns a list of clip dicts with all metadata the LLM needs to pick one.
    Filters to clips between MIN_CLIP_SECS and MAX_CLIP_SECS.
    """
    # Request extra results so we still have enough after duration filtering
    fetch_limit = limit * 4
    try:
        resp = await _http_client.post(
            f"{GOODCLIPS_API_URL}/api/v1/search/semantic",
            json={"query": query, "limit": fetch_limit},
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except Exception as e:
        logger.error(f"GoodCLIPS search failed: {e}")
        return []

    if not results:
        return []

    # Pre-filter by duration before doing expensive lookups
    filtered = []
    for result in results:
        scene = result.get("scene", {})
        duration = scene.get("end_time", 0) - scene.get("start_time", 0)
        if MIN_CLIP_SECS <= duration <= MAX_CLIP_SECS:
            filtered.append(result)
        if len(filtered) >= limit:
            break

    if not filtered:
        logger.warning(f"No clips in {MIN_CLIP_SECS}-{MAX_CLIP_SECS}s range, using shortest available")
        # Fallback: sort by duration and take shortest ones
        results.sort(key=lambda r: abs(r.get("scene", {}).get("end_time", 0) - r.get("scene", {}).get("start_time", 0)))
        filtered = results[:limit]

    clips = []
    for i, result in enumerate(filtered, 1):
        scene = result.get("scene", {})
        distance = result.get("distance", 0)
        similarity = (1 - distance) * 100 if distance else 0
        video_id = scene.get("video_id")

        # Get video info for file path
        video_url = ""
        title = "Unknown"
        try:
            vresp = await _http_client.get(f"{GOODCLIPS_API_URL}/api/v1/videos/{video_id}")
            vresp.raise_for_status()
            video_info = vresp.json().get("video", {})
            video_url = _build_video_url(video_info.get("filepath", ""))
            title = video_info.get("title", "Unknown")
        except Exception as e:
            logger.warning(f"Failed to get video info for {video_id}: {e}")

        # Get dialogue captions from database (WhisperX audio transcriptions)
        caption = ""
        timed_captions = []
        scene_id = scene.get("id")
        if scene_id and _db_pool:
            try:
                async with _db_pool.acquire() as conn:
                    rows = await conn.fetch(
                        """SELECT text, start_time, end_time FROM captions
                           WHERE scene_id = $1 AND language = 'en'
                           ORDER BY start_time""",
                        scene_id,
                    )
                    for row in rows:
                        timed_captions.append({
                            "text": row["text"],
                            "start": row["start_time"],
                            "end": row["end_time"],
                        })
                    if timed_captions:
                        caption = timed_captions[0]["text"]
            except Exception as e:
                logger.warning(f"Failed to get captions for scene {scene_id}: {e}")

        clips.append({
            "rank": i,
            "video_id": video_id,
            "file": video_url,
            "start": scene.get("start_time", 0),
            "end": scene.get("end_time", 0),
            "duration": round(scene.get("end_time", 0) - scene.get("start_time", 0), 1),
            "similarity": f"{similarity:.0f}%",
            "title": title,
            "caption": caption,
            "captions": timed_captions,
        })

    return clips


def format_clips_for_llm(clips: list[dict]) -> str:
    """Format clip search results into a concise string for the LLM prompt."""
    if not clips:
        return "No clips found."

    lines = []
    for c in clips:
        caption_short = c["caption"][:120] + "..." if len(c["caption"]) > 120 else c["caption"]
        lines.append(
            f'{c["rank"]}. [{c["title"]}] {c["duration"]}s | {c["similarity"]} | "{caption_short}"'
        )
    return "\n".join(lines)
