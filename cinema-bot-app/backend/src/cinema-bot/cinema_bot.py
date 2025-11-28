#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import sys
import os
from loguru import logger
from dotenv import load_dotenv

# Load environment variables first
load_dotenv(override=True)

# Remove default logger
logger.remove(0)

# Add console logging
logger.add(sys.stderr, level="DEBUG")

# Import our custom CloudWatch logger and set it up
from .cloudwatch_logger import setup_cloudwatch_logging

# Setup CloudWatch logging using our separate module
setup_cloudwatch_logging()

# Now import everything else
import argparse
import asyncio
from huggingface_hub import snapshot_download

from pipecat.audio.vad.silero import SileroVADAnalyzer, VADParams
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.parallel_pipeline import ParallelPipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
#from pipecat.services.cartesia.tts import CartesiaTTSService, Language
#from pipecat.services.elevenlabs import ElevenLabsTTSService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.services.daily import DailyTransport, DailyParams
from pipecat.services.whisper.stt import WhisperSTTService, Model
from pipecat.processors.frameworks.rtvi import RTVIProcessor, RTVIConfig, RTVIObserver, RTVIMessage, RTVIAction, RTVIActionArgument,RTVIServerMessageFrame
from pipecat_flows import FlowManager
from .cinema_script import SYSTEM_ROLE, create_initial_node
from .status_utils import status_updater
from .custom_flow_manager import CustomFlowManager
from pipecat.frames.frames import BotStoppedSpeakingFrame, TranscriptionFrame, TextFrame, Frame, FunctionCallResultFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from uuid import uuid4
from pipecat.utils.time import time_now_iso8601
import json
import base64

from pipecat.transports.services.helpers.daily_rest import DailyRESTHelper, DailyRoomParams
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
# Hume observer removed - no longer needed
# STTMuteFilter removed - we want Whisper to always transcribe


class VideoResponseProcessor(FrameProcessor):
    """
    Processor that manages dual-track conversation for Cinema Chat:
    - User-facing track: User input → Video description → User input → Video description
    - Behind-the-scenes track: User input → LLM reasoning → Function call → Video selection

    This processor intercepts LLM text responses and replaces them with video descriptions
    from function call results before they're added to conversation history.

    It also validates that the LLM called the required function, and prompts it to retry if not.
    """

    def __init__(self, context_aggregator=None):
        super().__init__()
        self.pending_function_result = None
        self.llm_text_buffer = None
        self.function_was_called = False
        self.context_aggregator = context_aggregator

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        from pipecat.frames.frames import FunctionCallInProgressFrame

        # Track when a function call starts
        if isinstance(frame, FunctionCallInProgressFrame):
            logger.debug(f"[VideoResponse] Function call in progress: {frame.function_name}")
            self.function_was_called = True
            await self.push_frame(frame, direction)
            return

        # Track function call results
        if isinstance(frame, FunctionCallResultFrame):
            logger.debug(f"[VideoResponse] Function call result: {frame.result}")
            self.pending_function_result = frame.result
            self.function_was_called = True
            # Let the function result through
            await self.push_frame(frame, direction)
            return

        # Intercept LLM text responses
        if isinstance(frame, TextFrame) and direction == FrameDirection.DOWNSTREAM:
            # Check if we have a pending function result with a video description
            if self.pending_function_result and isinstance(self.pending_function_result, dict):
                video_description = self.pending_function_result.get("response")
                if video_description:
                    logger.info(f"[VideoResponse] Replacing LLM text '{frame.text}' with video description '{video_description}'")
                    # Replace the text frame with the video description
                    replaced_frame = TextFrame(video_description)
                    await self.push_frame(replaced_frame, direction)
                    # Clear the pending result and reset flag
                    self.pending_function_result = None
                    self.function_was_called = False
                    return

            # If no function was called, the LLM failed to follow instructions
            if not self.function_was_called:
                logger.warning(f"[VideoResponse] LLM did not call search_and_play_video function! Text was: '{frame.text}'")

                # Send a correction message back to the LLM via context aggregator
                if self.context_aggregator:
                    correction_message = {
                        "role": "system",
                        "content": "ERROR: You did not call the search_and_play_video function. You MUST call this function to respond. Please call search_and_play_video now with an appropriate query based on the user's message."
                    }
                    # Add the correction to the conversation context
                    await self.context_aggregator.push_messages([correction_message])
                    logger.info("[VideoResponse] Sent correction message to LLM")

                # Block the text from going to the user
                return

            # If function was called but we're still getting text, this is internal reasoning
            logger.debug(f"[VideoResponse] Blocking internal LLM text: {frame.text}")
            return

        # Let all other frames through
        await self.push_frame(frame, direction)


