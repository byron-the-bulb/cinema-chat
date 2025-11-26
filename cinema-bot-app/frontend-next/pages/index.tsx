import { useState, useEffect, useCallback, useRef } from 'react';
import Head from 'next/head';
import styles from '@/styles/Home.module.css';

// Import components
import ChatLog, { ChatMessage, MessageType } from '@/components/ChatLog';
import LoadingSpinner from '@/components/LoadingSpinner';
import PiAudioDeviceSelector from '@/components/PiAudioDeviceSelector';

// Generate a truly unique ID for messages
function generateUniqueId() {
  return Date.now().toString() + '-' + Math.random().toString(36).substring(2, 15);
}

// Server URL constants from environment variables
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://172.28.172.5:8765';

// Interface for active room data
interface ActiveRoom {
  room_url: string;
  identifier: string;
  bot_pid: number;
  bot_running: boolean;
  pi_client_pid: number | null;
  video_service_pid: number | null;
  created_at: string;
  status: string;
}

export default function Home() {
  const [statusText, setStatusText] = useState('Checking for active sessions...');
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [isConnecting, setIsConnecting] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [serverUrl, setServerUrl] = useState(API_URL);
  const [currentRoomUrl, setCurrentRoomUrl] = useState<string | null>(null);
  const [conversationStatus, setConversationStatus] = useState<string | null>(null);
  const [sessionIdentifier, setSessionIdentifier] = useState<string | null>(null);
  const [lastSeenMessageCount, setLastSeenMessageCount] = useState(0);
  const lastSeenStatusCountRef = useRef(0);
  const [isUserSpeaking, setIsUserSpeaking] = useState(false);
  const [existingRoom, setExistingRoom] = useState<ActiveRoom | null>(null);

  // Handle server URL change
  const handleServerUrlChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setServerUrl(e.target.value);
  };

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

  const handleStartConnection = useCallback(async () => {
    console.log('Starting Cinema Chat session...');
    setStatusText('Checking for existing sessions...');
    setIsConnecting(true);

    try {
      const baseUrl = serverUrl || API_URL;

      // First, check if there's already an active room
      const roomsResponse = await fetch(`${baseUrl}/rooms`);
      if (roomsResponse.ok) {
        const roomsData = await roomsResponse.json();
        if (roomsData.active_rooms && roomsData.active_rooms.length > 0) {
          const room = roomsData.active_rooms[0];
          setExistingRoom(room);
          setStatusText('Active session already exists');
          addChatMessage('⚠️ An active session already exists. Please stop it first.', 'system');
          setIsConnecting(false);
          return;
        }
      }

      // No existing room, proceed to create new one
      setStatusText('Creating session...');

      const response = await fetch(`${baseUrl}/connect`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          config: [{
            service: 'tts',
            options: [{
              name: 'provider',
              value: 'cartesia'
            }]
          }]
        })
      });

      if (!response.ok) {
        throw new Error(`Failed to create session: ${response.statusText}`);
      }

      const data = await response.json();
      console.log('Session created:', data);

      const roomUrl = data.room_url;
      const token = data.token;
      const identifier = data.identifier;

      if (!roomUrl) {
        throw new Error('No room URL returned from backend');
      }

      setCurrentRoomUrl(roomUrl);
      setSessionIdentifier(identifier);
      setIsConnected(true);
      setExistingRoom(null);
      setStatusText('Session active - Pi client connecting...');
      addChatMessage('Session started successfully', 'system');
      addChatMessage(`Room: ${roomUrl}`, 'system');
      console.log(`Session identifier: ${identifier}`);

      // Start Pi client for this room
      try {
        const startClientResponse = await fetch('/api/start_pi_client', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ roomUrl, token, backendUrl: baseUrl })
        });

        const clientData = await startClientResponse.json();
        if (clientData.success) {
          addChatMessage(`Pi client started (PID: ${clientData.pid})`, 'system');
        } else {
          addChatMessage(`Error: ${clientData.error}`, 'system');
        }
      } catch (error: any) {
        console.error('Error starting Pi client:', error);
        addChatMessage('Warning: Could not start Pi client', 'system');
      }

    } catch (error: any) {
      console.error('Failed to start session:', error);
      setStatusText(`Error: ${error.message}`);
      addChatMessage(`Error: ${error.message}`, 'system');
    } finally {
      setIsConnecting(false);
    }
  }, [serverUrl, addChatMessage]);

  const handleStopConnection = useCallback(async () => {
    console.log('Stopping session...');
    setStatusText('Stopping session...');

    try {
      const baseUrl = serverUrl || API_URL;

      // Determine which room to cleanup
      let roomToCleanup = currentRoomUrl;
      if (!roomToCleanup && existingRoom) {
        roomToCleanup = existingRoom.room_url;
      }

      if (roomToCleanup) {
        // Call backend to cleanup the room and all processes
        const cleanupResponse = await fetch(`${baseUrl}/cleanup-room`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ room_url: roomToCleanup })
        });

        if (cleanupResponse.ok) {
          const result = await cleanupResponse.json();
          console.log('Cleanup result:', result);

          if (result.bot_terminated) {
            addChatMessage('Bot process terminated', 'system');
          }
          if (result.pi_client_terminated) {
            addChatMessage('Pi client terminated', 'system');
          }
          if (result.video_service_terminated) {
            addChatMessage('Video service terminated', 'system');
          }
          if (result.errors && result.errors.length > 0) {
            result.errors.forEach((error: string) => {
              console.warn('Cleanup error:', error);
            });
          }
        } else {
          console.error('Cleanup request failed:', cleanupResponse.statusText);
        }
      }

      // Reset UI state
      setIsConnected(false);
      setCurrentRoomUrl(null);
      setSessionIdentifier(null);
      setLastSeenMessageCount(0);
      lastSeenStatusCountRef.current = 0;
      setIsUserSpeaking(false);
      setExistingRoom(null);
      setStatusText('Ready to start');
      addChatMessage('Session stopped', 'system');

    } catch (error: any) {
      console.error('Failed to stop session:', error);
      setStatusText(`Error stopping: ${error.message}`);
      addChatMessage(`Error: ${error.message}`, 'system');
    }
  }, [serverUrl, currentRoomUrl, existingRoom, addChatMessage]);

  // Check for existing rooms on mount
  useEffect(() => {
    const checkExistingRooms = async () => {
      try {
        const baseUrl = serverUrl || API_URL;
        const response = await fetch(`${baseUrl}/rooms`);
        if (response.ok) {
          const data = await response.json();
          if (data.active_rooms && data.active_rooms.length > 0) {
            const room = data.active_rooms[0];
            setExistingRoom(room);
            setCurrentRoomUrl(room.room_url);
            setSessionIdentifier(room.identifier);
            setIsConnected(true);
            setStatusText('Reconnected to existing session');
            addChatMessage('✓ Found existing session', 'system');
            addChatMessage(`Room: ${room.room_url}`, 'system');
            addChatMessage(`Status: ${room.status}`, 'system');
            if (room.bot_running) {
              addChatMessage(`Bot running (PID: ${room.bot_pid})`, 'system');
            }
            if (room.pi_client_pid) {
              addChatMessage(`Pi client connected (PID: ${room.pi_client_pid})`, 'system');
            }
            if (room.video_service_pid) {
              addChatMessage(`Video service running (PID: ${room.video_service_pid})`, 'system');
            }
          } else {
            setStatusText('Ready to start');
            addChatMessage('Cinema Chat ready', 'system');
          }
        } else {
          setStatusText('Ready to start');
          addChatMessage('Cinema Chat ready', 'system');
        }
      } catch (error) {
        console.error('Error checking for existing rooms:', error);
        setStatusText('Ready to start');
        addChatMessage('Cinema Chat ready', 'system');
      }
    };

    checkExistingRooms();
  }, [serverUrl, addChatMessage]);

  // Poll for conversation updates from backend
  useEffect(() => {
    console.log('[POLLING DEBUG] useEffect triggered', { isConnected, sessionIdentifier, serverUrl });
    if (!isConnected || !sessionIdentifier) {
      console.log('[POLLING DEBUG] Early return - not polling', { isConnected, sessionIdentifier });
      return;
    }
    console.log('[POLLING DEBUG] Starting polling interval');

    const pollInterval = setInterval(async () => {
      try {
        const baseUrl = serverUrl || API_URL;
        // Remove /api suffix if present for this endpoint
        const cleanBaseUrl = baseUrl.replace(/\/api$/, '');
        const url = `${cleanBaseUrl}/conversation-status/${sessionIdentifier}?last_seen=${lastSeenStatusCountRef.current}`;
        console.log('[POLLING DEBUG] Fetching:', url);
        const response = await fetch(url);

        if (!response.ok) {
          console.warn('Failed to fetch conversation status');
          return;
        }

        const data = await response.json();
        console.log('Conversation status:', data);

        // Update conversation status text if available
        if (data.status) {
          setConversationStatus(data.status);
        }

        // Update user speaking state if available
        if (typeof data.user_speaking === 'boolean') {
          setIsUserSpeaking(data.user_speaking);
        }

        // Process messages from the context
        if (data.context && data.context.messages) {
          const messages = data.context.messages;

          // Only add messages we haven't seen yet
          if (messages.length > lastSeenMessageCount) {
            const newMessages = messages.slice(lastSeenMessageCount);

            newMessages.forEach((msg: any) => {
              if (msg.role === 'user') {
                addChatMessage(msg.content || '[User spoke]', 'user');
              } else if (msg.role === 'assistant') {
                addChatMessage(msg.content || '[Bot responded]', 'guide');
              } else if (msg.role === 'system' || msg.type === 'system') {
                addChatMessage(msg.content || msg.text, 'system');
              }
            });

            setLastSeenMessageCount(messages.length);
          }
        }

        // Check for new status messages (reasoning, video selections, etc.)
        console.log('[POLLING DEBUG] Checking for status messages:', {
          hasContext: !!data.context,
          hasStatusMessages: !!(data.context && data.context.status_messages),
          statusMessagesLength: data.context?.status_messages?.length,
          totalMessageCount: data.context?.total_message_count,
          currentLastSeen: lastSeenStatusCountRef.current
        });

        if (data.context && data.context.status_messages) {
          const statusMessages = data.context.status_messages;
          console.log('[POLLING DEBUG] Processing status messages:', statusMessages);
          statusMessages.forEach((msg: string) => {
            console.log('[POLLING DEBUG] Adding status message:', msg);
            addChatMessage(msg, 'system');
          });

          // Update the count of seen status messages
          if (data.context.total_message_count) {
            console.log('[POLLING DEBUG] Updating lastSeenStatusCount from', lastSeenStatusCountRef.current, 'to', data.context.total_message_count);
            lastSeenStatusCountRef.current = data.context.total_message_count;
          } else {
            console.log('[POLLING DEBUG] No total_message_count in response!');
          }
        } else {
          console.log('[POLLING DEBUG] No status messages in response');
        }

      } catch (error) {
        console.error('Error polling conversation status:', error);
      }
    }, 2000);

    return () => clearInterval(pollInterval);
  }, [isConnected, sessionIdentifier, serverUrl, lastSeenMessageCount, addChatMessage]);

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

        {/* Server URL Configuration */}
        <div className={styles.stationNameContainer}>
          <label htmlFor="serverUrl" className={styles.stationNameLabel}>Backend Server URL:</label>
          <input
            type="text"
            id="serverUrl"
            value={serverUrl}
            onChange={handleServerUrlChange}
            className={styles.stationNameInput}
            disabled={isConnected || isConnecting}
            placeholder="http://172.28.172.5:8765/api"
          />
        </div>

        {/* Pi Audio Device Selection */}
        <div className={styles.stationNameContainer}>
          <PiAudioDeviceSelector />
        </div>

        {isConnected && currentRoomUrl && (
          <div className={styles.sessionInfo}>
            <strong>Active Session</strong>
            <div style={{ fontSize: '0.9em', marginTop: '5px' }}>
              {conversationStatus || 'Running'}
            </div>
          </div>
        )}

        <div className={styles.controls}>
          <button
            onClick={handleStartConnection}
            disabled={isConnected || isConnecting}
            className={styles.startButton}
          >
            {isConnecting ? 'Starting...' : 'Start Experience'}
          </button>
          <button
            onClick={handleStopConnection}
            disabled={!isConnected}
            className={styles.stopButton}
          >
            Stop Experience
          </button>
        </div>

        <ChatLog
          messages={chatMessages}
          isWaitingForUser={false}
          isUserSpeaking={isUserSpeaking}
          uiOverride={null}
        />

        {isConnecting && (
          <LoadingSpinner message="Starting Cinema Chat..." />
        )}
      </main>
    </div>
  );
}
