import type { NextApiRequest, NextApiResponse } from 'next';

type TriggerVideoRequest = {
  video_query?: string;
  scene_description?: string;
};

type ResponseData = {
  success?: boolean;
  error?: string;
  message?: string;
};

/**
 * API handler for video trigger requests (Cinema Chat)
 *
 * Note: This endpoint is currently a stub. Video playback is handled
 * by the MCP server which the bot's LLM calls directly via function calling.
 * This endpoint could be used in the future for manual video triggering
 * or curator override functionality.
 */
export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse<ResponseData>
) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    const { video_query, scene_description } = req.body as TriggerVideoRequest;

    console.log('Video trigger request received:', { video_query, scene_description });

    // TODO: If we want manual video triggering, implement here
    // For now, videos are triggered via MCP server from LLM function calls

    return res.status(200).json({
      success: true,
      message: 'Video triggering handled by MCP server via LLM function calls'
    });
  } catch (error: any) {
    console.error('Error in trigger_video API:', error);
    return res.status(500).json({
      error: error.message || 'Unknown error'
    });
  }
}
