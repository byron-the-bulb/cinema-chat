#!/usr/bin/env python3
"""
MCP Server for Cinema-Chat

This server connects to the GoodCLIPS semantic search API to find
video clips matching descriptions and plays them via the playback service.

Usage:
    python server.py
"""

import asyncio
import json
import os
import httpx
import asyncpg
from typing import Any, Optional, List
from mcp.server.models import InitializationOptions
from mcp.server import Server, NotificationOptions
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from config import Settings

# Configuration
settings = Settings()

# Database connection pool (lazy initialized)
_db_pool = None

async def get_db_pool():
    """Get or create the database connection pool."""
    global _db_pool
    if _db_pool is None:
        _db_pool = await asyncpg.create_pool(
            host=settings.db_host,
            port=settings.db_port,
            user=settings.db_user,
            password=settings.db_password,
            database=settings.db_name,
            min_size=1,
            max_size=5
        )
    return _db_pool

async def get_caption_for_scene(scene_id: int) -> str:
    """Fetch caption text (visual description) for a scene from the database."""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT text FROM captions WHERE scene_id = $1 LIMIT 1",
                scene_id
            )
            if row:
                return row['text']
    except Exception as e:
        print(f"Error fetching caption for scene {scene_id}: {e}", file=__import__('sys').stderr)
    return ""

# HTTP Video Playback Service URL (Pi video service)
PLAYBACK_SERVICE_URL = os.getenv("PLAYBACK_SERVICE_URL", "http://localhost:5000")

# Video server URL - where videos are served from
VIDEO_SERVER_URL = os.getenv("VIDEO_SERVER_URL", "http://192.168.1.113:9000")

# GoodCLIPS API URL
GOODCLIPS_API_URL = os.getenv("GOODCLIPS_API_URL", "http://localhost:8080")

app = Server("cinema-chat-mcp")
http_client = httpx.AsyncClient(timeout=30.0)


async def search_goodclips(query: str, limit: int = 5) -> List[dict]:
    """
    Search GoodCLIPS API for scenes matching a semantic description.

    Returns list of scene results with video info.
    """
    url = f"{GOODCLIPS_API_URL}/api/v1/search/semantic"

    try:
        response = await http_client.post(
            url,
            json={"query": query, "limit": limit}
        )
        response.raise_for_status()
        data = response.json()
        return data.get("results", [])
    except Exception as e:
        print(f"Error searching GoodCLIPS: {e}", file=__import__('sys').stderr)
        return []


async def get_video_info(video_id: int) -> Optional[dict]:
    """Get video metadata from GoodCLIPS API."""
    url = f"{GOODCLIPS_API_URL}/api/v1/videos/{video_id}"

    try:
        response = await http_client.get(url)
        response.raise_for_status()
        data = response.json()
        return data.get("video", {})
    except Exception as e:
        print(f"Error getting video {video_id}: {e}", file=__import__('sys').stderr)
        return None


async def get_api_stats() -> dict:
    """Get GoodCLIPS database statistics."""
    url = f"{GOODCLIPS_API_URL}/api/v1/stats"

    try:
        response = await http_client.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error getting stats: {e}", file=__import__('sys').stderr)
        return {"error": str(e)}


