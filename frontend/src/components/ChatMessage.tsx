import React from 'react';
import styled from 'styled-components';
import { Message } from '../types';

const MessageContainer = styled.div<{ isUser: boolean }>`
  display: flex;
  margin-bottom: 10px;
  justify-content: ${props => props.isUser ? 'flex-end' : 'flex-start'};
`;

const MessageBubble = styled.div<{ isUser: boolean }>`
  max-width: 70%;
  padding: 10px 15px;
  border-radius: 18px;
  background-color: ${props => props.isUser ? '#0084ff' : '#f0f0f0'};
  color: ${props => props.isUser ? 'white' : 'black'};
  text-align: left;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
`;

interface ChatMessageProps {
  message: Message;
}

const ChatMessage: React.FC<ChatMessageProps> = ({ message }) => {
  const isUser = message.role === 'user';
  
  return (
    <MessageContainer isUser={isUser}>
      <MessageBubble isUser={isUser}>
        {message.content}
      </MessageBubble>
    </MessageContainer>
  );
};

export default ChatMessage;