import React, { useRef, useEffect, useState } from 'react';
import { useRTVIClient } from '@pipecat-ai/client-react';
import { v4 as uuidv4 } from 'uuid';
import styles from '@/styles/ChatLog.module.css';
import { RTVIMessage } from '@pipecat-ai/client-js';

// Message types
export type MessageType = 'system' | 'user' | 'guide' | 'status';

// Chat message interface
export interface ChatMessage {
  id: string;
  text: string;
  type: MessageType;
  timestamp: Date;
}

interface ChatLogProps {
  messages: ChatMessage[];
  isWaitingForUser: boolean;
  isUserSpeaking: boolean;
  uiOverride: any | null;
}

const ChatLog: React.FC<ChatLogProps> = ({ messages, isWaitingForUser, isUserSpeaking, uiOverride }) => {
  const chatEndRef = useRef<HTMLDivElement>(null);
  const uiOverrideRef = useRef<HTMLDivElement>(null);
  const client = useRTVIClient();
  const [selectedOption, setSelectedOption] = useState('');
  
  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (chatEndRef.current) {
      chatEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  // Scroll to UI override when it appears
  useEffect(() => {
    if (uiOverride && uiOverrideRef.current) {
      uiOverrideRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [uiOverride]);

  const handleButtonClick = async () => {
    if (!client) {
      console.error('RTVI client not available for UI override action');
      return;
    }
    
    if (uiOverride?.type === 'button') {
      console.log('Sending uiOverride action:', uiOverride);
      try {
        const action = await client.action({
          service: 'conversation',
          action: 'uioverride_response',
          arguments: [
            { name: 'message', value: uiOverride.action_text }
          ]
        });
        console.log('UI override action response:', action);
      } catch (error) {
        console.error('Error sending UI override action:', error);
      }
    }
  };

  const handleListSelection = async () => {
    if (!client) {
      console.error('RTVI client not available for UI override action');
      return;
    }
    
    if (uiOverride?.type === 'list' && selectedOption) {
      console.log('Sending list selection uiOverride action:', selectedOption);
      try {
        const action = await client.action({
          service: 'conversation',
          action: 'uioverride_response',
          arguments: [
            { name: 'message', value: selectedOption }
          ]
        });
        console.log('UI override action response:', action);
        setSelectedOption(''); // Reset selection after submission
      } catch (error) {
        console.error('Error sending UI override action:', error);
      }
    }
  };

  return (
    <div className={styles.chatLog}>
      <div className={styles.chatHeader}>
        <h2>Conversation Log</h2>
        {isWaitingForUser && (
          <div className={styles.waitingIndicator}>
            Waiting for your response...
          </div>
        )}
        {isUserSpeaking && (
          <div className={styles.speakingIndicator}>
            Speaking detected...
          </div>
        )}
      </div>

      <div className={styles.chatMessages}>
        {messages.map((message) => (
          <div 
            key={message.id} 
            className={`${styles.chatMessage} ${styles[`message${message.type.charAt(0).toUpperCase() + message.type.slice(1)}`]}`}
          >
            <div className={styles.messageHeader}>
              <span className={styles.messageType}>
                {message.type === 'user' ? 'Participant' :
                 message.type === 'guide' ? (
                   message.text.startsWith('[REASONING]') ? 'Reasoning' :
                   message.text.startsWith('[SEARCH RESULTS]') ? 'Search Results' :
                   message.text.startsWith('[VIDEO:') ? 'Video' :
                   'Cinema Chat'
                 ) :
                 message.type === 'system' ? 'System' : 'Status'}
              </span>
              <span className={styles.messageTime}>
                {message.timestamp.toLocaleTimeString()}
              </span>
            </div>
            <div className={styles.messageContent}>{message.text}</div>
          </div>
        ))}
        {uiOverride && (
          <div className={styles.uiOverrideContainer} ref={uiOverrideRef}>
            {uiOverride.type === 'button' && (
              <div>
                <p>{uiOverride.prompt}</p>
                <button onClick={handleButtonClick}>{uiOverride.action_text}</button>
              </div>
            )}
            {uiOverride.type === 'list' && (
              <div>
                <p>{uiOverride.prompt}</p>
                <select 
                  value={selectedOption} 
                  onChange={(e) => setSelectedOption(e.target.value)}
                >
                  <option value="">Select an option</option>
                  {uiOverride.options.map((option: string, index: number) => (
                    <option key={index} value={option}>{option}</option>
                  ))}
                </select>
                <button onClick={handleListSelection} disabled={!selectedOption}>
                  Submit
                </button>
              </div>
            )}
          </div>
        )}
        <div ref={chatEndRef} />
      </div>
    </div>
  );
};

export default ChatLog;
