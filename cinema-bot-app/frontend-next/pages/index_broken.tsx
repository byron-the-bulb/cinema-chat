import { useState, useEffect, useCallback, useRef } from 'react';
import Head from 'next/head';
import styles from '@/styles/Home.module.css';
import { RTVIClientProvider, RTVIClientAudio, useRTVIClient } from '@pipecat-ai/client-react';
import { RTVIClient, RTVIEvent } from '@pipecat-ai/client-js';
import { DailyTransport } from '@pipecat-ai/daily-transport';

// Import components
import ChatLog, { ChatMessage, MessageType } from '@/components/ChatLog';
import LoadingSpinner from '@/components/LoadingSpinner';
import AudioDeviceSelector from '@/components/AudioDeviceSelector';

// Import types
import { TTSConfig } from '@/types';

// Generate a truly unique ID for messages
function generateUniqueId() {
  return Date.now().toString() + '-' + Math.random().toString(36).substring(2, 15);
}

// Server URL constants from environment variables
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3000/api';
const CARTESIA_API_KEY = process.env.NEXT_PUBLIC_CARTESIA_API_KEY || '';

// Default TTS configuration (Note: Cinema Chat doesn't use TTS - videos are the bot's voice)
const defaultTtsConfig: TTSConfig = {
  provider: 'cartesia',
  voiceId: 'ec58877e-44ae-4581-9078-a04225d42bd4', // Default voice ID
  model: 'sonic-2-2025-03-07',
  language: 'en',
  speed: 'slow'
};

// Define an interface that extends TTSConfig to include stationName and deviceId
interface ClientConfig extends TTSConfig {
  stationName?: string;
  audioDeviceId?: string;
}

// Function to create a Pipecat client with the given TTS configuration
const createClient = (config: ClientConfig = defaultTtsConfig) => {
  try {
    // Extract TTS config, station name, and audio device ID
    const { stationName, audioDeviceId, ...ttsConfig } = config;
    
    // Create client with basic configuration
    const client = new RTVIClient({
      params: {
        baseUrl: API_URL,
        requestData: {
          tts: ttsConfig,
          stationName // Include stationName in the request data
        },
        endpoints: { connect: process.env.NEXT_PUBLIC_API_ENDPOINT || '/connect' },
      },
      transport: new DailyTransport(),
      enableMic: true
    });
    
    // Log the selected audio device for debugging purposes
    if (audioDeviceId) {
      console.log('Selected audio device ID:', audioDeviceId);
      // Note: The actual device selection happens in the AudioDeviceSelector component
      // when it's rendered within the RTVIClientProvider
    }
    
    return client;
  } catch (error) {
    console.error('Failed to initialize Pipecat client:', error);
    return null;
  }
};

// We'll create the client only when the user starts the conversation
let clientInstance: RTVIClient | null = null;

