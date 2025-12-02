// Test pod deployment with basic configuration
const fetch = require('node-fetch');
require('dotenv').config({ path: '../frontend-next/.env.local' });

const RUNPOD_API_KEY = process.env.RUNPOD_API_KEY;
const RUNPOD_API_URL = 'https://api.runpod.io/graphql';
const TEMPLATE_ID = process.env.NEXT_PUBLIC_RUNPOD_TEMPLATE_ID;

async function testPodDeployment() {
  try {
    console.log('Testing pod deployment with template ID:', TEMPLATE_ID);
    
    // Simplest possible pod deployment query with minimal required fields
    // Following exactly the format from the ashleykleynhans/runpod-api repository
    const query = `
      mutation {
        podFindAndDeployOnDemand(input: {
          cloudType: COMMUNITY
          templateId: "4njxjs5ikx"
          gpuCount: 1
          gpuTypeId: "NVIDIA GeForce RTX 4090"
          name: "my-pod"
          volumeInGb: 0
          containerDiskInGb: 20
          dataCenterId: "US-IL-1"
          networkVolumeId: "pwsi7066z6"
          env: []
        }) {
          id
        }
      }
    `;
    
    // Try method 1: Authorization header (as you were doing)
    /*console.log('\nTrying with Authorization header...');
    const response1 = await fetch(RUNPOD_API_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${RUNPOD_API_KEY}`
      },
      body: JSON.stringify({ query })
    });
    
    console.log('Response Status (Auth Header):', response1.status);
    const data1 = await response1.json();
    console.log('Response Body (Auth Header):', JSON.stringify(data1, null, 2));
    */
    // Try method 2: URL parameter (as in the GitHub repo)
    console.log('\nTrying with URL parameter...');
    const urlWithKey = `${RUNPOD_API_URL}?api_key=${RUNPOD_API_KEY}`;
    const response2 = await fetch(urlWithKey, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ query })
    });
    
    console.log('Response Status (URL Param):', response2.status);
    const data2 = await response2.json();
    console.log('Response Body (URL Param):', JSON.stringify(data2, null, 2));
    
    // Use the data from whichever method worked
    const data = response2.status === 200 ? data2 : data2;
    
    // Check for error types
    if (data.errors) {
      console.log('\nAnalyzing errors:');
      data.errors.forEach((error, index) => {
        console.log(`Error ${index + 1}:`);
        console.log(`- Message: ${error.message}`);
        console.log(`- Path: ${error.path}`);
        if (error.extensions) {
          console.log(`- Code: ${error.extensions.code}`);
          console.log(`- Exception: ${JSON.stringify(error.extensions.exception || {})}`);
        }
      });
    }
  } catch (error) {
    console.error('Fetch Error:', error);
  }
}

testPodDeployment();
