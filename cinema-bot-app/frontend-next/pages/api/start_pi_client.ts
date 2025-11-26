/**
 * API endpoint to start a Pi Daily.co client for a new room
 * Each room gets its own dedicated Python client process
 */

import type { NextApiRequest, NextApiResponse } from 'next';
import { spawn } from 'child_process';

// Pi client paths - use venv_daily python with all dependencies
const VENV_PYTHON = '/home/twistedtv/venv_daily/bin/python3';
const PYTHON_CLIENT = '/home/twistedtv/pi_daily_client_rtvi.py';

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    const { roomUrl, token, backendUrl } = req.body;

    if (!roomUrl) {
      return res.status(400).json({ error: 'roomUrl is required' });
    }

    // Spawn a new Pi client for this room
    try {
      // Start video playback service (with static noise) before starting Pi client
      try {
        const { exec } = require('child_process');
        const util = require('util');
        const execPromise = util.promisify(exec);

        console.log('Starting video playback service...');

        // Kill any existing video service first
        try {
          await execPromise('pkill -9 -f video_playback_service_mpv.py');
          await new Promise(resolve => setTimeout(resolve, 500)); // Brief delay
        } catch (killErr) {
          // Ignore error if no process to kill
        }

        // Start new video service with nohup
        const videoServiceCmd = 'cd /home/twistedtv && nohup python3 video_playback_service_mpv.py > /tmp/video_mpv.log 2>&1 &';
        await execPromise(videoServiceCmd);

        console.log('Video playback service started');
        await new Promise(resolve => setTimeout(resolve, 1500)); // Give it time to start

        // Start static noise playback immediately
        try {
          const startStaticCmd = 'curl -X POST http://localhost:5000/play -H "Content-Type: application/json" -d \'{"video_path":"/home/twistedtv/videos/static.mp4","start":0,"end":999999,"fullscreen":true}\' > /dev/null 2>&1 &';
          await execPromise(startStaticCmd);
          console.log('Static noise playback started');
        } catch (staticErr) {
          console.error('Failed to start static (continuing anyway):', staticErr);
        }
      } catch (videoErr) {
        console.error('Failed to start video service (continuing anyway):', videoErr);
        // Don't fail the entire request if video service fails to start
      }

      // Read the configured audio device if available
      let audioDevice = 'default';
      try {
        const fs = require('fs');
        if (fs.existsSync('/home/twistedtv/audio_device.conf')) {
          audioDevice = fs.readFileSync('/home/twistedtv/audio_device.conf', 'utf-8').trim();
        }
      } catch (err) {
        console.log('No audio device config found, using default');
      }

      const env = {
        ...process.env,
        DAILY_ROOM_URL: roomUrl,
        DAILY_TOKEN: token || '',
        BACKEND_URL: backendUrl || 'http://localhost:8765',
        VIDEO_SERVICE_URL: 'http://localhost:5000',
        AUDIO_DEVICE: audioDevice
      };

      console.log(`Starting Pi client for room: ${roomUrl}`);
      console.log(`Backend URL: ${env.BACKEND_URL}`);

      const childProcess = spawn(VENV_PYTHON, [PYTHON_CLIENT], {
        env,
        detached: true,
        stdio: ['ignore', 'pipe', 'pipe']
      });

      // Write stdout/stderr to PID-specific log file for debugging
      const fs = require('fs');
      const logFile = `/tmp/pi_client_${childProcess.pid}.log`;
      const logStream = fs.createWriteStream(logFile, { flags: 'a' });

      childProcess.stdout?.pipe(logStream);
      childProcess.stderr?.pipe(logStream);

      // Detach the process so it continues after API response
      childProcess.unref();

      console.log(`Pi client started with PID: ${childProcess.pid}, log: ${logFile}`);

      return res.status(200).json({
        success: true,
        message: 'Pi client started successfully',
        pid: childProcess.pid,
        roomUrl
      });
    } catch (spawnError: any) {
      console.error('Error spawning Pi client:', spawnError);
      return res.status(500).json({
        success: false,
        error: 'Failed to start Pi client',
        details: spawnError.message
      });
    }

  } catch (error: any) {
    console.error('Error notifying Pi:', error);
    return res.status(500).json({ error: error.message });
  }
}
