import type { NextApiRequest, NextApiResponse } from 'next';
import axios from 'axios';
import { v4 as uuidv4 } from 'uuid';
import { CloudWatchLogsClient, PutLogEventsCommand, CreateLogGroupCommand, CreateLogStreamCommand, DescribeLogStreamsCommand } from '@aws-sdk/client-cloudwatch-logs';

// CloudWatch Logs configuration
const AWS_REGION = process.env.MY_AWS_REGION || 'us-east-1';
const CLOUDWATCH_LOG_GROUP = process.env.CLOUDWATCH_LOG_GROUP || '/sphinx-voice-bot';
const CLOUDWATCH_LOG_STREAM = `api-connect-${new Date().toISOString().split('T')[0]}`;

// Create CloudWatch Logs client
let cloudWatchLogsClient: CloudWatchLogsClient | null = null;
let logSequenceToken: string | undefined;

// Initialize CloudWatch Logs client
cloudWatchLogsClient = new CloudWatchLogsClient({
  region: AWS_REGION,
  credentials : {
    accessKeyId: process.env.MY_AWS_ACCESS_KEY_ID || '',
    secretAccessKey: process.env.MY_AWS_SECRET_ACCESS_KEY || ''
  }
});

// Initialize logs if we have a client
if (cloudWatchLogsClient) {
  initializeCloudWatchLogs().catch(err => {
    console.error('Failed to initialize CloudWatch logging:', err);
    // Don't fail the application if CloudWatch setup fails
  });
}

// Custom logger that logs to both console and CloudWatch
const logger = {
  log: async (message: string, ...args: any[]) => {
    // Original console.log
    console.log(message, ...args);
    
    // Send to CloudWatch if client is initialized
    if (cloudWatchLogsClient) {
      await sendToCloudWatch('INFO', message, args);
    }
  },
  error: async (message: string, ...args: any[]) => {
    // Original console.error
    console.error(message, ...args);
    
    // Send to CloudWatch if client is initialized
    if (cloudWatchLogsClient) {
      await sendToCloudWatch('ERROR', message, args);
    }
  }
};

// Initialize CloudWatch log group and stream
async function initializeCloudWatchLogs() {
  if (!cloudWatchLogsClient) return;
  
  try {
    // Check if log group exists, create if it doesn't
    try {
      await cloudWatchLogsClient.send(new CreateLogGroupCommand({
        logGroupName: CLOUDWATCH_LOG_GROUP
      }));
      console.log(`Created log group: ${CLOUDWATCH_LOG_GROUP}`);
    } catch (error: any) {
      // Ignore error if log group already exists
      if (error.name !== 'ResourceAlreadyExistsException') {
        console.error(`Error creating log group: ${error.message}`);
      }
    }
    
    // Check if log stream exists
    try {
      const streamsResponse = await cloudWatchLogsClient.send(new DescribeLogStreamsCommand({
        logGroupName: CLOUDWATCH_LOG_GROUP,
        logStreamNamePrefix: CLOUDWATCH_LOG_STREAM
      }));
      
      // Check if our stream exists in the response
      const streamExists = streamsResponse.logStreams?.some(
        stream => stream.logStreamName === CLOUDWATCH_LOG_STREAM
      );
      
      // If stream doesn't exist, create it
      if (!streamExists) {
        await cloudWatchLogsClient.send(new CreateLogStreamCommand({
          logGroupName: CLOUDWATCH_LOG_GROUP,
          logStreamName: CLOUDWATCH_LOG_STREAM
        }));
        console.log(`Created log stream: ${CLOUDWATCH_LOG_STREAM}`);
      } else {
        // If it exists, we might need to get the sequence token
        const stream = streamsResponse.logStreams?.find(
          stream => stream.logStreamName === CLOUDWATCH_LOG_STREAM
        );
        logSequenceToken = stream?.uploadSequenceToken;
      }
    } catch (error: any) {
      console.error(`Error checking/creating log stream: ${error.message}`);
      throw error; // Re-throw as this is critical
    }
    
    return true;
  } catch (error) {
    console.error('Failed to initialize CloudWatch logs:', error);
    return false;
  }
}

