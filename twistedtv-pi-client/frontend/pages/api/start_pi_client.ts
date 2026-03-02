/**
 * API endpoint to start a Pi client for a new session.
 * Supports both WebSocket (new fast path) and Daily.co (legacy) modes.
 */

import type { NextApiRequest, NextApiResponse } from 'next';
import { spawn } from 'child_process';

// Pi client paths
const VENV_PYTHON = '/home/twistedtv/venv_daily/bin/python3';
const WS_CLIENT = '/home/twistedtv/twistedtv-pi-client/ws_client.py';
// Legacy Daily client (kept for fallback)
const DAILY_CLIENT = '/home/twistedtv/twistedtv-pi-client/pi_daily_client/pi_daily_client.py';

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    const { wsUrl, roomUrl, token, backendUrl } = req.body;

    // Determine mode: WebSocket (new) or Daily (legacy)
    const useWebSocket = !!wsUrl;
    const sessionRef = wsUrl || roomUrl;

    if (!sessionRef) {
      return res.status(400).json({ error: 'wsUrl or roomUrl is required' });
    }

    const { exec } = require('child_process');
    const util = require('util');
    const execPromise = util.promisify(exec);

    // Clean up existing Pi processes
    console.log('Cleaning up existing Pi processes...');
    try {
      const { stdout } = await execPromise('bash /home/twistedtv/cleanup_pi.sh');
      console.log('Cleanup output:', stdout);

      const { stdout: verifyOutput } = await execPromise(
        'ps aux | grep -E "(pi_daily_client|ws_client).*\\.py" | grep -v grep || echo "CLEAN"'
      );

      if (!verifyOutput.includes('CLEAN')) {
        console.error('Cleanup verification failed:', verifyOutput);
        return res.status(500).json({
          success: false,
          error: 'Failed to cleanup existing Pi processes',
          details: verifyOutput
        });
      }
      await new Promise(resolve => setTimeout(resolve, 1000));
    } catch (cleanupErr: any) {
      console.error('Cleanup failed:', cleanupErr.message);
      return res.status(500).json({
        success: false,
        error: 'Failed to cleanup existing Pi processes',
        details: cleanupErr.message
      });
    }

    // Start video playback service
    try {
      const videoServiceCmd = `cd /home/twistedtv/twistedtv-pi-client/video_playback && nohup python3 video_playback_service_mpv.py > /tmp/video_mpv.log 2>&1 & echo $!`;
      const { stdout: pidOutput } = await execPromise(videoServiceCmd);
      const videoServicePid = parseInt(pidOutput.trim());
      console.log(`Video playback service started with PID: ${videoServicePid}`);
      await new Promise(resolve => setTimeout(resolve, 1500));
    } catch (videoErr) {
      console.error('Failed to start video service (continuing anyway):', videoErr);
    }

    // Auto-detect audio device
    let audioDevice = 'default';
    try {
      const fs = require('fs');
      try {
        const { stdout } = await execPromise('arecord -l');
        for (const line of stdout.split('\n')) {
          const cardMatch = line.match(/^card\s+(\d+):/);
          if (cardMatch) {
            const cardNum = parseInt(cardMatch[1]);
            const deviceMatch = line.match(/device\s+(\d+):/);
            const deviceNum = deviceMatch ? parseInt(deviceMatch[1]) : 0;
            audioDevice = `plughw:${cardNum},${deviceNum}`;
            console.log(`Auto-detected audio device: ${audioDevice}`);
            fs.writeFileSync('/home/twistedtv/audio_device.conf', audioDevice, 'utf-8');
            break;
          }
        }
      } catch {
        if (require('fs').existsSync('/home/twistedtv/audio_device.conf')) {
          audioDevice = require('fs').readFileSync('/home/twistedtv/audio_device.conf', 'utf-8').trim();
        }
      }
    } catch {
      console.log('Audio detection failed, using default');
    }

    // Spawn the appropriate client
    let clientArgs: string[];
    let env: NodeJS.ProcessEnv;

    if (useWebSocket) {
      // New WebSocket client — direct LAN connection
      clientArgs = [
        WS_CLIENT,
        '--server', wsUrl,
        '--audio-device', audioDevice,
        '--video-service', 'http://localhost:5000',
      ];
      env = { ...process.env, AUDIO_DEVICE: audioDevice };
      console.log(`Starting WebSocket client → ${wsUrl}`);
    } else {
      // Legacy Daily.co client
      clientArgs = [DAILY_CLIENT];
      env = {
        ...process.env,
        DAILY_ROOM_URL: roomUrl,
        DAILY_TOKEN: token || '',
        BACKEND_URL: backendUrl || 'http://localhost:8765',
        VIDEO_SERVICE_URL: 'http://localhost:5000',
        AUDIO_DEVICE: audioDevice,
      };
      console.log(`Starting Daily client → ${roomUrl}`);
    }

    try {
      const childProcess = spawn(VENV_PYTHON, clientArgs, {
        env,
        detached: true,
        stdio: ['ignore', 'pipe', 'pipe'],
      });

      const fs = require('fs');
      const logFile = `/tmp/pi_client_${childProcess.pid}.log`;
      const logStream = fs.createWriteStream(logFile, { flags: 'a' });
      childProcess.stdout?.pipe(logStream);
      childProcess.stderr?.pipe(logStream);
      childProcess.unref();

      console.log(`Pi client started with PID: ${childProcess.pid}, log: ${logFile}`);

      return res.status(200).json({
        success: true,
        message: `Pi client started (${useWebSocket ? 'WebSocket' : 'Daily'})`,
        pid: childProcess.pid,
        mode: useWebSocket ? 'websocket' : 'daily',
      });
    } catch (spawnError: any) {
      console.error('Error spawning Pi client:', spawnError);
      return res.status(500).json({
        success: false,
        error: 'Failed to start Pi client',
        details: spawnError.message,
      });
    }

  } catch (error: any) {
    console.error('Error in start_pi_client:', error);
    return res.status(500).json({ error: error.message });
  }
}
