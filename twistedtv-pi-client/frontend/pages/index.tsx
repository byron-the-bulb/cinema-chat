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
    // Safety check: ensure text is actually a string
    if (typeof text === 'object') {
      console.error('[addChatMessage] ERROR: Received object instead of string:', text);
      // Try to extract text from object
      text = (text as any).text || JSON.stringify(text);
    }

    if (!text) {
      console.log('[addChatMessage] Empty text, returning');
      return;
    }
    console.log(`[addChatMessage] Called with type="${type}", text="${text}"`);
    setChatMessages(prevMessages => {
      console.log(`[addChatMessage] Current message count: ${prevMessages.length}`);
      // Only check for exact duplicates in the last 2 messages (immediate duplicates only)
      // This prevents blocking legitimate messages that arrive in batches from polling
      const recentMessages = prevMessages.slice(-2);
      const isDuplicate = recentMessages.some(
        msg => msg.text === text && msg.type === type
      );
      if (isDuplicate) {
        console.log(`[addChatMessage] ❌ PREVENTED DUPLICATE: type="${type}", text="${text}"`);
        return prevMessages;
      }
      // Final safety check - ensure text is a string
      const safeText = typeof text === 'string' ? text : String(text);

      const newMessage = {
        id: generateUniqueId(),
        text: safeText,
        type,
        timestamp: new Date()
      };
      console.log(`[addChatMessage] ✅ ADDING MESSAGE: type="${type}", text="${safeText}"`);
      return [...prevMessages, newMessage];
    });
  }, []);

  const handleStartConnection = useCallback(async () => {
    console.log('Starting Cinema Chat session...');
    setStatusText('Checking for existing sessions...');
    setIsConnecting(true);

    try {
      const baseUrl = serverUrl || API_URL;

      // First, check if there's already an active room (with timeout)
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 5000); // 5 second timeout

      const roomsResponse = await fetch(`${baseUrl}/rooms`, {
        signal: controller.signal
      });
      clearTimeout(timeoutId);

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

      const connectController = new AbortController();
      const connectTimeoutId = setTimeout(() => connectController.abort(), 10000); // 10 second timeout for connection

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
        }),
        signal: connectController.signal
      });
      clearTimeout(connectTimeoutId);

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
      let errorMessage = error.message;
      if (error.name === 'AbortError') {
        errorMessage = 'Server connection timeout - please check server URL and try again';
      } else if (error.message.includes('Failed to fetch')) {
        errorMessage = 'Could not connect to server - please check server URL';
      }
      setStatusText(`Error: ${errorMessage}`);
      addChatMessage(`❌ Error: ${errorMessage}`, 'system');
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

        // Add timeout to prevent hanging on unreachable server
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 3000); // 3 second timeout

        const response = await fetch(`${baseUrl}/rooms`, {
          signal: controller.signal
        });
        clearTimeout(timeoutId);

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
      } catch (error: any) {
        console.error('Error checking for existing rooms:', error);
        setStatusText('Ready to start');
        // Show user-friendly error message if server is not reachable
        if (error.name === 'AbortError') {
          addChatMessage('⚠️ Server connection timeout - check server URL', 'system');
        } else {
          addChatMessage('⚠️ Could not connect to server - check server URL', 'system');
        }
      }
    };

    checkExistingRooms();
  }, [serverUrl, addChatMessage]);

  // Poll for conversation updates from backend
  useEffect(() => {
    console.log('useEffect triggered', { isConnected, sessionIdentifier, serverUrl });
    if (!isConnected || !sessionIdentifier) {
      console.log('Early return - not polling', { isConnected, sessionIdentifier });
      return;
    }
    console.log('Starting polling interval');

    const pollInterval = setInterval(async () => {
      try {
        const baseUrl = serverUrl || API_URL;
        // Remove /api suffix if present for this endpoint
        const cleanBaseUrl = baseUrl.replace(/\/api$/, '');
        const url = `${cleanBaseUrl}/conversation-status/${sessionIdentifier}?last_seen=${lastSeenStatusCountRef.current}`;
        console.log('Fetching:', url);
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
                addChatMessage(msg.content || '[Bot responded]', 'bot');
              } else if (msg.role === 'system' || msg.type === 'system') {
                addChatMessage(msg.content || msg.text, 'system');
              }
            });

            setLastSeenMessageCount(messages.length);
          }
        }

        // Check for new status messages (reasoning, video selections, etc.)
        console.log('Checking for status messages:', {
          hasContext: !!data.context,
          hasStatusMessages: !!(data.context && data.context.status_messages),
          statusMessagesLength: data.context?.status_messages?.length,
          totalMessageCount: data.context?.total_message_count,
          currentLastSeen: lastSeenStatusCountRef.current
        });

        if (data.context && data.context.status_messages) {
          const statusMessages = data.context.status_messages;
          console.log('Processing status messages:', statusMessages);
          statusMessages.forEach((msg: any) => {
            // Handle both old format (string) and new format (object with text + context)
            let messageText: string;
            let messageContext: any = null;

            if (typeof msg === 'string') {
              // Old format: plain string
              messageText = msg;
            } else if (typeof msg === 'object' && msg !== null) {
              // New format: object with text and context
              messageText = msg.text || JSON.stringify(msg);
              messageContext = msg.context || null;
            } else {
              // Fallback: convert to string
              messageText = String(msg);
            }

            console.log('Raw msg object:', JSON.stringify(msg));
            console.log('messageText type:', typeof messageText);
            console.log('messageText value:', messageText);
            console.log('Message context:', messageContext);

            // Determine message type from context metadata (preferred) or text prefix (fallback)
            if (messageContext && messageContext.role === 'user') {
              // Use context metadata to identify user messages
              const transcriptionText = messageContext.text || messageText.replace(/^User: /, '');
              console.log('✅ DETECTED USER MESSAGE (from context):', transcriptionText);
              addChatMessage(transcriptionText, 'user');
            } else if (messageText && typeof messageText === 'string' && messageText.startsWith('User: ')) {
              // Fallback: parse from text prefix if no context available
              const transcriptionText = messageText.substring(6);
              console.log('✅ DETECTED USER MESSAGE (from prefix):', transcriptionText);
              addChatMessage(transcriptionText, 'user');
            } else if (messageText && typeof messageText === 'string' && messageText.startsWith('[REASONING]')) {
              // Bot reasoning messages
              console.log('✅ DETECTED REASONING MESSAGE:', messageText.substring(0, 50));
              addChatMessage(messageText, 'reasoning');
            } else if (messageText && typeof messageText === 'string' && messageText.startsWith('[VIDEO:')) {
              // Video selection messages
              console.log('✅ DETECTED VIDEO MESSAGE:', messageText.substring(0, 50));
              addChatMessage(messageText, 'video');
            } else if (messageText && typeof messageText === 'string' && messageText.startsWith('[SEARCH RESULTS]')) {
              // Search results messages
              console.log('✅ DETECTED SEARCH RESULTS:', messageText.substring(0, 50));
              addChatMessage(messageText, 'bot');
            } else {
              // All other status messages (system notifications, etc.)
              console.log('Adding as system message');
              console.log('About to call addChatMessage with:', { messageText, type: typeof messageText });
              addChatMessage(messageText, 'system');
            }
          });

          // Update the count of seen status messages
          if (data.context.total_message_count) {
            console.log('Updating lastSeenStatusCount from', lastSeenStatusCountRef.current, 'to', data.context.total_message_count);
            lastSeenStatusCountRef.current = data.context.total_message_count;
          } else {
            console.log('No total_message_count in response!');
          }
        } else {
          console.log('No status messages in response');
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