export default function Home() {
  const [statusText, setStatusText] = useState('Ready to connect');
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [isWaitingForUser, setIsWaitingForUser] = useState(false);
  const [clientInitialized, setClientInitialized] = useState(true); // Always true since we'll create the client on demand
  const [participantId, setParticipantId] = useState<string | undefined>();
  const [conversationStatus, setConversationStatus] = useState<String | null>(null);
  const [isUserSpeaking, setIsUserSpeaking] = useState(false);
  const [uiOverride, setUIOverride] = useState<any | null>(null);
  const [pendingUIOverride, setPendingUIOverride] = useState<any | null>(null);
  const pendingUIOverrideRef = useRef<any | null>(null);
  const [selectedVoiceId, setSelectedVoiceId] = useState(defaultTtsConfig.voiceId);
  const [selectedSpeed, setSelectedSpeed] = useState(defaultTtsConfig.speed);
  const [ttsConfig, setTtsConfig] = useState<TTSConfig>(defaultTtsConfig);
  const [isConnecting, setIsConnecting] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [isWaitingForParticipant, setIsWaitingForParticipant] = useState(false);
  const [stationName, setStationName] = useState('Station 1'); // Default station name
  const [selectedAudioDeviceId, setSelectedAudioDeviceId] = useState<string | undefined>();
  const eventHandlersAttached = useRef(false);
  const initialMessageSent = useRef(false);

  // Handle station name change
  const handleStationNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setStationName(e.target.value);
  };

  // Handle audio device selection
  const handleAudioDeviceSelect = (deviceId: string) => {
    console.log('Audio device selected:', deviceId);
    setSelectedAudioDeviceId(deviceId);
  };

  // Custom setter to log all updates to pendingUIOverride
  const logSetPendingUIOverride = useCallback((newValue: any | null) => {
    setPendingUIOverride((prev: any | null) => {
      console.log('pendingUIOverride updated from:', prev, 'to:', newValue);
      pendingUIOverrideRef.current = newValue; // Update ref synchronously
      return newValue;
    });
  }, []);

  // useEffect to catch any change to pendingUIOverride, including state rebuilds
  useEffect(() => {
    console.log('pendingUIOverride changed to:', pendingUIOverride);
  }, [pendingUIOverride]);

  // Handle voice selection
  const handleVoiceSelect = useCallback((voiceId: string) => {
    console.log('Voice selected:', voiceId);
    setSelectedVoiceId(voiceId);

    // Update the TTS config with the new voice ID
    const newTtsConfig = {
      ...ttsConfig,
      voiceId
    };
    setTtsConfig(newTtsConfig);
  }, [ttsConfig]);

  // Handle speed selection
  const handleSpeedSelect = useCallback((speed: string) => {
    console.log('Speed selected:', speed);
    setSelectedSpeed(speed);

    // Update the TTS config with the new speed
    const newTtsConfig = {
      ...ttsConfig,
      speed
    };
    setTtsConfig(newTtsConfig);
  }, [ttsConfig]);


  const addChatMessage = useCallback((text: string, type: MessageType) => {
    if (!text) return;
    console.log(`Adding ${type} message: ${text}`);
    setChatMessages(prevMessages => {
      const isDuplicate = prevMessages.some(
        msg => msg.text === text && msg.type === type &&
          (new Date().getTime() - msg.timestamp.getTime() < 2000)
      );
      if (isDuplicate) {
        console.log(`Prevented duplicate message: ${text}`);
        return prevMessages;
      }
      const newMessage = {
        id: generateUniqueId(),
        text,
        type,
        timestamp: new Date()
      };
      return [...prevMessages, newMessage];
    });
  }, []);

  // Define event handler functions
  const setupEventHandlers = useCallback((client: RTVIClient) => {
    console.log("Setting up Pipecat event handlers");
    if (eventHandlersAttached.current) {
      return;
    }
    eventHandlersAttached.current = true;

    // Define handler functions for better cleanup
    const handleTextResponse = (text: any) => {
      console.log('Received text response:', text);
      if (text.text) {
        addChatMessage(text.text, 'guide');
      }
    };

    const handleTranscription = (transcript: any) => {
      console.log('Received transcription:', transcript);
      if (transcript.text) {
        addChatMessage(transcript.text, 'user');
        //setUIOverride(null);
      }
    };

    const handleConnected = () => {
      console.log('Connected to server');
      setStatusText('Connected to server');
      setIsConnected(true);
      setIsConnecting(false);
      addChatMessage('Connected to Cinema Chat server', 'system');
      // We're now waiting for a participant to join
      setIsWaitingForParticipant(true);
    };

    const handleDisconnected = () => {
      console.log('Disconnected from server');
      setStatusText('Disconnected from server');
      setUIOverride(null);
      setIsConnected(false);
      setIsConnecting(false);
      setIsWaitingForParticipant(false);
      addChatMessage('Disconnected from the server', 'system');
      setIsWaitingForUser(false);
    };

    const handleServerMessage = (event: any) => {
      console.log('Server message received:', event);
      if (event) {
        // It's either status or trigger or emotion
        if (event.status) {
          addChatMessage(event.status, 'system');
          setConversationStatus(event.status_context?.node || null);

          if (event.ui_override) {
            console.log('UI override received:', event.ui_override);
            logSetPendingUIOverride(event.ui_override);
          }
        } else if (event.trigger === "UIOverride") {
          console.log('UI override trigger received, pendingUIOverride:', pendingUIOverrideRef.current);
          if (pendingUIOverrideRef.current) {
            console.log('Setting UI override:', pendingUIOverrideRef.current);
            setUIOverride(pendingUIOverrideRef.current);
            logSetPendingUIOverride(null);
            setIsWaitingForUser(true);
          }
        } else if (event.trigger === "VideoTrigger") {
          console.log('Video trigger received, empowered_state_data:', event.empowered_state_data);
          if (event.empowered_state_data) {
            // Call the trigger_video API endpoint with the empowered_state_data
            fetch('/api/trigger_video', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
              },
              body: JSON.stringify({
                empowered_state_data: event.empowered_state_data
              })
            }).catch(error => {
              console.error('Error calling trigger_video endpoint:', error);
            });
          }
        } else if (event.trigger === "NeedsHelp") {
          console.log('NeedsHelp trigger received, help_data:', event.help_data);
          if (event.help_data) {
            // Call the needs_help API endpoint with the help data
            fetch('/api/needs_help', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
              },
              body: JSON.stringify({
                help_data: event.help_data
              })
            }).catch(error => {
              console.error('Error calling needs_help endpoint:', error);
            });
            
            // Show help request in chat log with both station name and phase
            const helpMessage = event.help_data.needs_help
              ? `${event.help_data.user} needs help with ${event.help_data.phase}`
              : `Help request resolved for ${event.help_data.user} (${event.help_data.phase})`;
            addChatMessage(helpMessage, 'system');
          }
        }
        // Note: Cinema Chat doesn't use emotion detection - removed Hume AI integration
      }
    };

    const handleError = (error: any) => {
      console.error('Pipecat client error:', error);
      setStatusText(`Error: ${error.message || 'Unknown error'}`);
      addChatMessage(`Error: ${error.message || 'Unknown error'}`, 'system');
      setIsConnecting(false);
      setIsWaitingForParticipant(false);
    };

    const handleBotStoppedSpeaking = () => {
      console.log('Bot stopped speaking');
      if (pendingUIOverrideRef.current) {
        console.log('Setting UI override:', pendingUIOverrideRef.current);
        setUIOverride(pendingUIOverrideRef.current);
        logSetPendingUIOverride(null);
      }
      setIsWaitingForUser(true);
    };

    const handleBotStartedSpeaking = () => {
      console.log('Bot started speaking');
      setIsWaitingForUser(false);
    };

    const handleUserStartedSpeaking = () => {
      console.log('User started speaking');
      setIsWaitingForUser(false);
      setIsUserSpeaking(true);
    };

    const handleUserStoppedSpeaking = () => {
      console.log('User stopped speaking');
      setIsUserSpeaking(false);
    };

    const handleBotConnected = (participant: any) => {
      console.log('Participant joined:', participant);
      if (participant?.id) {
        console.log('Setting participant ID:', participant.id);
        setParticipantId(participant.id);
        // Participant has joined, no longer waiting
        setIsWaitingForParticipant(false);
      }
    };

    const handleBotDisconnected = (participant: any) => {
      console.log('Participant disconnected:', participant);
      if (participant?.id) {
        console.log('Clearing participant ID:', participant.id);
        setParticipantId(undefined);
        addChatMessage('Participant disconnected', 'system');
      }
    };

    // Attach event handlers using RTVIEvent constants
    client.on('connected', handleConnected);
    client.on('disconnected', handleDisconnected);
    client.on(RTVIEvent.ServerMessage, handleServerMessage);
    client.on('error', handleError);
    client.on('botConnected', handleBotConnected);
    client.on('botDisconnected', handleBotDisconnected);
    client.on(RTVIEvent.UserTranscript, handleTranscription);
    client.on(RTVIEvent.BotTranscript, handleTextResponse);
    client.on(RTVIEvent.BotStartedSpeaking, handleBotStartedSpeaking);
    client.on(RTVIEvent.BotStoppedSpeaking, handleBotStoppedSpeaking);
    client.on(RTVIEvent.UserStartedSpeaking, handleUserStartedSpeaking);
    client.on(RTVIEvent.UserStoppedSpeaking, handleUserStoppedSpeaking);

    // Return cleanup function
    return () => {
      console.log("Cleaning up event handlers");
      client.off('connected', handleConnected);
      client.off('disconnected', handleDisconnected);
      client.off(RTVIEvent.ServerMessage, handleServerMessage);
      client.off('error', handleError);
      client.off('botConnected', handleBotConnected);
      client.off('botDisconnected', handleBotDisconnected);
      client.off(RTVIEvent.UserTranscript, handleTranscription);
      client.off(RTVIEvent.BotTranscript, handleTextResponse);
      client.off(RTVIEvent.BotStartedSpeaking, handleBotStartedSpeaking);
      client.off(RTVIEvent.BotStoppedSpeaking, handleBotStoppedSpeaking);
      client.off(RTVIEvent.UserStartedSpeaking, handleUserStartedSpeaking);
      client.off(RTVIEvent.UserStoppedSpeaking, handleUserStoppedSpeaking);
      eventHandlersAttached.current = false;
    };
  }, [addChatMessage, logSetPendingUIOverride]);

  const handleStartConnection = useCallback(() => {
    console.log('Starting connection with TTS config:', ttsConfig, 'station name:', stationName, 'and audio device:', selectedAudioDeviceId);
    setStatusText('Starting connection...');
    setIsConnecting(true);

    // Create a new client with the current TTS configuration, station name, and audio device
    clientInstance = createClient({
      ...ttsConfig,
      stationName, // Add station name to the configuration
      audioDeviceId: selectedAudioDeviceId // Add selected audio device ID
    });

    if (!clientInstance) {
      console.error('Failed to create client');
      setStatusText('Failed to create client');
      setIsConnecting(false);
      return;
    }

    // Set up event handlers for the new client
    const cleanup = setupEventHandlers(clientInstance);

    // Connect the client - this will call our /api/connect endpoint
    clientInstance.connect().catch((err: Error) => {
      console.error('Failed to connect:', err);
      setStatusText(`Connection error: ${err.message}`);
      setIsConnecting(false);

      // Clean up event handlers if connection fails
      if (cleanup) {
        cleanup();
      }

      // Clean up client
      clientInstance = null;
    });
  }, [ttsConfig, setupEventHandlers, stationName, selectedAudioDeviceId]); // Add selectedAudioDeviceId to dependencies

  const handleStopConnection = useCallback(() => {
    if (!clientInstance) return;
    console.log('Stopping connection...');
    setStatusText('Disconnecting...');

    clientInstance.disconnect().catch((err: Error) => {
      console.error('Failed to disconnect:', err);
      setStatusText(`Disconnection error: ${err.message}`);
    });
  }, []);

  // Send welcome message on mount
  useEffect(() => {
    if (!initialMessageSent.current) {
      addChatMessage('Cinema Chat ready', 'system');
      initialMessageSent.current = true;
      console.log("Initial welcome message sent");
    }
  }, [addChatMessage]);

  return (
    <div className={styles.container}>
      <Head>
        <title>Cinema Chat</title>
        <meta name="description" content="Cinema Chat - Conversation through vintage film clips" />
        <link rel="icon" href="/favicon.ico" />
      </Head>

      <main className={styles.main}>
        <h1 className={styles.title}>
          Cinema Chat
        </h1>
        <h3><div id="statusText">{statusText}</div></h3>

        {/* TTS Voice Settings - Removed for Cinema Chat (uses video clips instead of speech) */}
        {/*
        <div className={styles.voiceSettingsContainer}>
          <div className={styles.voiceSelectionContainer}>
            <VoiceSelector
              onVoiceSelect={handleVoiceSelect}
              initialVoiceId={selectedVoiceId}
              apiKey={CARTESIA_API_KEY}
            />
          </div>

          <VoiceSettingsPanel
            selectedSpeed={selectedSpeed}
            selectedEmotions={selectedEmotions}
            onSpeedSelect={handleSpeedSelect}
            onEmotionsChange={handleEmotionsChange}
          />
        </div>
        */}

        {/* Station Name Input - Not needed for Cinema Chat */}
        {/*
        <div className={styles.stationNameContainer}>
          <label htmlFor="stationName" className={styles.stationNameLabel}>Station Name:</label>
          <input
            type="text"
            id="stationName"
            value={stationName}
            onChange={handleStationNameChange}
            className={styles.stationNameInput}
            disabled={isConnected || isConnecting}
          />
        </div>
        */}

        {/* Audio Device Selector (Microphone) */}
        <div className={styles.audioControls}>
          <AudioDeviceSelector 
            insideProvider={false}
            selectedDeviceId={selectedAudioDeviceId}
            onDeviceSelect={handleAudioDeviceSelect}
          />
        </div>

        {participantId ? (
          <>
            <div className={styles.sessionInfo}>
              <strong>Participant in session</strong>
            </div>
            <div className={styles.scriptInfo}>
              <strong>Script stage:</strong> {conversationStatus}
            </div>
          </>
        ) : (
          <div className={styles.noParticipant}>
            No participant active
          </div>
        )}

        <div className={styles.controls}>
          <button
            onClick={handleStartConnection}
            disabled={isConnected || isConnecting}
            className={styles.startButton}
          >
            {isConnecting ? 'Connecting...' : 'Start Experience'}
          </button>
          <button
            onClick={handleStopConnection}
            disabled={!isConnected}
            className={styles.stopButton}
          >
            Stop Experience
          </button>
        </div>

        {clientInstance ? (
          <RTVIClientProvider client={clientInstance}>
            {/* Show the internal audio selector when connected */}
            <div className={styles.audioControls}>
              <AudioDeviceSelector 
                insideProvider={true} 
                selectedDeviceId={selectedAudioDeviceId} 
              />
            </div>
            <RTVIClientAudio />
            <ChatLog
              messages={chatMessages}
              isWaitingForUser={isWaitingForUser}
              isUserSpeaking={isUserSpeaking}
              uiOverride={uiOverride}
            />
          </RTVIClientProvider>
        ) : (
          <ChatLog
            messages={chatMessages}
            isWaitingForUser={isWaitingForUser}
            isUserSpeaking={isUserSpeaking}
            uiOverride={uiOverride}
          />
        )}

        {/* 
        Emotion Tracker Component - Keeping component in project but not displaying it
        {isConnected && (
          <EmotionTracker emotionData={emotionData} />
        )}
        */}

        {(isConnecting || isWaitingForParticipant) && (
          <LoadingSpinner message="Connecting to Cinema Chat..." />
        )}
      </main>
    </div>
  );
}