def build_video_url(filepath: str) -> str:
    """
    Convert a database filepath to a video server URL.

    Database stores paths like: /data/videos/metropolis.mp4
    Video server URL should be: http://192.168.1.113:9000/metropolis.mp4
    """
    # Extract just the filename from the path
    filename = os.path.basename(filepath)
    return f"{VIDEO_SERVER_URL}/{filename}"


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available MCP tools."""
    return [
        Tool(
            name="search_and_play_video",
            description="Search for a video clip matching a description and play it on TV. Returns the clip that was played.",
            inputSchema={
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Semantic description of the desired scene/emotion/action (e.g., 'a futuristic city', 'person looking worried')",
                    },
                    "limit": {
                        "type": "number",
                        "description": f"Number of results to consider (default: {settings.default_search_limit})",
                        "default": settings.default_search_limit,
                    },
                },
                "required": ["description"],
            },
        ),
        Tool(
            name="stop_video",
            description="Stop the currently playing video.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="search_video_clips",
            description="Search for video clips matching a description WITHOUT playing them. Returns multiple options for the LLM to choose from.",
            inputSchema={
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Semantic description of desired scene/emotion/action",
                    },
                    "limit": {
                        "type": "number",
                        "description": f"Maximum number of results (default: {settings.default_search_limit})",
                        "default": settings.default_search_limit,
                    },
                },
                "required": ["description"],
            },
        ),
        Tool(
            name="play_video_by_params",
            description="Play a specific video clip using exact parameters. Use this AFTER analyzing options from search_video_clips.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_id": {
                        "type": "number",
                        "description": "Video ID from the database",
                    },
                    "file": {
                        "type": "string",
                        "description": "Video URL or filename",
                    },
                    "start": {
                        "type": "number",
                        "description": "Start time in seconds",
                    },
                    "end": {
                        "type": "number",
                        "description": "End time in seconds",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Explain why you chose this video over the other options",
                    },
                },
                "required": ["file", "start", "end"],
            },
        ),
        Tool(
            name="get_api_status",
            description="Returns status and statistics from the GoodCLIPS API.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool calls."""

    if name == "search_and_play_video":
        description = arguments.get("description")
        limit = arguments.get("limit", settings.default_search_limit)

        # Search GoodCLIPS for matching scenes
        results = await search_goodclips(description, limit)

        if not results:
            return [
                TextContent(
                    type="text",
                    text=f"❌ No video clips found matching: '{description}'\n"
                         "The database may be empty or not yet indexed."
                )
            ]

        # Get the best match (first result)
        best = results[0]
        scene = best.get("scene", {})
        distance = best.get("distance", 0)
        similarity = (1 - distance) * 100 if distance else 0

        # Get video info to find filepath
        video_info = await get_video_info(scene.get("video_id"))
        if not video_info:
            return [
                TextContent(
                    type="text",
                    text=f"❌ Could not find video info for video_id: {scene.get('video_id')}"
                )
            ]

        # Build video URL
        video_url = build_video_url(video_info.get("filepath", ""))
        start_time = scene.get("start_time", 0)
        end_time = scene.get("end_time", 0)

        # Call HTTP playback service
        try:
            response = await http_client.post(
                f"{PLAYBACK_SERVICE_URL}/play",
                json={
                    "video_path": video_url,
                    "start": start_time,
                    "end": end_time,
                    "fullscreen": True
                }
            )

            if response.status_code == 200:
                result = response.json()
                return [
                    TextContent(
                        type="text",
                        text=f"✅ Playing clip from: {video_info.get('title', 'Unknown')}\n"
                             f"Scene: {scene.get('scene_index', 0)}\n"
                             f"Time: {start_time:.1f}s - {end_time:.1f}s\n"
                             f"Duration: {end_time - start_time:.1f}s\n"
                             f"Similarity: {similarity:.1f}%\n"
                             f"Query: '{description}'\n"
                             f"PID: {result.get('pid')}"
                    )
                ]
            else:
                error_msg = response.json().get('message', 'Unknown error')
                return [
                    TextContent(
                        type="text",
                        text=f"❌ Failed to play video: {error_msg}"
                    )
                ]

        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=f"❌ Error calling playback service: {str(e)}\n"
                         f"Make sure video_playback_service.py is running on port 5000"
                )
            ]

    elif name == "stop_video":
        try:
            response = await http_client.post(f"{PLAYBACK_SERVICE_URL}/stop")
            return [TextContent(type="text", text="✅ Video playback stopped")]
        except Exception as e:
            return [TextContent(type="text", text=f"❌ Error stopping video: {str(e)}")]

    elif name == "search_video_clips":
        description = arguments.get("description")
        limit = arguments.get("limit", settings.default_search_limit)

        # Search GoodCLIPS for matching scenes
        results = await search_goodclips(description, limit)

        if not results:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "query": description,
                        "count": 0,
                        "videos": [],
                        "message": "No clips found. Database may be empty."
                    }, indent=2)
                )
            ]

        # Build response with video details
        videos = []
        for i, result in enumerate(results, 1):
            scene = result.get("scene", {})
            distance = result.get("distance", 0)
            similarity = (1 - distance) * 100 if distance else 0

            # Get video info
            video_info = await get_video_info(scene.get("video_id"))
            video_url = build_video_url(video_info.get("filepath", "")) if video_info else ""

            # Fetch caption (visual description) directly from database
            scene_id = scene.get("id")
            caption = await get_caption_for_scene(scene_id) if scene_id else ""
            videos.append({
                "rank": i,
                "video_id": scene.get("video_id"),
                "scene_index": scene.get("scene_index"),
                "file": video_url,
                "start": scene.get("start_time", 0),
                "end": scene.get("end_time", 0),
                "duration": scene.get("end_time", 0) - scene.get("start_time", 0),
                "similarity": f"{similarity:.1f}%",
                "title": video_info.get("title", "Unknown") if video_info else "Unknown",
                "caption": caption,
                "description": caption  # Include as 'description' for handler compatibility
            })

        response_data = {
            "query": description,
            "count": len(videos),
            "videos": videos
        }

        return [TextContent(type="text", text=json.dumps(response_data, indent=2))]

    elif name == "play_video_by_params":
        file = arguments.get("file")
        start = arguments.get("start")
        end = arguments.get("end")
        video_id = arguments.get("video_id")
        reasoning = arguments.get("reasoning", "")

        # Fetch caption for this scene if we have video_id and can find scene
        caption = ""
        if video_id:
            try:
                # Try to get caption from the scene
                pool = await get_db_pool()
                async with pool.acquire() as conn:
                    # Find scene by video_id and time range
                    row = await conn.fetchrow(
                        """SELECT c.text FROM captions c
                           JOIN scenes s ON c.scene_id = s.id
                           WHERE s.video_id = $1 AND s.start_time = $2
                           LIMIT 1""",
                        video_id, start
                    )
                    if row:
                        caption = row['text']
            except Exception as e:
                print(f"Error fetching caption: {e}", file=__import__('sys').stderr)

        # Return success - the cinema_script handler will send RTVI to Pi
        response_data = {
            "status": "success",
            "video_played": {
                "file": file,
                "start": start,
                "end": end,
                "duration": end - start,
                "video_id": video_id,
                "reasoning": reasoning,
                "description": caption,
                "caption": caption
            }
        }
        return [TextContent(type="text", text=json.dumps(response_data, indent=2))]

    elif name == "deprecated_play_video_by_params_with_service":
        # Old code that called playback service - kept for reference
        file = arguments.get("file")
        start = arguments.get("start")
        end = arguments.get("end")
        video_id = arguments.get("video_id")
        reasoning = arguments.get("reasoning", "")

        # Call playback service
        try:
            response = await http_client.post(
                f"{PLAYBACK_SERVICE_URL}/play",
                json={
                    "video_path": file,
                    "start": start,
                    "end": end,
                    "fullscreen": True
                }
            )

            if response.status_code == 200:
                result = response.json()
                response_data = {
                    "status": "success",
                    "video_played": {
                        "file": file,
                        "start": start,
                        "end": end,
                        "duration": end - start,
                        "video_id": video_id,
                        "reasoning": reasoning,
                        "pid": result.get("pid")
                    }
                }
                return [TextContent(type="text", text=json.dumps(response_data, indent=2))]
            else:
                error_msg = response.json().get('message', 'Unknown error')
                return [
                    TextContent(
                        type="text",
                        text=f"❌ Failed to play video: {error_msg}"
                    )
                ]
        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=f"❌ Error calling playback service: {str(e)}"
                )
            ]

    elif name == "get_api_status":
        stats = await get_api_stats()

        if "error" in stats:
            return [
                TextContent(
                    type="text",
                    text=f"❌ GoodCLIPS API Error: {stats['error']}\n"
                         f"API URL: {GOODCLIPS_API_URL}"
                )
            ]

        return [
            TextContent(
                type="text",
                text=f"✅ GoodCLIPS API Status\n\n"
                     f"API URL: {GOODCLIPS_API_URL}\n"
                     f"Video Server: {VIDEO_SERVER_URL}\n\n"
                     f"Database Stats:\n"
                     f"  Total Videos: {stats.get('total_videos', 0)}\n"
                     f"  Completed Videos: {stats.get('completed_videos', 0)}\n"
                     f"  Total Scenes: {stats.get('total_scenes', 0)}\n"
                     f"  Scenes with Embeddings: {stats.get('scenes_with_embeddings', 0)}\n"
                     f"  Total Captions: {stats.get('total_captions', 0)}\n"
                     f"  Total Duration: {stats.get('total_duration_seconds', 0):.1f}s\n"
                     f"  Active Jobs: {stats.get('active_jobs', 0)}"
            )
        ]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    """Run the MCP server."""
    import sys

    # Print startup info to stderr (stdout is for MCP JSON-RPC)
    print("🎬 Starting Cinema-Chat MCP Server...", file=sys.stderr, flush=True)
    print(f"📡 GoodCLIPS API: {GOODCLIPS_API_URL}", file=sys.stderr, flush=True)
    print(f"📺 Video Server: {VIDEO_SERVER_URL}", file=sys.stderr, flush=True)
    print(f"🎥 Playback Service: {PLAYBACK_SERVICE_URL}", file=sys.stderr, flush=True)

    # Test API connection
    try:
        stats = await get_api_stats()
        if "error" not in stats:
            print(f"✅ Connected to GoodCLIPS API", file=sys.stderr, flush=True)
            print(f"   Videos: {stats.get('total_videos', 0)}, Scenes: {stats.get('total_scenes', 0)}", file=sys.stderr, flush=True)
        else:
            print(f"⚠️  GoodCLIPS API error: {stats.get('error')}", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"⚠️  Could not connect to GoodCLIPS API: {e}", file=sys.stderr, flush=True)

    print("", file=sys.stderr, flush=True)

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="cinema-chat-mcp",
                server_version="0.2.0",
                capabilities=app.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
