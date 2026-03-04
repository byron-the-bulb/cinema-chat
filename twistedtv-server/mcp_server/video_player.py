"""Video playback control using ffmpeg."""
import subprocess
import logging
import asyncio
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class VideoPlayer:
    """Manages video playback using ffmpeg."""

    def __init__(self, output_device: Optional[str] = None):
        """Initialize video player.

        Args:
            output_device: Optional output device (display number or device path)
                          If None, plays in default window
        """
        self.output_device = output_device
        self.current_process: Optional[subprocess.Popen] = None
        self.current_file: Optional[str] = None

    async def play_clip(
        self,
        video_path: str,
        start_time: float,
        end_time: float,
        fullscreen: bool = True
    ) -> bool:
        """Play a video clip from start_time to end_time.

        Args:
            video_path: Path to the video file
            start_time: Start time in seconds
            end_time: End time in seconds
            fullscreen: Whether to play fullscreen

        Returns:
            True if playback started successfully, False otherwise
        """
        # Stop any current playback
        await self.stop()

        # Validate file exists
        if not Path(video_path).exists():
            logger.error(f"Video file not found: {video_path}")
            return False

        # Calculate duration
        duration = end_time - start_time

        logger.info(f"Playing clip: {video_path} from {start_time:.2f}s to {end_time:.2f}s")

        # Build ffmpeg command
        # Use ffplay for simple playback with automatic cleanup
        cmd = [
            "ffplay",
            "-ss", str(start_time),       # Seek to start time
            "-t", str(duration),           # Duration to play
            "-autoexit",                   # Exit when done
            "-loglevel", "error",          # Quiet output
        ]

        if fullscreen:
            cmd.append("-fs")  # Fullscreen

        if self.output_device:
            # For specific display, set DISPLAY environment variable
            # This works on Linux with X11
            pass  # TODO: handle specific display output

        cmd.append(video_path)

        try:
            # Run ffplay as subprocess
            # Don't capture stdout/stderr - let video window appear normally
            self.current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            self.current_file = video_path

            logger.info(f"Started playback (PID: {self.current_process.pid})")

            # Give the process a moment to start
            import time
            time.sleep(0.1)

            # Check if process is still running (didn't immediately fail)
            if self.current_process.poll() is not None:
                logger.error(f"Process exited immediately with code: {self.current_process.returncode}")
                return False

            return True

        except Exception as e:
            logger.error(f"Failed to start playback: {e}")
            return False

    async def stop(self):
        """Stop current video playback."""
        if self.current_process:
            logger.info(f"Stopping playback (PID: {self.current_process.pid})")
            try:
                self.current_process.terminate()
                # Wait briefly for graceful shutdown
                try:
                    self.current_process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    # Force kill if still running
                    self.current_process.kill()
                    self.current_process.wait()

                logger.info("Playback stopped")
            except Exception as e:
                logger.error(f"Error stopping playback: {e}")
            finally:
                self.current_process = None
                self.current_file = None

    def is_playing(self) -> bool:
        """Check if video is currently playing.

        Returns:
            True if a video is playing, False otherwise
        """
        if self.current_process:
            # Check if process is still running
            return self.current_process.poll() is None
        return False

    async def wait_for_completion(self):
        """Wait for current video to finish playing."""
        if self.current_process:
            # Use asyncio to wait without blocking
            while self.current_process.poll() is None:
                await asyncio.sleep(0.1)

            logger.info("Playback completed")
            self.current_process = None
            self.current_file = None

    def cleanup(self):
        """Cleanup resources (called on shutdown)."""
        if self.current_process:
            try:
                self.current_process.terminate()
                self.current_process.wait(timeout=1.0)
            except:
                pass
