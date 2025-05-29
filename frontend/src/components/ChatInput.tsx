import React, { useState, FormEvent, ChangeEvent } from 'react';
import styled from 'styled-components';
import SendFeedback from './SendFeedback';
import { FeedbackFormData, FeedbackResponse } from '../types';

const InputContainer = styled.div`
  display: flex;
  padding: 10px;
  background-color: #f5f5f5;
  border-top: 1px solid #ddd;
`;

const Input = styled.input`
  flex: 1;
  padding: 10px 15px;
  border: 1px solid #ddd;
  border-radius: 20px;
  font-size: 16px;
  outline: none;
`;

const SendButton = styled.button`
  margin-left: 10px;
  padding: 10px 15px;
  background-color: #0084ff;
  color: white;
  border: none;
  border-radius: 20px;
  cursor: pointer;
  font-size: 16px;
  
  &:hover {
    background-color: #0073e6;
  }
  
  &:disabled {
    background-color: #ccc;
    cursor: not-allowed;
  }
`;

const StopButton = styled.button`
  margin-left: 10px;
  padding: 10px 15px;
  background-color: #ff4444;
  color: white;
  border: none;
  border-radius: 20px;
  cursor: pointer;
  font-size: 16px;
  
  &:hover {
    background-color: #cc0000;
  }
`;

const FeedbackButton = styled.button`
  margin-left: 10px;
  padding: 10px 15px;
  background-color:rgb(131, 138, 145);
  color: white;
  border: none;
  border-radius: 20px;
  cursor: pointer;
  font-size: 16px;
  
  &:hover {
    background-color: #5a6268;
  }
`;

interface ChatInputProps {
  onSendMessage: (message: string) => void;
  onCancelRequest: () => void;
  isLoading: boolean;
  onOpenFeedback: () => void;
}

const ChatInput: React.FC<ChatInputProps> = ({ onSendMessage, onCancelRequest, isLoading, onOpenFeedback }) => {
  const [message, setMessage] = useState('');

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (message.trim() && !isLoading) {
      onSendMessage(message);
      setMessage('');
    }
  };

  return (
    <InputContainer>
      <form onSubmit={handleSubmit} style={{ display: 'flex', width: '100%' }}>
        <FeedbackButton type="button" onClick={onOpenFeedback}>
          Send Feedback
        </FeedbackButton>
        <Input
          type="text"
          value={message}
          onChange={(e: ChangeEvent<HTMLInputElement>) => setMessage(e.target.value)}
          placeholder="Type your message..."
          disabled={isLoading}
        />
        {!isLoading ? (
          <SendButton type="submit" disabled={!message.trim()}>
            Send
          </SendButton>
        ) : (
          <StopButton type="button" onClick={onCancelRequest}>
            Stop
          </StopButton>
        )}      
      </form>
    </InputContainer>
  );
};

export default ChatInput;