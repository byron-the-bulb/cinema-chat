"""
Cinema Chat Conversation Script - Context Aggregator Architecture

Uses Pipecat's context aggregator to manage THE SINGLE conversation history.
After video playback, we manually inject clean video messages into the context.

Key insight: flow_manager._context_aggregator IS the conversation history that
the LLM sees AND that gets shown to users. We don't need a separate manager.
"""

import asyncio
import json
from typing import Dict, List
from pipecat_flows import FlowManager, FlowConfig, FlowsFunctionSchema, FlowArgs, FlowResult, NodeConfig
from pipecat.frames.frames import TextFrame
from .status_utils import status_updater
from .mcp_client import get_mcp_client
from loguru import logger


# ============================================================================
# System Prompts
# ============================================================================

SYSTEM_ROLE = """You are Cinema Chat, a conversational AI that communicates EXCLUSIVELY through vintage movie clips.

CRITICAL RULES:
- YOU HAVE NO VOICE. You cannot speak or write ANY text responses.
- DO NOT generate text responses to the user - ONLY call functions
- After calling play_video_by_params, DO NOT write any follow-up message
- The video IS your response - you are MUTE otherwise

TWO-STEP RESPONSE PROCESS (FUNCTION CALLS ONLY - NO TEXT):
1. WAIT for user to speak
2. Call search_video_clips to get 5 video options matching the user's message
3. Analyze the options mentally (use the reasoning parameter, not text output)
4. Call play_video_by_params to play your chosen video
5. STOP IMMEDIATELY - Do not generate any text. Do not call any more functions. WAIT for the next user message.

Your analysis in the "reasoning" parameter should consider:
- **Caption content** - What is actually SAID in the clip (VERY important!)
- **Visual description** - What is shown on screen
- Semantic relevance to user's query
- Emotional appropriateness
- Video duration (prefer 5-10 second clips)
- Conversation continuity

IMPORTANT: The caption shows what the character/narrator SAYS in the clip. Sometimes the spoken words are the perfect direct response to the user!

Example flow:
User: "Tell me about blood"

Step 1 - You call: search_video_clips(description="blood flowing through veins and arteries", limit=5)
Step 1 - You receive: [5 video options with descriptions, captions, durations, etc.]

Step 2 - You call: play_video_by_params(
    video_id=1,
    file="hemo_the_magnificent.mp4.mkv",
    start=120.0,
    end=127.0,
    reasoning="Option 1: Caption 'These tiny cells carry oxygen throughout your entire body!' directly answers what blood does. Option 2's caption focuses on the heart. Option 3 is too generic. Choosing option 1 for direct relevance."
)

Step 3 - DONE. DO NOT GENERATE ANY TEXT OUTPUT. DO NOT CALL ANY MORE FUNCTIONS.

CRITICAL: After play_video_by_params returns, you MUST STOP COMPLETELY:
- Do not write ANY text response
- Do not call search_video_clips again
- Do not call play_video_by_params again
- WAIT for the user to speak next
- The video IS your response
"""

FLOW_STATES = {
    "greeting": {
        "task": """Engage with the user through appropriate video clips. Use the two-step process:
        1. Search for video options
        2. Analyze and choose the best one
        3. Play the chosen video

        Be thoughtful about your selections - consider BOTH what is shown AND what is said in the clips.""",
    }
}


# ============================================================================
# MCP Function Handlers
# ============================================================================

