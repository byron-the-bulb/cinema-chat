// Script to run GraphQL introspection query on RunPod API
const fetch = require('node-fetch');
require('dotenv').config({ path: './frontend-next/.env.local' });

const RUNPOD_API_KEY = process.env.RUNPOD_API_KEY;
const RUNPOD_API_URL = 'https://api.runpod.io/graphql';

async function runIntrospectionQuery() {
  try {
    // GraphQL introspection query to examine the PodFindAndDeployOnDemandInput type
    const query = `
      query {
        __type(name: "myself") {
          inputFields {
            name
            type {
              name
              kind
            }
            isNonNull
          }
        }
      }
    `;
    
    console.log('Running GraphQL introspection query...');
    
    // Make the request with authorization header
    const response = await fetch(RUNPOD_API_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${RUNPOD_API_KEY}`
      },
      body: JSON.stringify({ query })
    });
    
    console.log('Response Status:', response.status);
    const data = await response.json();
    
    if (data.errors) {
      console.error('GraphQL Errors:', JSON.stringify(data.errors, null, 2));
      return;
    }
    
    if (data.data && data.data.__type && data.data.__type.inputFields) {
      console.log('\nFields for PodFindAndDeployOnDemandInput:');
      console.log('===========================================');
      
      // Sort fields by required status (required first) then alphabetically
      const fields = data.data.__type.inputFields.sort((a, b) => {
        if (a.isNonNull && !b.isNonNull) return -1;
        if (!a.isNonNull && b.isNonNull) return 1;
        return a.name.localeCompare(b.name);
      });
      
      // Print required fields first, then optional
      console.log('\nREQUIRED FIELDS:');
      const requiredFields = fields.filter(f => f.isNonNull === true);
      if (requiredFields.length === 0) {
        console.log('  None');
      } else {
        requiredFields.forEach(field => {
          console.log(`  ${field.name}: ${field.type.kind === 'ENUM' ? 'ENUM' : field.type.name}`);
        });
      }
      
      console.log('\nOPTIONAL FIELDS:');
      const optionalFields = fields.filter(f => f.isNonNull !== true);
      optionalFields.forEach(field => {
        console.log(`  ${field.name}: ${field.type.kind === 'ENUM' ? 'ENUM' : field.type.name}`);
      });
      
      // Save full raw response to file for reference
      const fs = require('fs');
      fs.writeFileSync(
        './runpod-introspection-result.json', 
        JSON.stringify(data.data, null, 2)
      );
      console.log('\nFull results saved to runpod-introspection-result.json');
    } else {
      console.log('No type information returned:', JSON.stringify(data, null, 2));
    }
  } catch (error) {
    console.error('Error running introspection query:', error);
  }
}

runIntrospectionQuery();