async def run_bot(room_url, token, identifier, data=None):
    """Run the Cinema Chat voice bot with the provided room URL and token.

    Args:
        room_url: The URL of the Daily room to connect to
        token: The access token for the Daily room
        identifier: A unique identifier for this bot instance
        data: Optional JSON-encoded data passed from the server
    """
    logger.info(f"Starting Cinema Chat bot in room {room_url} with identifier {identifier}")
    
    # print all env variables
    #logger.info(f"All environment variables: {dict(os.environ)}")
    # Parse the data if provided
    logger.info(f"Received data: {data}")
    config_data = {}
    if data:
        try:

            # Decode base64-encoded JSON data
            decoded_data = base64.b64decode(data).decode()
            logger.info(f"Decoded data: {decoded_data}")
            config_data = json.loads(decoded_data)
            logger.info(f"Parsed configuration data: {config_data}")
        except Exception as e:
            logger.error(f"Error parsing data parameter: {e}")
    
    transport = DailyTransport(
        room_url=room_url,
        token=token,
        bot_name="Cinema Chat",
        params=DailyParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(
                threshold=0.3,              # Sensitive to short bursts
                min_speech_duration_ms=100, # Captures brief utterances
                min_silence_duration_ms=50, # Quick response to speech end
                stop_secs=1.8,              # Tolerant of pauses in long speech
                max_speech_duration_secs=30 # Allow long utterances                
                )),
            vad_audio_passthrough=True,
            session_timeout=60 * 2,
        ),
    )
    
    llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"), model="gpt-4.1")
    
    # Get device from environment variable, default to cuda
    whisper_device = os.getenv("WHISPER_DEVICE", os.getenv("SPHINX_WHISPER_DEVICE", "cuda"))
    logger.info(f"Using device for Whisper STT: {whisper_device}")

    # Check if mount point is provided and valid
    mount_point = os.getenv("MOUNT_POINT", os.getenv("SPHINX_MOUNT_POINT", None))
    repo_id = os.getenv("REPO_ID", os.getenv("SPHINX_REPO_ID", None))
    model_path = None
    
    if mount_point and repo_id:
        # Format the full model path, extract the model name from the repo ID
        model_path = os.path.join(mount_point, "models", repo_id.split('/')[-1])
        logger.info(f"Using mount point for Whisper model: {mount_point}")
        logger.info(f"Hugging Face repo ID: {repo_id}")
        logger.info(f"Full model path: {model_path}")
        
        # Check if model directory exists
        if not os.path.exists(model_path):
            #log the content of the network volume for debugging starting from the root of the volume
            logger.info(f"Content of the network volume: {os.listdir(mount_point)}")
            logger.info(f"Model not found at {model_path}, downloading from Hugging Face repo: {repo_id}")
            try:
                # Create the models directory if it doesn't exist
                os.makedirs(os.path.dirname(model_path), exist_ok=True)
                
                # Download the model from Hugging Face
                logger.info(f"Starting model download from Hugging Face...")
                snapshot_download(
                    repo_id=repo_id,
                    local_dir=model_path,
                    local_dir_use_symlinks=False
                )
                
                logger.info(f"Successfully downloaded model to {model_path}")
            except Exception as e:
                logger.error(f"Error downloading model from Hugging Face: {e}")
                model_path = None
        else:
            logger.info(f"Model found at {model_path}")
    
    # Initialize WhisperSTTService with model path if available
    if model_path and os.path.exists(model_path):
        logger.info(f"Using local model from {model_path}")
        stt = WhisperSTTService(
            api_key=os.getenv("OPENAI_API_KEY"),
            device=whisper_device,
            model=model_path,
            no_speech_prob=0.2
        )
    else:
        logger.info("Using default Whisper model configuration")
        stt = WhisperSTTService(
            api_key=os.getenv("OPENAI_API_KEY"),
            device=whisper_device,
            model=Model.DISTIL_MEDIUM_EN,
            no_speech_prob=0.2
        )

    # TTS removed - cinema-bot uses video responses instead
    tts = None

    messages = [
        {
            "role": "system",
            "content": SYSTEM_ROLE,
        },
    ]

    if config_data.get("stationName"):
        station_name = config_data["stationName"]
    else:
        station_name = "Unknown Station"

    context = OpenAILLMContext(messages)
    context_aggregator = llm.create_context_aggregator(context)

    # STTMuteFilter removed - we want Whisper to always transcribe user speech
    # Cinema Chat needs to hear the user to respond with videos

    rtvi = RTVIProcessor(config=RTVIConfig(config=[]))
    await status_updater.initialize(rtvi, identifier, room_url, station_name)
    # hume_observer removed - emotion detection not needed for cinema-bot

    # Create video response processor to manage dual-track conversation
    # Pass context_aggregator so it can send correction messages to the LLM
    # TEMPORARILY DISABLED - debugging initialization issue
    # video_response_processor = VideoResponseProcessor(context_aggregator=context_aggregator)

    conversation_pipeline = Pipeline(
        [
            transport.input(),  # Websocket input from client
            rtvi,
            # stt_mute_filter removed - blocking transcription
            stt,  # Speech-To-Text
            context_aggregator.user(),
            llm,  # LLM
            # video_response_processor,  # Replace LLM text with video descriptions - TEMPORARILY DISABLED
            # tts removed - using video responses instead
            transport.output(),  # Websocket output to client
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        conversation_pipeline,
        params=PipelineParams(
            audio_in_sample_rate=16000,
            audio_out_sample_rate=48000,
            allow_interruptions=True,
        ),
        observers=[RTVIObserver(rtvi)]  # hume_observer removed
    )

    flow_manager = CustomFlowManager(
        task=task,
        llm=llm,
        context_aggregator=context_aggregator,
        tts=tts
    )

    # FlowManager is a FrameProcessor and needs to be in the pipeline, not attached to RTVI
    # RTVIProcessor.set_flow_manager() doesn't exist in Pipecat 0.0.95
    # FlowManager will handle function calls and flow state management through the pipeline

    async def handle_uioverride_response(processor, service, arguments):
        """Handler for UI override response action"""
        message = arguments.get("message", "Default message")
        logger.info(f"UI override response triggered with message: {message}")
        await processor.queue_frame(TranscriptionFrame(message, "", time_now_iso8601()), direction=FrameDirection.DOWNSTREAM)
        return True

    uioverride_response_action = RTVIAction(
        service="conversation",
        action="uioverride_response",
        arguments=[
            RTVIActionArgument(name="message", type="string")
        ],
        result="bool",
        handler=handle_uioverride_response
    )

    rtvi.register_action(uioverride_response_action)

    @transport.event_handler("on_participant_joined")
    async def on_participant_joined(transport, participant):
        #await audiobuffer.start_recording()
        # Kick off the conversation.
        participant_id = participant['id']
        logger.info(f"New client connected: {participant_id} using identifier {identifier}")
        
        try:
            # Update status updater with the participant ID
            await status_updater.initialize(rtvi, identifier, room_url, station_name)
            logger.info(f"StatusUpdater initialized with identifier: {identifier}")
            
            # Start transcription for the user
            await transport.capture_participant_transcription(participant_id)
            
            # Initialize the flow manager
            await flow_manager.initialize()

            # Start the flow manager
            await flow_manager.set_node("greeting", create_initial_node())
        except Exception as e:
            logger.error(f"Error during client connection handling: {e}")

    @transport.event_handler("on_app_message")
    async def on_app_message(transport, message, sender):
        """Handle app messages from Pi client (test pings for diagnostics)"""
        try:
            logger.info(f"📨 Received app message from {sender}")
            logger.debug(f"Message content: {message}")

            # Parse the message if it's a string
            if isinstance(message, str):
                msg_data = json.loads(message)
            else:
                msg_data = message

            # Log test ping messages
            if msg_data.get("type") == "pi-test-ping":
                logger.info(f"✅ Test ping #{msg_data.get('counter')}: {msg_data.get('message')}")
                logger.debug(f"Timestamp: {msg_data.get('timestamp')}")

                # Send to conversation log so it appears in frontend
                await status_updater.update_status(
                    f"[PI TEST PING] #{msg_data.get('counter')}: {msg_data.get('message')}"
                )
        except Exception as e:
            logger.error(f"Error handling app message: {e}")

    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, reason):
        logger.info(f"Participant left: {participant['id']}, reason: {reason}")
        try:
            if room_url and os.getenv("DAILY_API_KEY"):
                import aiohttp
                # Initialize Daily REST helper with proper aiohttp session
                async with aiohttp.ClientSession() as session:
                    daily_rest = DailyRESTHelper(
                        daily_api_key=os.getenv("DAILY_API_KEY", ""),
                        daily_api_url=os.getenv("DAILY_API_URL", "https://api.daily.co/v1"),
                        aiohttp_session=session
                    )

                    logger.info(f"Deleting Daily room: {room_url}")
                    try:
                        success = await daily_rest.delete_room_by_url(room_url)
                        if success:
                            logger.info(f"Successfully deleted room: {room_url}")
                        else:
                            logger.error(f"Failed to delete room: {room_url}")
                    except Exception as e:
                        logger.error(f"Error deleting Daily room: {e}")
        except Exception as e:
            logger.error(f"Error in on_participant_left: {e}")
        finally:
            # Close the status updater session
            await status_updater.close()

            # Cancel the pipeline, which stops processing and removes the bot from the room
            await task.cancel()

            # Log that we're exiting the process
            logger.info("Participant left, canceling pipeline task...")

            # Give a small delay to allow logs to flush
            await asyncio.sleep(1)

            # Instead of sys.exit, raise an exception that will be caught by the outer try/except
            # This allows for proper cleanup of resources
            raise asyncio.CancelledError("Participant left the room")

    try:
        runner = PipelineRunner()
        await runner.run(task)
    except asyncio.CancelledError:
        logger.info("Pipeline runner cancelled, shutting down gracefully...")
    except Exception as e:
        logger.error(f"Error in pipeline runner: {e}")
        # Exit with error code
        import sys
        sys.exit(1)


def main():
    """Main entry point for cinema-bot."""
    parser = argparse.ArgumentParser(description="Cinema Voice Bot")
    parser.add_argument(
        "-u", "--url", required=True, help="Room URL to connect to"
    )
    parser.add_argument(
        "-t", "--token", required=True, help="Access token for the room"
    )

    parser.add_argument(
        "-i", "--identifier", required=True, help="Unique bot identifier"
    )

    parser.add_argument(
        "-d", "--data", help="Optional JSON-encoded data passed from the server"
    )

    args = parser.parse_args()

    asyncio.run(run_bot(args.url, args.token, args.identifier, args.data))


if __name__ == "__main__":
    main()