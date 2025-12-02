"""
MCP Video Tools for OpenAI Function Calling

Defines the search_and_play_video tool that the LLM can call,
and handles executing those calls via the MCP server.
"""

import httpx
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Video playback service URL (our HTTP service)
VIDEO_PLAYBACK_URL = "http://localhost:5000"

# MCP server URL (if we want to use full MCP protocol later)
MCP_SERVER_URL = "http://localhost:3000"

# For now, we'll use the same keyword matching as the MCP mock server
KEYWORD_CLIPS = {
    # Blood/circulation
    "blood": ("hemo_the_magnificent.mp4.mkv", 120.0, 128.0, "Blood cells flowing through vessels"),
    "heart": ("hemo_the_magnificent.mp4.mkv", 450.0, 458.0, "Heart beating and pumping blood"),
    "circulation": ("hemo_the_magnificent.mp4.mkv", 890.0, 898.0, "Circulatory system overview"),
    "flow": ("hemo_the_magnificent.mp4.mkv", 1200.0, 1208.0, "Blood flowing through arteries"),

    # Senses
    "eye": ("gateway_to_the_mind.mp4.mkv", 200.0, 208.0, "How the eye works"),
    "vision": ("gateway_to_the_mind.mp4.mkv", 350.0, 358.0, "Visual perception"),
    "sense": ("gateway_to_the_mind.mp4.mkv", 50.0, 58.0, "Introduction to human senses"),
    "brain": ("gateway_to_the_mind.mp4.mkv", 600.0, 608.0, "Brain processing information"),
    "think": ("gateway_to_the_mind.mp4.mkv", 400.0, 406.0, "Person thinking/contemplating"),

    # Body
    "body": ("your_posture_1953.mp4.mkv", 50.0, 58.0, "Human body structure"),
    "posture": ("your_posture_1953.mp4.mkv", 100.0, 108.0, "Good posture demonstration"),

    # Generic
    "yes": ("hemo_the_magnificent.mp4.mkv", 10.0, 18.0, "Nodding/agreement"),
    "hello": ("hemo_the_magnificent.mp4.mkv", 0.0, 8.0, "Opening scene greeting"),
}

# OpenAI function definition
SEARCH_AND_PLAY_VIDEO_TOOL = {
    "type": "function",
    "function": {
        "name": "search_and_play_video",
        "description": "Search for and play a video clip that matches the given description. Use this to respond to the user with a visual scene instead of speaking text. For example, if you want to show agreement, search for 'person nodding', or if discussing blood, search for 'blood flowing through veins'.",
        "parameters": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "A semantic description of the scene/emotion/action you want to show. Be specific and visual. Examples: 'blood flowing through veins', 'person thinking deeply', 'eye looking at something'"
                }
            },
            "required": ["description"]
        }
    }
}


def find_clip_for_description(description: str) -> tuple[str, float, float, str]:
    """
    Find a video clip matching the description using keyword matching.

    Args:
        description: Text description from LLM

    Returns:
        (filename, start_time, end_time, clip_description)
    """
    description_lower = description.lower()

    # Try to find keyword matches
    for keyword, clip_data in KEYWORD_CLIPS.items():
        if keyword in description_lower:
            logger.info(f"Matched keyword '{keyword}' in description: {description}")
            return clip_data

    # Default fallback
    logger.warning(f"No keyword match for: {description}, using fallback")
    return ("hemo_the_magnificent.mp4.mkv", 100.0, 108.0, "Generic scene")


async def execute_search_and_play_video(description: str) -> Dict[str, Any]:
    """
    Execute the search_and_play_video function.
    Called when LLM invokes this tool.

    Args:
        description: The description from the LLM's function call

    Returns:
        Result dict to return to the LLM
    """
    logger.info(f"LLM requested video for: {description}")

    # Find matching clip
    filename, start, end, clip_desc = find_clip_for_description(description)

    # Play the video via HTTP service
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            response = await client.post(
                f"{VIDEO_PLAYBACK_URL}/play",
                json={
                    "video_path": filename,
                    "start": start,
                    "end": end,
                    "fullscreen": False  # Set to True for production
                }
            )

            if response.status_code == 200:
                result = response.json()
                logger.info(f"Playing: {clip_desc} (PID: {result.get('pid')})")

                return {
                    "status": "playing",
                    "clip_description": clip_desc,
                    "duration": end - start,
                    "message": f"Now showing: {clip_desc}"
                }
            else:
                error = response.json().get('message', 'Unknown error')
                logger.error(f"Failed to play video: {error}")
                return {
                    "status": "error",
                    "message": f"Could not play video: {error}"
                }

        except Exception as e:
            logger.error(f"Error calling video service: {e}")
            return {
                "status": "error",
                "message": f"Video service error: {str(e)}"
            }
