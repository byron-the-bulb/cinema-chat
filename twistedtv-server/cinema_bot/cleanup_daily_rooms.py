#!/usr/bin/env python3
#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import os
import asyncio
import aiohttp
import argparse
from datetime import datetime, timedelta, timezone
from loguru import logger
import sys
from dotenv import load_dotenv

# Import the DailyRESTHelper for room deletion only
from pipecat.transports.services.helpers.daily_rest import DailyRESTHelper

# Setup logging
logger.remove(0)
logger.add(sys.stderr, level="INFO")

async def cleanup_daily_rooms(days_to_keep=1, dry_run=False, direct_api=True):
    """
    Delete all Daily rooms that were created before the cutoff date.
    
    Args:
        days_to_keep: Number of days of rooms to keep (default: 1, which keeps only today's rooms)
        dry_run: If True, only list rooms that would be deleted without deleting them
    """
    # Load environment variables
    load_dotenv(override=True)
    
    # Get API credentials
    daily_api_key = os.getenv("DAILY_API_KEY")
    daily_api_url = os.getenv("DAILY_API_URL", "https://api.daily.co/v1")
    
    if not daily_api_key:
        logger.error("DAILY_API_KEY environment variable is not set")
        return
    
    # Calculate cutoff date (anything before this will be deleted)
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
    cutoff_date = cutoff_date.replace(hour=0, minute=0, second=0, microsecond=0)
    logger.info(f"Cutoff date: {cutoff_date.isoformat()} - Will delete rooms created before this date")
    
    deleted_count = 0
    error_count = 0
    skipped_count = 0
    
    async with aiohttp.ClientSession() as session:
        # Initialize Daily REST helper for room deletion
        daily_rest = DailyRESTHelper(
            daily_api_key=daily_api_key,
            daily_api_url=daily_api_url,
            aiohttp_session=session
        )
        
        # List all rooms directly using the Daily API
        logger.info("Fetching list of all Daily rooms...")
        
        # Make a direct request to the Daily API's list-rooms endpoint
        rooms_endpoint = f"{daily_api_url}/rooms"
        headers = {"Authorization": f"Bearer {daily_api_key}"}
        
        async with session.get(rooms_endpoint, headers=headers) as response:
            if response.status != 200:
                logger.error(f"Failed to list rooms: {response.status}, {await response.text()}")
                return
            
            response_data = await response.json()
            rooms = response_data.get('data', [])
        
        if not rooms:
            logger.info("No rooms found")
            return
        
        logger.info(f"Found {len(rooms)} rooms total")
        
        # Process each room
        for room in rooms:
            try:
                # Extract creation time - handle different timestamp formats
                created_at_value = room.get('created_at')
                room_name = room.get('name', 'Unknown')
                
                # Check timestamp format and convert to datetime (always with UTC timezone)
                if isinstance(created_at_value, int) or isinstance(created_at_value, float):
                    # Numeric timestamp - convert to UTC aware datetime
                    created_at = datetime.fromtimestamp(created_at_value, tz=timezone.utc)
                elif isinstance(created_at_value, str):
                    # ISO format string (common API response format)
                    try:
                        # Try parsing ISO format (will be timezone aware)
                        created_at = datetime.fromisoformat(created_at_value.replace('Z', '+00:00'))
                    except ValueError:
                        # If not ISO format, try to convert to float first
                        created_at = datetime.fromtimestamp(float(created_at_value), tz=timezone.utc)
                else:
                    # Default to current time if missing
                    logger.warning(f"Could not parse creation time for room {room_name}, using default")
                    created_at = datetime.now(timezone.utc)
                
                # Check if the room was created before the cutoff date
                if created_at < cutoff_date:
                    logger.info(f"Room '{room_name}' created at {created_at.isoformat()} is older than the cutoff date")
                    
                    if not dry_run:
                        # Delete the room - either using DailyRESTHelper or direct API
                        if direct_api:
                            # Delete directly using Daily API
                            delete_endpoint = f"{daily_api_url}/rooms/{room_name}"
                            async with session.delete(delete_endpoint, headers=headers) as delete_response:
                                if delete_response.status == 200:
                                    logger.info(f"Successfully deleted room: {room_name}")
                                    deleted_count += 1
                                else:
                                    error_text = await delete_response.text()
                                    logger.error(f"Failed to delete room {room_name}: {delete_response.status}, {error_text}")
                                    error_count += 1
                        else:
                            # Use DailyRESTHelper for deletion
                            success = await daily_rest.delete_room(room_name)
                            if success:
                                logger.info(f"Successfully deleted room: {room_name}")
                                deleted_count += 1
                            else:
                                logger.error(f"Failed to delete room: {room_name}")
                                error_count += 1
                    else:
                        logger.info(f"[DRY RUN] Would delete room: {room_name}")
                        deleted_count += 1
                else:
                    logger.info(f"Keeping room '{room_name}' created at {created_at.isoformat()}")
                    skipped_count += 1
            except Exception as e:
                logger.error(f"Error processing room {room.get('name', 'Unknown')}: {e}")
                error_count += 1
        
    # Final summary
    logger.info(f"Cleanup complete: {deleted_count} rooms deleted, {skipped_count} rooms kept, {error_count} errors")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean up old Daily rooms")
    parser.add_argument(
        "--days", type=int, default=1, 
        help="Number of days of rooms to keep (default: 1, which keeps only today's rooms)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List rooms that would be deleted without actually deleting them"
    )
    parser.add_argument(
        "--use-helper", action="store_true",
        help="Use DailyRESTHelper for deletion instead of direct API calls"
    )
    
    args = parser.parse_args()
    
    # Run with the chosen parameters
    asyncio.run(cleanup_daily_rooms(
        days_to_keep=args.days, 
        dry_run=args.dry_run,
        direct_api=not args.use_helper
    ))