// Helper function to send logs to CloudWatch
async function sendToCloudWatch(level: string, message: string, args: any[]) {
  if (!cloudWatchLogsClient) return;
  
  try {
    const timestamp = new Date().getTime();
    const logMessage = `[${level}] ${message} ${args.length > 0 ? JSON.stringify(args) : ''}`;
    
    const params = {
      logGroupName: CLOUDWATCH_LOG_GROUP,
      logStreamName: CLOUDWATCH_LOG_STREAM,
      logEvents: [
        {
          message: logMessage,
          timestamp
        }
      ],
      sequenceToken: logSequenceToken
    };
    
    try {
      const command = new PutLogEventsCommand(params);
      const response = await cloudWatchLogsClient.send(command);
      logSequenceToken = response.nextSequenceToken;
    } catch (error: any) {
      // If we get a ResourceNotFoundException, try to initialize and retry once
      if (error.name === 'ResourceNotFoundException') {
        const initialized = await initializeCloudWatchLogs();
        if (initialized) {
          // Retry the put operation now that we've created the stream
          const retryCommand = new PutLogEventsCommand({
            ...params,
            sequenceToken: logSequenceToken // May have been updated by initializeCloudWatchLogs
          });
          const response = await cloudWatchLogsClient.send(retryCommand);
          logSequenceToken = response.nextSequenceToken;
        }
      } else {
        throw error; // Re-throw other errors
      }
    }
  } catch (error) {
    // If there's an error with CloudWatch, log to console but don't throw
    // This prevents logging issues from breaking the main functionality
    console.error('Error sending logs to CloudWatch:', error);
  }
}

type ResponseData = {
  room_url?: string;
  token?: string;
  error?: string;
};

// RunPod GraphQL endpoint
const RUNPOD_API_URL = 'https://api.runpod.io/graphql';
const RUNPOD_API_KEY = process.env.RUNPOD_API_KEY;
const DAILY_API_KEY = process.env.DAILY_API_KEY;

// Pod template ID for the Sphinx bot
const TWISTEDTV_TEMPLATE_ID = process.env.NEXT_PUBLIC_RUNPOD_TEMPLATE_ID;

/**
 * Creates a Daily.co room and returns the room URL and token
 */
async function createDailyRoom(): Promise<{ roomUrl: string; token: string }> {
 
  try {
    // Create a new Daily.co room
    const roomResponse = await axios.post(
      'https://api.daily.co/v1/rooms',
      {
        properties: {
          exp: Math.floor(Date.now() / 1000) + 3600, // Expires in 1 hour
          enable_network_ui: false,
          enable_chat: false,
          enable_knocking: false,
          enable_emoji_reactions: false,
          enable_prejoin_ui: false,
          start_audio_off: false,
          start_video_off: true,
        },
      },
      {
        headers: {
          Authorization: `Bearer ${DAILY_API_KEY}`,
          'Content-Type': 'application/json',
        },
      }
    );

    const roomName = roomResponse.data.name;
    const roomUrl = roomResponse.data.url;

    // Create a token for this room
    const tokenResponse = await axios.post(
      'https://api.daily.co/v1/meeting-tokens',
      {
        properties: {
          room_name: roomName,
          exp: Math.floor(Date.now() / 1000) + 3600, // Expires in 1 hour
          is_owner: false,
        },
      },
      {
        headers: {
          Authorization: `Bearer ${DAILY_API_KEY}`,
          'Content-Type': 'application/json',
        },
      }
    );

    return {
      roomUrl,
      token: tokenResponse.data.token,
    };
  } catch (error) {
    await logger.error('Error creating Daily room:', error);
    
    // Provide more specific error messages based on the type of error
    if (axios.isAxiosError(error)) {
      if (error.response) {
        // The request was made and the server responded with a status code outside of 2xx range
        throw new Error(`Failed to create Daily room: ${error.response.status} - ${JSON.stringify(error.response.data)}`);
      } else if (error.request) {
        // The request was made but no response was received
        throw new Error('Failed to create Daily room: No response received from Daily.co API');
      } else {
        // Something happened in setting up the request
        throw new Error(`Failed to create Daily room: ${error.message}`);
      }
    }
    
    throw new Error('Failed to create Daily room');
  }
}

/**
 * Configuration type for RunPod instances
 */
type DatacenterConfig = {
  id: string;
  networkVolumeId: string;
};

