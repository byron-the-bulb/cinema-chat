#!/usr/bin/env python3
"""
Mock MCP Server for Cinema-Chat

This is a simplified version that works WITHOUT the GoodCLIPS API.
It uses hardcoded scene mappings to allow testing the voice bot integration
while we wait for the API to be ready.

Usage:
    python mock_server.py
"""

import asyncio
import random
import httpx
from typing import Any
from mcp.server.models import InitializationOptions
from mcp.server import Server, NotificationOptions
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from config import Settings

# HTTP Video Playback Service URL
PLAYBACK_SERVICE_URL = "http://localhost:5000"

# Base path for videos
import os
VIDEO_BASE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "videos")

# Hardcoded scene library for testing
# Format: keyword -> (video_filename, start_time, end_time, description, caption)
# Caption = what is actually SAID in the clip (important for semantic matching!)
MOCK_SCENES = {
    # Blood/circulation related
    "blood": ("hemo_the_magnificent.mp4.mkv", 120.0, 127.0, "Blood cells flowing through vessels", "Hey, you guys are people! Fellas, Everybody, we got people!"),
    "heart": ("hemo_the_magnificent.mp4.mkv", 450.0, 458.0, "Heart beating and pumping blood", "Without my delicate machinery of circulation I build for you"),
    "circulation": ("hemo_the_magnificent.mp4.mkv", 890.0, 898.0, "Circulatory system overview", "Your blood travels through thousands of miles of vessels."),
    "flow": ("hemo_the_magnificent.mp4.mkv", 1200.0, 1208.0, "Blood flowing through arteries", "Watch how the blood flows smoothly through these passages."),

    # Senses related
    "eye": ("gateway_to_the_mind.mp4.mkv", 200.0, 208.0, "How the eye works", "The eye is like a camera, capturing light and sending signals to the brain."),
    "vision": ("gateway_to_the_mind.mp4.mkv", 350.0, 358.0, "Visual perception", "Everything you see is processed by your amazing visual cortex."),
    "sense": ("gateway_to_the_mind.mp4.mkv", 50.0, 58.0, "Introduction to human senses", "Your senses are the gateways to understanding the world."),
    "brain": ("gateway_to_the_mind.mp4.mkv", 600.0, 608.0, "Brain processing information", "The brain processes millions of signals every second."),

    # Posture/body
    "posture": ("your_posture_1953.mp4.mkv", 100.0, 108.0, "Good posture demonstration", "Stand tall with your shoulders back and head held high."),
    "spine": ("your_posture_1953.mp4.mkv", 250.0, 258.0, "Spinal alignment", "Your spine is the central support for your entire body."),
    "body": ("your_posture_1953.mp4.mkv", 50.0, 58.0, "Human body structure", "The human body is a magnificent machine."),

    # Generic fallbacks
    "yes": ("hemo_the_magnificent.mp4.mkv", 10.0, 15.0, "Nodding/agreement gesture", "Yes, that's absolutely correct!"),
    "no": ("gateway_to_the_mind.mp4.mkv", 30.0, 35.0, "Shaking head/disagreement", "No, that's not quite right."),
    "think": ("gateway_to_the_mind.mp4.mkv", 400.0, 406.0, "Person thinking/contemplating", "Let me think about that for a moment..."),
    "hello": ("hemo_the_magnificent.mp4.mkv", 0.0, 8.0, "Opening scene greeting", "The Bell telephone system bring you another in its series of programs on science!"),
}

# Default fallback scenes
DEFAULT_SCENES = [
    ("hemo_the_magnificent.mp4.mkv", 500.0, 508.0, "Generic blood scene", "Now I place 2 side by side like so... now I take right burb into left burb so... and right tube into left burb so"),
    ("gateway_to_the_mind.mp4.mkv", 100.0, 108.0, "Generic mind scene", "We will give you a big and some chickens. Now I wonder which one you value the most"),
]

app = Server("cinema-chat-mock")
settings = Settings()
http_client = httpx.AsyncClient()


def find_best_scene(description: str) -> tuple[str, float, float, str, str]:
    """
    Find the best matching scene for a description.
    Uses simple keyword matching on the mock scene library.
    Returns: (video_filename, start_time, end_time, description, caption)
    """
    description_lower = description.lower()

    # Try to find keyword matches
    for keyword, scene_data in MOCK_SCENES.items():
        if keyword in description_lower:
            return scene_data

    # No match found, return a random default
    return random.choice(DEFAULT_SCENES)


