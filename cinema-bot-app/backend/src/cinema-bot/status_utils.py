import aiohttp
import asyncio
import os
import urllib.parse
from loguru import logger
from pipecat.processors.frameworks.rtvi import RTVIProcessor, RTVIServerMessageFrame

class StatusUpdater:
    def __init__(self):
        self.rtvi = None
        self.identifier = None
        self.room_url = None
        self.station_name = None
    
    async def initialize(self, rtvi: RTVIProcessor, identifier, room_url=None, station_name="Unknown Station"):
        self.rtvi = rtvi
        self.identifier = identifier
        self.room_url = room_url
        self.station_name = station_name
        logger.info(f"StatusUpdater initialized for identifier: {identifier}")
        logger.info(f"Station name: {station_name}")
        if room_url:
            logger.info(f"Room URL for reference: {room_url}")
    
    async def update_status(self, status, context=None,ui_override=None):
        logger.info(f"Updating status: {status} with UI override: {ui_override}")
        if not self.rtvi:
            logger.error("StatusUpdater not initialized with RTVI processor")
            return False
        
        data = {
            "status": status,
            "identifier": self.identifier,
            "status_context": context,
            "ui_override": ui_override  # Structured UI override data
        }
        
        try:
            status_frame = RTVIServerMessageFrame(data)
            await self.rtvi.push_frame(status_frame)
            return True
        except Exception as e:
            logger.error(f"Error updating status: {e}")
            return False

    async def close(self):
        logger.info("Sending goodbye system status")
        if not self.rtvi:
            logger.error("StatusUpdater not initialized with RTVI processor")
            return False
        
        data = {
            "status": "goodbye",
            "identifier": self.identifier,
            "status_context": None,
            "ui_override": None
        }
        
        try:
            status_frame = RTVIServerMessageFrame(data)
            await self.rtvi.push_frame(status_frame)
            return True
        except Exception as e:
            logger.error(f"Error closing StatusUpdater: {e}")
            return False

    async def needs_help(self, phase, needs_help=True):
        """
        Send a help request notification to the frontend.

        Args:
            phase: The phase/stage that needs help (e.g., "Greeting", "Name collection")
                  This is used for logging only, the station_name is sent instead
            needs_help: Whether help is needed (True) or the request should be resolved (False)
        """
        logger.info(f"[DEBUG] needs_help method called with phase={phase}, needs_help={needs_help}")
        logger.info(f"[DEBUG] Using station name: {self.station_name}")
        logger.info(f"[DEBUG] RTVI processor initialized: {self.rtvi is not None}")
        logger.info(f"[DEBUG] Identifier: {self.identifier}")
        
        if not self.rtvi:
            logger.error("[DEBUG] StatusUpdater not initialized with RTVI processor - cannot send help request")
            return False
        
        data = {
            "trigger": "NeedsHelp",
            "identifier": self.identifier,
            "help_data": {
                "user": self.station_name,  # Use the station name instead of the phase
                "needs_help": needs_help,
                "phase": phase  # Keep the phase as additional information
            }
        }
        
        try:
            logger.info(f"[DEBUG] Creating help request frame with data: {data}")
            status_frame = RTVIServerMessageFrame(data)
            logger.info(f"[DEBUG] Frame created: {status_frame}")
            logger.info(f"[DEBUG] Frame data: {status_frame.data if hasattr(status_frame, 'data') else 'No data attribute'}")
            logger.info(f"[DEBUG] Pushing help request frame to RTVI processor")
            logger.info(f"[DEBUG] RTVI processor type: {type(self.rtvi).__name__}")
            logger.info(f"[DEBUG] RTVI processor methods: {[m for m in dir(self.rtvi) if not m.startswith('_') and callable(getattr(self.rtvi, m))]}")
            
            # Verify push_frame method exists
            if not hasattr(self.rtvi, 'push_frame'):
                logger.error(f"[DEBUG] RTVI processor does not have push_frame method!")
                return False
                
            # Try pushing the frame with more detailed error handling
            logger.info(f"[DEBUG] About to call push_frame on RTVI processor")
            push_result = await self.rtvi.push_frame(status_frame)
            logger.info(f"[DEBUG] Push frame result: {push_result}")
            logger.info(f"[DEBUG] Successfully sent help request for station: {self.station_name}, phase: {phase}, needs_help={needs_help}")
            return True
        except Exception as e:
            logger.error(f"[DEBUG] Error sending needs_help event: {e}")
            import traceback
            logger.error(f"[DEBUG] Traceback: {traceback.format_exc()}")
            logger.error(f"[DEBUG] RTVI object: {self.rtvi}")
            logger.error(f"[DEBUG] RTVI state: {vars(self.rtvi) if self.rtvi else 'None'}")
            return False


status_updater = StatusUpdater()