type RunPodConfig = {
  gpuTypeId: string;
  minVcpuCount: number;
  minMemoryInGb: number;
};

/**
 * Launches a RunPod instance with the Sphinx bot
 */
async function launchRunPodInstance(roomUrl: string, token: string, ttsConfig?: any): Promise<string> {
  // Array of datacenters with their associated network volumes
  const datacenterConfigs: DatacenterConfig[] = [
    { id: "US-CA-2", networkVolumeId: "2asfjjhdxl" },
    { id: "US-WA-1", networkVolumeId: "z3guhr3kq7"},
    { id: "US-TX-3", networkVolumeId: "753enpqqhg"},
    { id: "US-IL-1", networkVolumeId: "pwsi7066z6" },
    { id: "US-GA-2", networkVolumeId: "oezj4md6us" },
    { id: "CA-MTL-1", networkVolumeId: "220xq1cw3q"},
    { id: "CA-MTL-3", networkVolumeId: "2kqbh7542h"},
    // Add more datacenters as they become available
  ];
  
  // Array of configurations in order of preference
  const podConfigs: RunPodConfig[] = [
    {
      gpuTypeId: "NVIDIA RTX 4000 Ada Generation", // Preferred
      minVcpuCount: 8,
      minMemoryInGb: 24
    },
    {
      gpuTypeId: "NVIDIA RTX 4000 Ada Generation", 
      minVcpuCount: 4,
      minMemoryInGb: 24
    },
    {
      gpuTypeId: "NVIDIA RTX 4000 Ada Generation",
      minVcpuCount: 4,
      minMemoryInGb: 15
    },   
    {
      gpuTypeId: "NVIDIA RTX 6000 Ada Generation",
      minVcpuCount: 4,
      minMemoryInGb: 15
    },
    {
      gpuTypeId: "NVIDIA RTX A4500",
      minVcpuCount: 4,
      minMemoryInGb: 15
    },
    {
      gpuTypeId : "NVIDIA RTX A5000",
      minVcpuCount: 4,
      minMemoryInGb: 15
    },
    {
      gpuTypeId : "NVIDIA A40",
      minVcpuCount: 4,
      minMemoryInGb: 15
    },
    {
      gpuTypeId: "NVIDIA GeForce RTX 4090",
      minVcpuCount: 4,
      minMemoryInGb: 24
    },
    {
      gpuTypeId: "NVIDIA GeForce RTX 4090",
      minVcpuCount: 4,
      minMemoryInGb: 15
    },    
    {
      gpuTypeId: "NVIDIA GeForce RTX 5080", 
      minVcpuCount: 4,
      minMemoryInGb: 24
    },
    {
      gpuTypeId: "NVIDIA GeForce RTX 4080 SUPER",
      minVcpuCount: 4,
      minMemoryInGb: 24
    },
    {
      gpuTypeId: "NVIDIA GeForce RTX 4080",
      minVcpuCount: 4,
      minMemoryInGb: 24
    },
    {
      gpuTypeId: "NVIDIA GeForce RTX 4070 Ti",
      minVcpuCount: 4, 
      minMemoryInGb: 16  // Lower memory requirement for this GPU
    },
    {
      gpuTypeId: "NVIDIA GeForce RTX 3090 Ti",
      minVcpuCount: 4,
      minMemoryInGb: 16  // Lower memory requirement for this GPU
    }
  ];
  
  // Try to launch with the first configuration in the array
  return await attemptRunPodLaunch(roomUrl, token, ttsConfig, podConfigs, datacenterConfigs);
}

/**
 * Helper function that handles the RunPod launch with failover to alternative configurations
 */
