/**
 * API endpoint to set the active audio input device on the local Pi
 */

import type { NextApiRequest, NextApiResponse } from 'next';
import { writeFile } from 'fs/promises';

const AUDIO_CONFIG_FILE = '/home/twistedtv/audio_device.conf';

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    const { device_id } = req.body;

    if (!device_id) {
      return res.status(400).json({ error: 'device_id is required' });
    }

    // Validate ALSA device ID format (e.g., hw:1,0 or plughw:1,0)
    if (!/^(plug)?hw:\d+,\d+$/.test(device_id)) {
      return res.status(400).json({
        error: 'Invalid device_id format. Expected format: hw:CARD,DEVICE or plughw:CARD,DEVICE (e.g., hw:1,0 or plughw:1,0)'
      });
    }

    // Write the device ID to a config file
    // The Pi client will read this when starting up
    await writeFile(AUDIO_CONFIG_FILE, device_id, 'utf-8');

    console.log(`Set Pi audio device to: ${device_id}`);

    // Also set as environment variable for current process
    process.env.AUDIO_DEVICE = device_id;

    return res.status(200).json({
      success: true,
      message: `Audio device set to ${device_id}`,
      device_id
    });

  } catch (error: any) {
    console.error('Error setting audio device:', error);
    return res.status(500).json({
      error: error.message,
      success: false
    });
  }
}
