import type { NextApiRequest, NextApiResponse } from 'next';

type NeedsHelpRequest = {
  help_data: {
    user: string;
    needs_help: boolean;
    phase?: string;
  };
};

type ResponseData = {
  success?: boolean;
  error?: string;
  help_needed?: boolean;
  message?: string;
};

/**
 * API handler for help requests (Cinema Chat)
 *
 * This endpoint receives help notifications from the bot backend
 * and logs them. In a production setup, this could trigger curator
 * notifications, display alerts in the frontend, or integrate with
 * other monitoring systems.
 */
export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse<ResponseData>
) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    const { help_data } = req.body as NeedsHelpRequest;

    if (!help_data || typeof help_data.user !== 'string' || typeof help_data.needs_help !== 'boolean') {
      return res.status(400).json({ error: 'Invalid request body. Missing or invalid help_data.' });
    }

    console.log('Help request received:', help_data);

    // TODO: Could add curator notification logic here
    // For now, just log and acknowledge

    return res.status(200).json({
      success: true,
      help_needed: help_data.needs_help,
      message: `Help request ${help_data.needs_help ? 'raised' : 'resolved'} for ${help_data.user}`
    });
  } catch (error: any) {
    console.error('Error in needs_help API:', error);
    return res.status(500).json({
      error: error.message || 'Unknown error'
    });
  }
} 