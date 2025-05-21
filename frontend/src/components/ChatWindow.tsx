import React, { useEffect, useRef } from 'react';
import styled from 'styled-components';
import ChatMessage from './ChatMessage';
import { Message } from '../types';

const WindowContainer = styled.div`
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  background-color: white;
`;

const LoadingIndicator = styled.div`
  display: flex;
  justify-content: flex-start;
  margin-bottom: 10px;
  
  .dot {
    width: 8px;
    height: 8px;
    margin: 0 4px;
    background-color: #ccc;
    border-radius: 50%;
    animation: pulse 1.5s infinite;
  }
  
  .dot:nth-child(2) {
    animation-delay: 0.3s;
  }
  
  .dot:nth-child(3) {
    animation-delay: 0.6s;
  }
  
  @keyframes pulse {
    0%, 100% {
      opacity: 0.4;
    }
    50% {
      opacity: 1;
    }
  }
`;

interface ChatWindowProps {
  messages: Message[];
  isLoading: boolean;
}

const ChatWindow: React.FC<ChatWindowProps> = ({ messages, isLoading }) => {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  return (
    <WindowContainer>
      {messages.map((message, index) => (
        <ChatMessage key={index} message={message} />
      ))}
      
      {isLoading && (
        <LoadingIndicator>
          <div className="dot"></div>
          <div className="dot"></div>
          <div className="dot"></div>
        </LoadingIndicator>
      )}
      
      <div ref={messagesEndRef} />
    </WindowContainer>
  );
};

export default ChatWindow;