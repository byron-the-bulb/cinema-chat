import type { NextApiRequest, NextApiResponse } from 'next';
import axios from 'axios';

// Local Python backend URL
const LOCAL_BACKEND_URL = 'http://localhost:8765/connect';

type ResponseData = {
  roomUrl?: string;
  token?: string;
  error?: string;
};

/**
 * API handler that proxies requests to the local Python backend
 * This allows testing the frontend without launching RunPod instances
 */
export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse<ResponseData>
) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    console.log('Proxying request to local backend at:', LOCAL_BACKEND_URL);
    console.log('Request body:', req.body);
    
    // Forward the request to the local Python backend
    const response = await axios.post(LOCAL_BACKEND_URL, req.body, {
      headers: {
        'Content-Type': 'application/json',
      },
    });
    
    console.log('Local backend response:', response.data);
    
    // Return the response from the local backend
    return res.status(200).json(response.data);
  } catch (error) {
    console.error('Error connecting to local backend:', error);
    return res.status(500).json({ 
      error: error instanceof Error ? error.message : 'An unknown error occurred' 
    });
  }
}
