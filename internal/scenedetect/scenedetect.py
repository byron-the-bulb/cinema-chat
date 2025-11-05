#!/usr/bin/env python3

import sys
import json
import os
from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector
from scenedetect.video_splitter import split_video_ffmpeg

def detect_scenes(video_path, threshold=30.0):
    """Detect scenes in a video file using PySceneDetect"""
    try:
        # Open the video
        video = open_video(video_path)
        
        # Create a scene manager and add detectors
        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=threshold))
        
        # Detect scenes
        scene_manager.detect_scenes(video, show_progress=False)
        
        # Get the list of scenes
        scenes = scene_manager.get_scene_list()
        
        # Convert to our format
        scene_list = []
        for i, scene in enumerate(scenes):
            start_time = scene[0].get_seconds()
            end_time = scene[1].get_seconds()
            scene_list.append({
                'index': i,
                'start_time': start_time,
                'end_time': end_time
            })
        
        return scene_list
    except Exception as e:
        raise Exception(f"Failed to detect scenes: {str(e)}")

def extract_keyframes(video_path, scenes, output_dir):
    """Extract keyframes for detected scenes"""
    try:
        os.makedirs(output_dir, exist_ok=True)
        
        # For each scene, extract a keyframe from the middle
        for scene in scenes:
            index = scene['index']
            start_time = scene['start_time']
            end_time = scene['end_time']
            mid_time = (start_time + end_time) / 2.0
            
            output_path = os.path.join(output_dir, f"scene_{index:04d}_keyframe.jpg")
            
            # Use ffmpeg to extract the keyframe
            cmd = [
                'ffmpeg',
                '-ss', str(mid_time),
                '-i', video_path,
                '-vframes', '1',
                '-q:v', '2',
                output_path,
                '-y'  # Overwrite output files
            ]
            
            # Run ffmpeg command
            import subprocess
            subprocess.run(cmd, check=True, capture_output=True)
            
        return True
    except Exception as e:
        raise Exception(f"Failed to extract keyframes: {str(e)}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scenedetect.py <video_path> [threshold] [output_dir]")
        sys.exit(1)
    
    video_path = sys.argv[1]
    threshold = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
    output_dir = sys.argv[3] if len(sys.argv) > 3 else None
    
    try:
        # Detect scenes
        scenes = detect_scenes(video_path, threshold)
        
        # If output directory is provided, extract keyframes
        if output_dir:
            extract_keyframes(video_path, scenes, output_dir)
        
        # Output results as JSON
        result = {
            'scenes': scenes,
            'count': len(scenes)
        }
        
        print(json.dumps(result))
        
    except Exception as e:
        print(json.dumps({'error': str(e)}))
        sys.exit(1)