async function attemptRunPodLaunch(
  roomUrl: string,
  token: string,
  ttsConfig: any,
  podConfigs: RunPodConfig[],
  datacenterConfigs: DatacenterConfig[]
): Promise<string> {
  if (podConfigs.length === 0) {
    throw new Error('No configurations available to try');
  }

  // Get API keys from environment variables
  const OPENAI_API_KEY = process.env.OPENAI_API_KEY || '';
  
  // Get AWS CloudWatch configuration
  const MY_AWS_ACCESS_KEY_ID = process.env.MY_AWS_ACCESS_KEY_ID || '';
  const MY_AWS_SECRET_ACCESS_KEY = process.env.MY_AWS_SECRET_ACCESS_KEY || '';
  const MY_AWS_REGION = process.env.MY_AWS_REGION || 'us-east-1';
  const CLOUDWATCH_LOG_GROUP = process.env.CLOUDWATCH_LOG_GROUP || '/twistedtv';
  
  // Get Whisper device configuration
  const WHISPER_DEVICE = process.env.WHISPER_DEVICE || 'cuda';
  const REPO_ID = process.env.REPO_ID || '';
  
  // Unique identifier for this instance
  const IDENTIFIER = `pod-${uuidv4()}`;
  
  // TwistedTV uses video clips for responses, not TTS

  // Collect errors for a detailed final message
  const errors: string[] = [];

  // Try each pod configuration
  for (let index = 0; index < podConfigs.length; index++) {
    const currentConfig = podConfigs[index];
    await logger.log(`Trying pod configuration ${index}: ${JSON.stringify(currentConfig)}`);
    
    // For each pod configuration, try all datacenters
    for (const datacenterConfig of datacenterConfigs) {
      try {
        await logger.log(`Attempting to launch pod with config: ${JSON.stringify(currentConfig)} in datacenter: ${datacenterConfig.id}`);
        
        await logger.log('Template ID:', TWISTEDTV_TEMPLATE_ID);
        
        // Escape all values to safely include them in the query string
        const escapeValue = (value: string) => value.replace(/"/g, '\"');
        
        const query = `mutation {
          podFindAndDeployOnDemand(
            input: {
              cloudType: SECURE,
              templateId: "${TWISTEDTV_TEMPLATE_ID}",
              gpuCount: 1,
              volumeInGb: 0,
              containerDiskInGb: 40,
              minVcpuCount: ${currentConfig.minVcpuCount},
              minMemoryInGb: ${currentConfig.minMemoryInGb},
              gpuTypeId: "${currentConfig.gpuTypeId}",
              dataCenterId: "${datacenterConfig.id}",
              networkVolumeId: "${datacenterConfig.networkVolumeId}",
              name: "twistedtv-bot-${IDENTIFIER}",
              env: [
                { key: "DAILY_ROOM_URL", value: "${escapeValue(roomUrl)}" },
                { key: "DAILY_TOKEN", value: "${escapeValue(token)}" },
                { key: "IDENTIFIER", value: "${IDENTIFIER}" },
                { key: "OPENAI_API_KEY", value: "${escapeValue(OPENAI_API_KEY)}" },
                { key: "AWS_ACCESS_KEY_ID", value: "${escapeValue(MY_AWS_ACCESS_KEY_ID)}" },
                { key: "AWS_SECRET_ACCESS_KEY", value: "${escapeValue(MY_AWS_SECRET_ACCESS_KEY)}" },
                { key: "AWS_REGION", value: "${escapeValue(MY_AWS_REGION)}" },
                { key: "CLOUDWATCH_LOG_GROUP", value: "${escapeValue(CLOUDWATCH_LOG_GROUP)}" },
                { key: "WHISPER_DEVICE", value: "${escapeValue(WHISPER_DEVICE)}" },
                { key: "MOUNT_POINT", value: "/workspace" },
                { key: "REPO_ID", value: "${escapeValue(REPO_ID)}" },
              ]
            }
          ) {
            id
          }
        }`;
        
        const runpodApiUrlWithKey = `${RUNPOD_API_URL}?api_key=${RUNPOD_API_KEY}`;
        
        const response = await axios.post(
          runpodApiUrlWithKey,
          { query },
          {
            headers: {
              'Content-Type': 'application/json',
            },
          }
        );
        
        await logger.log('RunPod response:', JSON.stringify(response.data, null, 2));

        // Handle specific "no instances" error
        if (response.data.errors && 
            response.data.errors.length > 0 && 
            response.data.errors[0].message && 
            response.data.errors[0].message.includes("no longer any instances available")) {
          const errorMsg = `No instances available in datacenter ${datacenterConfig.id} for GPU type: ${currentConfig.gpuTypeId}`;
          await logger.error(errorMsg);
          errors.push(errorMsg);
          continue;
        }

        // Handle other API errors
        if (response.data.errors) {
          const errorMessage = response.data.errors[0]?.message || 'Unknown error';
          const errorMsg = `Error deploying pod with config ${index} in datacenter ${datacenterConfig.id}: ${errorMessage}`;
          await logger.error(errorMsg);
          errors.push(errorMsg);
          continue;
        }

        // Successfully deployed pod
        const podId = response.data.data?.podFindAndDeployOnDemand?.id;
        if (podId) {
          await logger.log(`Successfully deployed pod with ID: ${podId} in datacenter ${datacenterConfig.id}`);
          return podId;
        } else {
          const errorMsg = `Pod ID not found in response for config ${index} in datacenter ${datacenterConfig.id}`;
          await logger.error(errorMsg);
          errors.push(errorMsg);
          continue;
        }
      } catch (error: any) {
        const errorMsg = `Failed to deploy with config ${index} in datacenter ${datacenterConfig.id}: ${error.message}`;
        await logger.error(errorMsg);
        errors.push(errorMsg);
        continue;
      }
    }
    
    await logger.log(`All datacenters failed for configuration ${index}, trying next configuration`);
  }

  // If all attempts failed, throw a detailed error
  throw new Error(`No instances available for any configured options. Errors encountered: ${errors.join('; ')}`);
}

/**
 * API handler to create a Daily room and launch a RunPod instance
 */

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse<ResponseData>
) {
  await logger.log('API request received');
  await logger.log('Available environment variables:', Object.keys(process.env).join(', '));
  // Add a timeout to ensure the request doesn't hang indefinitely
  const requestTimeout = setTimeout(async () => {
    if (!res.writableEnded) {
      await logger.error('API request timed out');
      res.status(504).json({ error: 'Request timed out' });
    }
  }, 60000); // 60 second timeout

  try {
    if (req.method !== 'POST') {
      clearTimeout(requestTimeout);
      return res.status(405).json({ error: 'Method not allowed' });
    }

    // Check if API keys are configured
    if (!RUNPOD_API_KEY || !DAILY_API_KEY) {
      clearTimeout(requestTimeout);
      return res.status(500).json({ 
        error: 'API keys not configured. Please set RUNPOD_API_KEY and DAILY_API_KEY environment variables.' 
      });
    }

    // Extract TTS configuration from request body
    const { tts } = req.body || {};
    await logger.log('Received TTS configuration:', tts);
    
    // Create Daily room with error handling
    await logger.log('Creating Daily room...');
    let roomUrl, token;
    try {
      const dailyRoom = await createDailyRoom();
      roomUrl = dailyRoom.roomUrl;
      token = dailyRoom.token;
    } catch (dailyError) {
      await logger.error('Error creating Daily room:', dailyError);
      clearTimeout(requestTimeout);
      return res.status(500).json({ 
        error: 'Failed to create Daily room. Please try again later.'
      });
    }
    
    // Launch RunPod instance with TTS config from request
    await logger.log('Launching RunPod instance...');
    try {
      await launchRunPodInstance(roomUrl, token, tts);
    } catch (runPodError: any) {
      // Check for specific errors that should be reported to the client
      if (runPodError instanceof Error && 
          runPodError.message === 'No instances available for any of the configured options') {
        await logger.error('No RunPod instances available:', runPodError);
        clearTimeout(requestTimeout);
        return res.status(503).json({ 
          error: 'No GPU instances are currently available. Please try again later.'
        });
      }
      
      await logger.error('Error launching RunPod instance:', runPodError);
      clearTimeout(requestTimeout);
      return res.status(500).json({ 
        error: 'Failed to launch instance. Please try again later.'
      });
    }

    // Clear the timeout as we've completed successfully
    clearTimeout(requestTimeout);
    
    // Return connection details to client
    return res.status(200).json({ room_url: roomUrl, token: token});
  } catch (error) {
    // This is a fallback for any unhandled errors
    await logger.error('Unhandled error in connect API:', error);
    
    // Clear the timeout
    clearTimeout(requestTimeout);
    
    // Send a meaningful error message to the client
    if (!res.writableEnded) {
      return res.status(500).json({ 
        error: 'An unexpected error occurred. Please try again later.'
      });
    }
    
    // If we've already started writing the response, we can't send another
    return;
  }
}
