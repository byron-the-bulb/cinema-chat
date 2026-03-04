// Simple script to query RunPod for available GPU types
const axios = require('axios');
require('dotenv').config({ path: '../frontend-next/.env.local' });

const RUNPOD_API_KEY = process.env.RUNPOD_API_KEY;
const RUNPOD_API_URL = 'https://api.runpod.io/graphql';

async function queryGpuTypes() {
  try {
    const query = `
      query GpuTypes {
        gpuTypes {
          id
          displayName
          memoryInGb
        }
      }
    `;

    const response = await axios.post(
      RUNPOD_API_URL,
      { query },
      {
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${RUNPOD_API_KEY}`,
        },
      }
    );

    console.log(JSON.stringify(response.data, null, 2));
  } catch (error) {
    console.error('Error querying GPU types:', error.response?.data || error.message);
  }
}

queryGpuTypes();
