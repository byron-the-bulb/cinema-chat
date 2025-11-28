#!/usr/bin/env python3
"""
Simple HTTP server for video streaming that handles range requests properly
"""
from flask import Flask, send_from_directory, request
import os

app = Flask(__name__)
VIDEO_DIR = os.path.dirname(os.path.abspath(__file__))

@app.route('/<path:filename>')
def serve_video(filename):
    """Serve video files with proper range request support"""
    return send_from_directory(VIDEO_DIR, filename)

if __name__ == '__main__':
    print(f"Starting video streaming server on port 9000")
    print(f"Serving files from: {VIDEO_DIR}")
    app.run(host='0.0.0.0', port=9000, threaded=True)
