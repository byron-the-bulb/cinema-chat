"""Cinema-Chat MCP Server - Video search and playback for conversational AI."""
import asyncio
import logging
from typing import Any
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from config import settings
from goodclips_client import GoodCLIPSClient, SceneResult
from video_player import VideoPlayer

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize server
app = Server(settings.server_name)

# Global instances
goodclips_client: GoodCLIPSClient | None = None
video_player: VideoPlayer | None = None


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available MCP tools."""
    return [
        Tool(
            name="search_and_play_video",
            description="""Search for a video clip matching a semantic description and play it.

This is the primary tool for the bot to "respond" to the user through video.
Instead of generating text to speak, describe the visual scene, emotion, or action
you want to show. The system will find and play a matching movie clip.

Examples:
- "a person nodding in agreement"
- "someone looking confused and scratching their head"
- "a character smiling warmly"
- "a dramatic sunset over the ocean"
- "someone waving goodbye"

The video will play on the TV and the conversation will wait for the user's next response.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Semantic description of the scene/emotion/action to search for"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of results to consider (default: 5, will play best match)",
                        "default": settings.default_search_limit
                    }
                },
                "required": ["description"]
            }
        ),
        Tool(
            name="stop_video",
            description="Stop the currently playing video clip. Use this if you need to interrupt playback.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="search_video_clips",
            description="""Search for video clips matching a description WITHOUT playing them.

Use this when you want to explore what clips are available before deciding which to play.
Returns a list of matching scenes with their details.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Semantic description to search for"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return",
                        "default": settings.default_search_limit
                    }
                },
                "required": ["description"]
            }
        ),
        Tool(
            name="get_api_stats",
            description="Get statistics about the video database (number of videos, scenes, etc.)",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool calls."""
    global goodclips_client, video_player

    try:
        if name == "search_and_play_video":
            description = arguments.get("description")
            limit = arguments.get("limit", settings.default_search_limit)

            if not description:
                return [TextContent(
                    type="text",
                    text="Error: description is required"
                )]

            # Clamp limit
            limit = min(limit, settings.max_search_limit)

            logger.info(f"Tool call: search_and_play_video('{description}', limit={limit})")

            # Search for matching scenes
            scenes = await goodclips_client.search_semantic(
                query=description,
                limit=limit
            )

            if not scenes:
                return [TextContent(
                    type="text",
                    text=f"No video clips found matching: '{description}'"
                )]

            # Get the best match (first result)
            best_scene = scenes[0]

            # Get video file path
            video_path = await goodclips_client.get_video_path(best_scene.video_id)

            if not video_path:
                return [TextContent(
                    type="text",
                    text=f"Error: Could not find video file for scene {best_scene.id}"
                )]

            # Play the clip
            success = await video_player.play_clip(
                video_path=video_path,
                start_time=best_scene.start_time,
                end_time=best_scene.end_time,
                fullscreen=True
            )

            if success:
                result_text = f"""Playing video clip:
- Description match: "{description}"
- Video ID: {best_scene.video_id}
- Scene: {best_scene.scene_index}
- Duration: {best_scene.duration:.1f}s
- Similarity: {1 - best_scene.distance:.2%}

The video is now playing on the TV. Wait for user response."""

                # If there were other good matches, mention them
                if len(scenes) > 1:
                    result_text += f"\n\nOther matches found: {len(scenes) - 1}"

                return [TextContent(type="text", text=result_text)]
            else:
                return [TextContent(
                    type="text",
                    text=f"Error: Failed to play video clip"
                )]

        elif name == "stop_video":
            logger.info("Tool call: stop_video()")

            if video_player.is_playing():
                await video_player.stop()
                return [TextContent(
                    type="text",
                    text="Video playback stopped"
                )]
            else:
                return [TextContent(
                    type="text",
                    text="No video is currently playing"
                )]

        elif name == "search_video_clips":
            description = arguments.get("description")
            limit = arguments.get("limit", settings.default_search_limit)

            if not description:
                return [TextContent(
                    type="text",
                    text="Error: description is required"
                )]

            limit = min(limit, settings.max_search_limit)

            logger.info(f"Tool call: search_video_clips('{description}', limit={limit})")

            scenes = await goodclips_client.search_semantic(
                query=description,
                limit=limit
            )

            if not scenes:
                return [TextContent(
                    type="text",
                    text=f"No clips found matching: '{description}'"
                )]

            # Format results
            results_text = f"Found {len(scenes)} clips matching '{description}':\n\n"
            for i, scene in enumerate(scenes, 1):
                similarity = (1 - scene.distance) * 100
                results_text += f"{i}. Video {scene.video_id}, Scene {scene.scene_index}\n"
                results_text += f"   Duration: {scene.duration:.1f}s, Similarity: {similarity:.1f}%\n"

            return [TextContent(type="text", text=results_text)]

        elif name == "get_api_stats":
            logger.info("Tool call: get_api_stats()")

            stats = await goodclips_client.get_stats()

            stats_text = "GoodCLIPS Database Statistics:\n\n"
            for key, value in stats.items():
                stats_text += f"- {key}: {value}\n"

            return [TextContent(type="text", text=stats_text)]

        else:
            return [TextContent(
                type="text",
                text=f"Unknown tool: {name}"
            )]

    except Exception as e:
        logger.error(f"Error in tool call {name}: {e}", exc_info=True)
        return [TextContent(
            type="text",
            text=f"Error: {str(e)}"
        )]


async def main():
    """Main entry point for MCP server."""
    global goodclips_client, video_player

    logger.info(f"Starting {settings.server_name} v{settings.server_version}")
    logger.info(f"GoodCLIPS API: {settings.goodclips_api_url}")
    logger.info(f"Videos path: {settings.videos_path}")

    # Initialize clients
    goodclips_client = GoodCLIPSClient(
        base_url=settings.goodclips_api_url,
        api_key=settings.goodclips_api_key
    )

    video_player = VideoPlayer(
        output_device=settings.video_output_device
    )

    # Test connection to GoodCLIPS
    try:
        stats = await goodclips_client.get_stats()
        logger.info(f"✅ Connected to GoodCLIPS: {stats}")
    except Exception as e:
        logger.error(f"⚠️  Failed to connect to GoodCLIPS: {e}")
        logger.error("Server will start but tools may fail until API is available")

    # Run MCP server
    async with stdio_server() as (read_stream, write_stream):
        logger.info("MCP server ready")
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    finally:
        if video_player:
            video_player.cleanup()
        if goodclips_client:
            asyncio.run(goodclips_client.close())