def find_matching_scenes(description: str, limit: int = 5) -> list[tuple[str, float, float, str, str]]:
    """
    Find multiple matching scenes for a description.
    Uses simple keyword matching on the mock scene library.
    Returns list of: (video_filename, start_time, end_time, description, caption)
    """
    description_lower = description.lower()
    matches = []

    # Try to find keyword matches
    for keyword, scene_data in MOCK_SCENES.items():
        if keyword in description_lower:
            matches.append(scene_data)
            if len(matches) >= limit:
                break

    # If we don't have enough matches, add some defaults
    # But don't loop forever - only try as many times as we have defaults
    target_count = min(limit, 3)
    attempts = 0
    max_attempts = len(DEFAULT_SCENES) * 2  # Allow some retries for duplicates

    while len(matches) < target_count and attempts < max_attempts:
        default = random.choice(DEFAULT_SCENES)
        if default not in matches:
            matches.append(default)
        attempts += 1

    return matches[:limit]


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
                        "description": "Semantic description of the desired scene/emotion/action (e.g., 'blood flowing through veins', 'person nodding in agreement')",
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
            description="Search for video clips matching a description WITHOUT playing them. Returns multiple options with descriptions and captions for the LLM to choose from.",
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
                        "description": "Video ID from search results (optional, for tracking)",
                    },
                    "file": {
                        "type": "string",
                        "description": "Video filename (e.g., 'hemo_the_magnificent.mp4.mkv')",
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
            name="get_mock_status",
            description="Returns status indicating this is a mock server for testing.",
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

        # Find best matching scene
        filename, start_time, end_time, scene_desc, caption = find_best_scene(description)

        # Call HTTP playback service
        try:
            response = await http_client.post(
                f"{PLAYBACK_SERVICE_URL}/play",
                json={
                    "video_path": filename,  # Just filename, service will add base path
                    "start": start_time,
                    "end": end_time,
                    "fullscreen": True  # Fullscreen for installation
                }
            )

            if response.status_code == 200:
                result = response.json()
                return [
                    TextContent(
                        type="text",
                        text=f"✅ Playing clip: {scene_desc}\n"
                             f"Caption: \"{caption}\"\n"
                             f"Duration: {end_time - start_time:.1f}s\n"
                             f"Query: '{description}'\n"
                             f"PID: {result.get('pid')}\n"
                             f"[MOCK MODE - Using keyword matching]"
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

        # Find multiple matching scenes
        scenes = find_matching_scenes(description, limit)

        # Build JSON response with captions
        import json
        videos = []
        for i, (filename, start_time, end_time, scene_desc, caption) in enumerate(scenes, 1):
            videos.append({
                "video_id": i,
                "file": filename,
                "start": start_time,
                "end": end_time,
                "duration": end_time - start_time,
                "description": scene_desc,
                "caption": caption,
                "keywords": [k for k, v in MOCK_SCENES.items() if v == (filename, start_time, end_time, scene_desc, caption)]
            })

        result = {
            "query": description,
            "count": len(videos),
            "videos": videos,
            "mock_mode": True
        }

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "play_video_by_params":
        import json
        file = arguments.get("file")
        start = arguments.get("start")
        end = arguments.get("end")
        video_id = arguments.get("video_id")
        reasoning = arguments.get("reasoning", "")

        # Find description and caption from MOCK_SCENES
        description = "Video clip"
        caption = ""

        # First check MOCK_SCENES (keyword-based scenes)
        for keyword, scene_data in MOCK_SCENES.items():
            if scene_data[0] == file and scene_data[1] == start:
                description = scene_data[3]
                caption = scene_data[4] if len(scene_data) > 4 else ""
                break

        # If not found, check DEFAULT_SCENES (fallback scenes)
        if description == "Video clip":
            for scene_data in DEFAULT_SCENES:
                if scene_data[0] == file and scene_data[1] == start:
                    description = scene_data[2]
                    caption = scene_data[3] if len(scene_data) > 3 else ""
                    break

        # Call HTTP playback service
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

                # Return JSON with video metadata
                response_data = {
                    "status": "success",
                    "video_played": {
                        "file": file,
                        "start": start,
                        "end": end,
                        "duration": end - start,
                        "description": description,
                        "caption": caption,
                        "pid": result.get("pid"),
                        "reasoning": reasoning
                    }
                }

                return [TextContent(type="text", text=json.dumps(response_data, indent=2))]
            else:
                error_msg = response.json().get('message', 'Unknown error')
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({
                            "status": "error",
                            "message": f"Failed to play video: {error_msg}"
                        })
                    )
                ]

        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=json.dumps({
                        "status": "error",
                        "message": f"Error calling playback service: {str(e)}"
                    })
                )
            ]

    elif name == "get_mock_status":
        return [
            TextContent(
                type="text",
                text="⚠️ MOCK MCP SERVER\n\n"
                     f"Available keywords: {', '.join(sorted(MOCK_SCENES.keys()))}\n\n"
                     "This server uses simple keyword matching until GoodCLIPS API is ready.\n"
                     "Switch to server.py once semantic search is implemented."
            )
        ]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    """Run the mock MCP server."""
    import sys
    # Print to stderr to avoid interfering with MCP JSON-RPC on stdout
    print("🎬 Starting Cinema-Chat Mock MCP Server...", file=sys.stderr, flush=True)
    print(f"📁 Videos path: {settings.videos_path}", file=sys.stderr, flush=True)
    print(f"⚠️  MOCK MODE - Using keyword matching", file=sys.stderr, flush=True)
    print(f"🔑 Available keywords: {', '.join(sorted(MOCK_SCENES.keys()))}", file=sys.stderr, flush=True)
    print("", file=sys.stderr, flush=True)

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="cinema-chat-mock",
                server_version="0.1.0",
                capabilities=app.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
