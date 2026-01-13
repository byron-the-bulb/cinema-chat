// List all available RunPod templates for your account
const fetch = require('node-fetch');
require('dotenv').config({ path: '../frontend-next/.env.local' });

const RUNPOD_API_KEY = process.env.RUNPOD_API_KEY;
const RUNPOD_API_URL = 'https://api.runpod.io/graphql';

async function listTemplates() {
  try {
    // Query to get all available templates
    const query = `{
      myself {
        podTemplates {
          id
          imageName
          name
        }
      }
    }`; 

  
    const query2 = `{
      myself {
        datacenters {
          id
          name
          gpuAvailability(input:{
            minDisk:40
            minMemoryInGb:15
            minVcpuCount:4

          }) {
            available
            stockStatus
            gpuTypeId
            displayName
          }
        }
      }
    }`;

    const query3 = `{
      myself {
        datacenters {
          id
          name
          gpuAvailability{
            available
            stockStatus
            gpuTypeId
            displayName
          }
        }
      }
    }`;
      
    const response = await fetch(RUNPOD_API_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${RUNPOD_API_KEY}`
      },
      body: JSON.stringify({ query:query3 })
    });
    
    const data = await response.json();
    
    if (data.errors) {
      console.error('GraphQL Errors:', JSON.stringify(data.errors, null, 2));
      return;
    }
    
    console.log("Result: " + JSON.stringify(data, null, 2));
    const templates = data.data.myself.podTemplates;
    
    console.log(`Found ${templates.length} templates in your account:\n`);
    
    templates.forEach((template, index) => {
      console.log(`${index + 1}. Template ID: ${template.id}`);
      console.log(`   Name: ${template.name}`);
      console.log(`   ImageName: ${template.imageName}`);
      console.log('');
    });
    
    console.log('\nTo use one of these templates, update your .env.local file with:');
    console.log('NEXT_PUBLIC_RUNPOD_TEMPLATE_ID=the_template_id_you_want_to_use');
    
  } catch (error) {
    console.error('Error fetching templates:', error);
  }
}

listTemplates();
