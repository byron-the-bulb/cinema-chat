/**
 * API endpoint to get available audio input devices on the local Pi
 */

import type { NextApiRequest, NextApiResponse } from 'next';
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

interface AudioDevice {
  card: number;
  device: number;
  name: string;
  alsa_id: string;
}

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    // Run arecord -l to list audio capture devices
    const { stdout, stderr } = await execAsync('arecord -l');

    if (stderr && !stdout) {
      throw new Error(`arecord command failed: ${stderr}`);
    }

    // Parse arecord output to extract devices
    // Format: card 1: Device [USB Audio Device], device 0: USB Audio [USB Audio]
    const devices: AudioDevice[] = [];
    const lines = stdout.split('\n');

    for (const line of lines) {
      if (line.startsWith('card')) {
        try {
          // Extract card number (e.g., "card 1:")
          const cardMatch = line.match(/card\s+(\d+):/);
          if (!cardMatch) continue;
          const cardNum = parseInt(cardMatch[1]);

          // Extract device name from brackets (e.g., "[USB Audio Device]")
          const nameMatch = line.match(/\[([^\]]+)\]/);
          const deviceName = nameMatch ? nameMatch[1] : 'Unknown';

          // Extract device number (e.g., "device 0:")
          const deviceMatch = line.match(/device\s+(\d+):/);
          const deviceNum = deviceMatch ? parseInt(deviceMatch[1]) : 0;

          // Create ALSA device ID (use plughw for better compatibility)
          const alsaId = `plughw:${cardNum},${deviceNum}`;

          devices.push({
            card: cardNum,
            device: deviceNum,
            name: deviceName,
            alsa_id: alsaId
          });
        } catch (parseError) {
          console.error(`Error parsing line: ${line}`, parseError);
          continue;
        }
      }
    }

    return res.status(200).json({
      devices,
      raw_output: stdout
    });

  } catch (error: any) {
    console.error('Error getting audio devices:', error);
    return res.status(500).json({
      error: error.message,
      devices: []
    });
  }
}