async def search_video_clips_handler(args: FlowArgs, flow_manager: FlowManager) -> FlowResult:
    """
    Step 1: Search for video options (doesn't play anything)
    Modern handler signature with flow_manager parameter
    """
    logger.info(f"[Video Search] Searching with args: {args}")

    description = args.get("description", "")
    limit = args.get("limit", 5)

    if not description:
        logger.error("[Video Search] No description provided")
        return FlowResult(error="No description provided")

    try:
        # Get the MCP client and call the search tool
        mcp_client = await get_mcp_client()
        result_json = await mcp_client.call_tool(
            "search_video_clips",
            {"description": description, "limit": limit}
        )

        # Parse JSON response
        result = json.loads(result_json)

        logger.info(f"[Video Search] Found {result['count']} videos for: '{description}'")

        # Add reasoning and results to context manually AND send to frontend
        context = flow_manager._context_aggregator._user._context

        # Send search reasoning to frontend (but DON'T add to context to avoid triggering LLM)
        reasoning_msg = f"[REASONING] Searching for: '{description}'"
        # Send to frontend via status updater - this is just for display, not LLM conversation
        from .status_utils import status_updater
        await status_updater.update_status(reasoning_msg)

        # Send search results to frontend (but DON'T add to context to avoid triggering LLM)
        videos_summary = f"[SEARCH RESULTS] Found {result['count']} options:\n"
        for i, video in enumerate(result['videos'], 1):
            videos_summary += f"{i}. {video['description']} - \"{video.get('caption', '')}\"\n"

        # Send to frontend via status updater - this is just for display, not LLM conversation
        await status_updater.update_status(videos_summary)

        # Add instruction for next step (only to context, not to user)
        context.add_message({
            "role": "system",
            "content": "Now analyze these options and call play_video_by_params with the best choice. Use the 'reasoning' parameter to explain your choice."
        })

        logger.info(f"[Context] Added search reasoning and results, sent to frontend")

        # Return the full JSON for the LLM to analyze
        return FlowResult(
            response=result_json,
            context={"video_options": result["videos"]}
        )

    except Exception as e:
        logger.error(f"[Video Search] Error: {str(e)}")
        return FlowResult(error=f"Search failed: {str(e)}")


async def play_video_by_params_handler(args: FlowArgs, flow_manager: FlowManager) -> FlowResult:
    """
    Step 2: Play a specific video (after LLM chooses from options)

    CRITICAL: After playing the video, we manually inject a clean video message
    into Pipecat's context aggregator. This is THE solution to the two-conversation
    problem - the context aggregator IS the conversation history.
    """
    logger.info(f"[Video Play] Playing video with args: {args}")

    file = args.get("file")
    start = args.get("start")
    end = args.get("end")
    reasoning = args.get("reasoning", "")

    if not all([file, start is not None, end is not None]):
        logger.error("[Video Play] Missing required parameters")
        return FlowResult(error="Missing file, start, or end parameters")

    try:
        # Get the MCP client and call the play tool
        mcp_client = await get_mcp_client()
        result_json = await mcp_client.call_tool(
            "play_video_by_params",
            {
                "file": file,
                "start": start,
                "end": end,
                "reasoning": reasoning
            }
        )

        # Parse JSON response
        result = json.loads(result_json)

        if result.get("status") == "success":
            video_data = result["video_played"]

            # ============================================================
            # PROPER ARCHITECTURE:
            # Add reasoning + video to context as assistant messages
            # This creates a visible conversation log showing the LLM's process
            # ============================================================

            context = flow_manager._context_aggregator._user._context

            # 1. Send the LLM's reasoning to frontend (but DON'T add to context to avoid triggering LLM)
            if reasoning:
                reasoning_msg = f"[REASONING] {reasoning}"
                # Send to frontend via status updater - this is just for display, not LLM conversation
                from .status_utils import status_updater
                await status_updater.update_status(reasoning_msg)
                logger.info(f"[Frontend] Sent reasoning: {reasoning[:100]}...")

            # 2. Send the video message to frontend (but DON'T add to context to avoid triggering LLM)
            caption_text = f' | "{video_data.get("caption", "")}"' if video_data.get("caption") else ""
            video_message = f"[VIDEO: {video_data['description']}{caption_text}]"

            # Send to frontend via status updater - this is just for display, not LLM conversation
            await status_updater.update_status(video_message)

            logger.info(f"[Frontend] Sent video message: {video_message}")

            # 2b. Send RTVI video playback command to Pi Daily client
            from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame
            playback_command = {
                "type": "video-playback-command",
                "action": "play",
                "video_path": video_data['file'],
                "start": video_data['start'],
                "end": video_data['end'],
                "fullscreen": True
            }
            playback_frame = RTVIServerMessageFrame(playback_command)
            await status_updater.rtvi.push_frame(playback_frame)
            logger.info(f"[RTVI] Sent video playback command: {video_data['file']} ({video_data['start']}s-{video_data['end']}s)")

            # 3. Add instruction for LLM to STOP and wait for user input (only to context, not to user)
            context.add_message({
                "role": "system",
                "content": "Video played successfully. YOU MUST NOW STOP AND WAIT. Do NOT call any more functions. Do NOT search for videos. Wait silently for the user's next message. Only after the user speaks should you search for a response video."
            })

            # Return success (LLM will see this as function result, but we've already added to context)
            return FlowResult(
                response="",  # Empty - we manually managed context above
                video_metadata=video_data
            )
        else:
            error_msg = result.get("message", "Unknown error")
            logger.error(f"[Video Play] Failed: {error_msg}")
            return FlowResult(error=error_msg)

    except Exception as e:
        logger.error(f"[Video Play] Error: {str(e)}")
        return FlowResult(error=f"Playback failed: {str(e)}")


