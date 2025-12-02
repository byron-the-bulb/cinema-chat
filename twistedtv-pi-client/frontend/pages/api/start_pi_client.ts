/**
 * API endpoint to start a Pi Daily.co client for a new room
 * Each room gets its own dedicated Python client process
 */

import type { NextApiRequest, NextApiResponse } from 'next';
import { spawn } from 'child_process';

// Pi client paths - use venv_daily python with all dependencies
const VENV_PYTHON = '/home/twistedtv/venv_daily/bin/python3';
const PYTHON_CLIENT = '/home/twistedtv/twistedtv-new/pi_daily_client/pi_daily_client.py';
const VIDEO_SERVICE = '/home/twistedtv/twistedtv-new/video_playback/video_playback_service_mpv.py';

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
      // Clean up all existing Pi processes first - MUST succeed to prevent multiple sessions
      const { exec } = require('child_process');
      const util = require('util');
      const execPromise = util.promisify(exec);

      console.log('Cleaning up existing Pi processes...');

      // Run the cleanup script locally (Next.js is running on the Pi)
      try {
        const { stdout } = await execPromise('bash /home/twistedtv/cleanup_pi.sh');
        console.log('Cleanup output:', stdout);

        // Verify cleanup actually worked by checking for running processes
        const { stdout: verifyOutput } = await execPromise('ps aux | grep -E "pi_daily_client.*\\.py" | grep -v grep || echo "CLEAN"');

        if (!verifyOutput.includes('CLEAN')) {
          console.error('Cleanup verification failed - processes still running:', verifyOutput);
          return res.status(500).json({
            success: false,
            error: 'Failed to cleanup existing Pi processes. Please manually kill them before starting a new session.',
            details: verifyOutput
          });
        }

        console.log('Cleanup verification: All Pi client processes terminated');
        await new Promise(resolve => setTimeout(resolve, 1000)); // Wait for cleanup to complete
      } catch (cleanupErr: any) {
        console.error('Cleanup failed:', cleanupErr.message);
        return res.status(500).json({
          success: false,
          error: 'Failed to cleanup existing Pi processes',
          details: cleanupErr.message
        });
      }

      try {

        // Start new video service with nohup and capture PID
        const videoServiceCmd = `cd /home/twistedtv/twistedtv-new/video_playback && nohup python3 video_playback_service_mpv.py > /tmp/video_mpv.log 2>&1 & echo $!`;
        const { stdout: pidOutput } = await execPromise(videoServiceCmd);
        const videoServicePid = parseInt(pidOutput.trim());

        console.log(`Video playback service started with PID: ${videoServicePid}`);
        await new Promise(resolve => setTimeout(resolve, 1500)); // Give it time to start

        // Register the video service PID with the backend
        if (videoServicePid && backendUrl) {
          try {
            const registerUrl = `${backendUrl}/register-video-service`;
            const registerResponse = await fetch(registerUrl, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                room_url: roomUrl,
                video_service_pid: videoServicePid
              })
            });

            if (registerResponse.ok) {
              console.log(`Registered video service PID ${videoServicePid} with backend`);
            } else {
              console.warn(`Failed to register video service with backend: ${registerResponse.statusText}`);
            }
          } catch (registerError) {
            console.error('Error registering video service with backend:', registerError);
          }
        }

        // Note: Static background loop is started automatically by video service
      } catch (videoErr) {
        console.error('Failed to start video service (continuing anyway):', videoErr);
        // Don't fail the entire request if video service fails to start
      }

      // Auto-detect and configure audio device before starting Pi client
      let audioDevice = 'default';
      try {
        const fs = require('fs');
        const { exec } = require('child_process');
        const util = require('util');
        const execPromise = util.promisify(exec);

        // Detect available audio devices
        try {
          const { stdout } = await execPromise('arecord -l');
          const lines = stdout.split('\n');

          // Find first audio capture device
          for (const line of lines) {
            const cardMatch = line.match(/^card\s+(\d+):/);
            if (cardMatch) {
              const cardNum = parseInt(cardMatch[1]);
              const deviceMatch = line.match(/device\s+(\d+):/);
              const deviceNum = deviceMatch ? parseInt(deviceMatch[1]) : 0;

              // Use plughw format
              audioDevice = `plughw:${cardNum},${deviceNum}`;
              console.log(`Auto-detected audio device: ${audioDevice}`);

              // Write to config file for future reference
              fs.writeFileSync('/home/twistedtv/audio_device.conf', audioDevice, 'utf-8');
              break;
            }
          }
        } catch (detectErr) {
          console.warn('Could not auto-detect audio device, checking config file...');
          // Fall back to config file if auto-detection fails
          if (fs.existsSync('/home/twistedtv/audio_device.conf')) {
            audioDevice = fs.readFileSync('/home/twistedtv/audio_device.conf', 'utf-8').trim();
            console.log(`Using audio device from config: ${audioDevice}`);
          } else {
            console.log('No audio device config found, using default');
          }
        }
      } catch (err) {
        console.log('Error reading audio config, using default:', err);
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

      // Register the Pi client PID with the backend for tracking
      try {
        const registerUrl = `${backendUrl}/register-pi-client`;
        const registerResponse = await fetch(registerUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            room_url: roomUrl,
            pi_client_pid: childProcess.pid
          })
        });

        if (registerResponse.ok) {
          console.log(`Registered Pi client PID ${childProcess.pid} with backend`);
        } else {
          console.warn(`Failed to register Pi client with backend: ${registerResponse.statusText}`);
        }
      } catch (registerError) {
        console.error('Error registering Pi client with backend:', registerError);
        // Don't fail the entire request if registration fails
      }

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
