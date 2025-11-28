#!/usr/bin/env python3
"""
Generate a white noise static video (like old TV "no signal")
This will be played in a loop when the system is idle
"""

import numpy as np
import cv2
import os

def generate_static_video(output_path="/home/twistedtv/videos/static.mp4", duration=10, fps=30, width=1920, height=1080):
    """
    Generate a video of white noise static

    Args:
        output_path: Where to save the video
        duration: Length in seconds
        fps: Frames per second
        width: Video width
        height: Video height
    """
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    total_frames = duration * fps

    print(f"Generating {duration}s of static noise at {width}x{height}, {fps}fps...")

    for i in range(total_frames):
        # Generate random grayscale noise
        frame = np.random.randint(0, 256, (height, width), dtype=np.uint8)
        # Convert to BGR for OpenCV
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        out.write(frame_bgr)

        if (i + 1) % fps == 0:
            print(f"  Progress: {(i+1)//fps}/{duration} seconds")

    out.release()
    print(f"✓ Static video saved to: {output_path}")

if __name__ == "__main__":
    # Create a 10-second looping static video
    generate_static_video()