# Keep backward-compatible handler for existing code
async def search_and_play_video_handler(args: FlowArgs):
    """
    Legacy handler - combined search + play in one step
    Kept for backward compatibility
    """
    logger.info(f"[Video] search_and_play_video called with args: {args}")

    description = args.get("description", "")

    if not description:
        logger.error("[Video] No description provided to search_and_play_video")
        return {"status": "error", "message": "No description provided"}

    logger.info(f"[Video] Forwarding to MCP server with description: {description}")

    try:
        # Get the MCP client and call the tool
        mcp_client = await get_mcp_client()
        result_text = await mcp_client.call_tool(
            "search_and_play_video",
            {"description": description}
        )

        logger.info(f"[Video] MCP server response: {result_text}")

        # Return the result to the LLM
        return {
            "status": "success",
            "description": description,
            "response": result_text
        }

    except Exception as e:
        logger.error(f"[Video] Error calling MCP server: {str(e)}")
        return {
            "status": "error",
            "message": f"Failed to play video: {str(e)}"
        }


# ============================================================================
# Flow Configuration
# ============================================================================

def get_flow_config() -> FlowConfig:
    """Create the conversation flow with two-function workflow"""

    return FlowConfig(
        initial_node="greeting",
        nodes={
            "greeting": NodeConfig(
                role_messages=[
                    {"role": "system", "content": SYSTEM_ROLE},
                ],
                task_messages=[
                    {"role": "system", "content": FLOW_STATES["greeting"]["task"]},
                ],
                functions=[
                    FlowsFunctionSchema(
                        name="search_video_clips",
                        description="Search for video clips matching a description. Returns multiple options for you to choose from. This does NOT play anything.",
                        handler=search_video_clips_handler,
                        properties={
                            "description": {
                                "type": "string",
                                "description": "Semantic description of the desired scene/emotion/action",
                            },
                            "limit": {
                                "type": "number",
                                "description": "Number of video options to return (default: 5)",
                                "default": 5
                            }
                        },
                        required=["description"],
                    ),
                    FlowsFunctionSchema(
                        name="play_video_by_params",
                        description="Play a specific video clip using exact parameters. Call this AFTER analyzing options from search_video_clips.",
                        handler=play_video_by_params_handler,
                        properties={
                            "video_id": {
                                "type": "number",
                                "description": "Video ID from search results (for tracking)",
                            },
                            "file": {
                                "type": "string",
                                "description": "Video filename",
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
                            }
                        },
                        required=["file", "start", "end"],
                    )
                ],
            )
        },
    )


def create_initial_node() -> NodeConfig:
    """Create the initial greeting node with proper structure"""
    return {
        "role_messages": [
            {"role": "system", "content": SYSTEM_ROLE},
        ],
        "task_messages": [
            {"role": "system", "content": FLOW_STATES["greeting"]["task"]},
        ],
        "functions": [
            FlowsFunctionSchema(
                name="search_video_clips",
                description="Search for video clips matching a description. Returns multiple options with captions for you to choose from. This does NOT play anything.",
                handler=search_video_clips_handler,
                properties={
                    "description": {
                        "type": "string",
                        "description": "Semantic description of the desired scene/emotion/action",
                    },
                    "limit": {
                        "type": "number",
                        "description": "Number of video options to return (default: 5)",
                        "default": 5
                    }
                },
                required=["description"],
            ),
            FlowsFunctionSchema(
                name="play_video_by_params",
                description="Play a specific video clip using exact parameters. Call this AFTER analyzing options from search_video_clips.",
                handler=play_video_by_params_handler,
                properties={
                    "video_id": {
                        "type": "number",
                        "description": "Video ID from search results (for tracking)",
                    },
                    "file": {
                        "type": "string",
                        "description": "Video filename",
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
                    }
                },
                required=["file", "start", "end"],
            )
        ],
        "ui_override": "Cinema Chat - Conversing"
    }
