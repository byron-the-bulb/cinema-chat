/**
 * API endpoint to clean up all Pi processes
 * Kills all Daily clients, video services, and MPV processes
 */

import type { NextApiRequest, NextApiResponse } from 'next';
import { exec } from 'child_process';
import { promisify } from 'util';

const execPromise = promisify(exec);

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    console.log('Cleaning up all Pi processes...');

    // Run the cleanup script on the Pi
    const { stdout, stderr } = await execPromise(
      'ssh twistedtv@192.168.1.201 "bash /home/twistedtv/cleanup_pi.sh"'
    );

    console.log('Cleanup stdout:', stdout);
    if (stderr) {
      console.log('Cleanup stderr:', stderr);
    }

    return res.status(200).json({
      success: true,
      message: 'Pi processes cleaned up successfully',
      output: stdout
    });
  } catch (error: any) {
    console.error('Error cleaning up Pi:', error);
    return res.status(500).json({
      success: false,
      error: error.message,
      stderr: error.stderr
    });
  }
}
