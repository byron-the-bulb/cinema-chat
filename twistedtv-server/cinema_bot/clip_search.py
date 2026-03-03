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


async def search_clips(
    query: str,
    limit: int = 5,
    dialog_weight: Optional[float] = None,
    visual_weight: Optional[float] = None,
    dialog_query: Optional[str] = None,
    visual_query: Optional[str] = None,
) -> list[dict]:
    """
    Search for video clips matching a semantic description.
    Uses /search/clips endpoint (three-lane merge: dialog + CLIP + visual).
    Falls back to /search/text if /search/clips is not available.

    Args:
        query: Main search query (used for all lanes unless overridden).
        limit: Max results to return.
        dialog_weight: Weight for dialog lane (0-2, default 1.0). Higher = prefer dialog matches.
        visual_weight: Weight for visual/CLIP lane (0-2, default 1.0). Higher = prefer visual matches.
        dialog_query: Optional separate query for dialog search lane.
        visual_query: Optional separate query for visual/CLIP search lane.
    """
    fetch_limit = limit * 4

    # Build request payload with optional weight/query overrides
    payload = {"query": query, "limit": fetch_limit}
    if dialog_weight is not None:
        payload["dialog_weight"] = dialog_weight
    if visual_weight is not None:
        payload["visual_weight"] = visual_weight
    if dialog_query:
        payload["dialog_query"] = dialog_query
    if visual_query:
        payload["visual_query"] = visual_query

    # Try the new clips endpoint first
    try:
        resp = await _http_client.post(
            f"{GOODCLIPS_API_URL}/api/v1/search/clips",
            json=payload,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        parsed = await _parse_clip_results(results, limit)
        if parsed:
            return parsed
        logger.info("clips search returned no usable results, falling back to /search/text")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            logger.info("clips endpoint not available, falling back to /search/text")
        else:
            logger.error(f"clips search failed: {e}")
            return []
    except Exception as e:
        logger.warning(f"clips search failed, falling back to /search/text: {e}")

    # Fallback to legacy scene-based search
    return await _search_clips_legacy(query, fetch_limit, limit)


async def _parse_clip_results(results: list[dict], limit: int) -> list[dict]:
    """Parse results from the /search/clips endpoint."""
    clips = []
    for i, result in enumerate(results, 1):
        clip_data = result.get("clip", {})
        video_data = result.get("video", {})
        score = result.get("score", 0)
        duration = clip_data.get("duration", 0)

        if not (MIN_CLIP_SECS <= duration <= MAX_CLIP_SECS):
            continue
        if len(clips) >= limit:
            break

        video_url = ""
        filepath = video_data.get("filepath", "")
        if filepath:
            video_url = _build_video_url(filepath)

        title_val = video_data.get("title")
        if isinstance(title_val, str):
            title = title_val
        elif title_val is None:
            title = "Unknown"
        else:
            title = str(title_val)

        # Fetch timed caption lines for subtitle overlay
        video_id = clip_data.get("video_id")
        clip_start = clip_data.get("start_time", 0)
        clip_end = clip_data.get("end_time", 0)
        timed_captions = []
        if video_id and _db_pool:
            try:
                async with _db_pool.acquire() as conn:
                    rows = await conn.fetch(
                        """SELECT text, start_time, end_time FROM captions
                           WHERE video_id = $1 AND language = 'en'
                             AND start_time < $3 AND end_time > $2
                           ORDER BY start_time""",
                        video_id, clip_start, clip_end,
                    )
                    for row in rows:
                        timed_captions.append({
                            "text": row["text"],
                            "start": row["start_time"],
                            "end": row["end_time"],
                        })
            except Exception as e:
                logger.warning(f"Failed to get timed captions: {e}")

        clips.append({
            "rank": len(clips) + 1,
            "video_id": video_id,
            "file": video_url,
            "start": clip_start,
            "end": clip_end,
            "duration": round(duration, 1),
            "similarity": f"{score * 100:.0f}%",
            "title": title,
            "caption": clip_data.get("label", ""),
            "clip_type": clip_data.get("clip_type", ""),
            "captions": timed_captions,
        })

    return clips


async def _search_clips_legacy(query: str, fetch_limit: int, limit: int) -> list[dict]:
    """Fallback: search via /search/text (dialog-based, pre-clips architecture).

    Uses the dialog search endpoint which returns clip_start/clip_end (tight
    boundaries around spoken text) and dialog_text.  Individual caption lines
    are fetched from the database for timed subtitle display.
    """
    try:
        resp = await _http_client.post(
            f"{GOODCLIPS_API_URL}/api/v1/search/text",
            json={"query": query, "limit": fetch_limit},
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except Exception as e:
        logger.error(f"GoodCLIPS dialog search failed: {e}")
        return []

    if not results:
        return []

    clips = []
    for result in results:
        clip_start = result.get("clip_start", 0)
        clip_end = result.get("clip_end", 0)
        duration = clip_end - clip_start
        if not (MIN_CLIP_SECS <= duration <= MAX_CLIP_SECS):
            continue
        if len(clips) >= limit:
            break

        scene = result.get("scene", {})
        distance = result.get("distance", 0)
        similarity = (1 - distance) * 100 if distance else 0
        video_id = scene.get("video_id")
        dialog_text = result.get("dialog_text", "")

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

        # Fetch individual caption lines for timed subtitles
        timed_captions = []
        if video_id and _db_pool:
            try:
                async with _db_pool.acquire() as conn:
                    rows = await conn.fetch(
                        """SELECT text, start_time, end_time FROM captions
                           WHERE video_id = $1 AND language = 'en'
                             AND start_time < $3 AND end_time > $2
                           ORDER BY start_time""",
                        video_id, clip_start, clip_end,
                    )
                    for row in rows:
                        timed_captions.append({
                            "text": row["text"],
                            "start": row["start_time"],
                            "end": row["end_time"],
                        })
            except Exception as e:
                logger.warning(f"Failed to get timed captions: {e}")

        clips.append({
            "rank": len(clips) + 1,
            "video_id": video_id,
            "file": video_url,
            "start": clip_start,
            "end": clip_end,
            "duration": round(duration, 1),
            "similarity": f"{similarity:.0f}%",
            "title": title,
            "caption": dialog_text,
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
        clip_type = c.get("clip_type", "")
        type_tag = f" [{clip_type}]" if clip_type else ""
        lines.append(
            f'{c["rank"]}. [{c["title"]}]{type_tag} {c["duration"]}s | {c["similarity"]} | "{caption_short}"'
        )
    return "\n".join(lines)
