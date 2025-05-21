import React, { useState } from 'react';
import styled from 'styled-components';

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
`;

interface ChatInputProps {
  onSendMessage: (message: string) => void;
  isLoading: boolean;
}

const ChatInput: React.FC<ChatInputProps> = ({ onSendMessage, isLoading }) => {
  const [message, setMessage] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (message.trim() && !isLoading) {
      onSendMessage(message);
      setMessage('');
    }
  };

  return (
    <InputContainer>
      <form onSubmit={handleSubmit} style={{ display: 'flex', width: '100%' }}>
        <Input
          type="text"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Type your message..."
          disabled={isLoading}
        />
        <SendButton type="submit" disabled={isLoading}>
          {isLoading ? 'Sending...' : 'Send'}
        </SendButton>
      </form>
    </InputContainer>
  );
};

export default ChatInput;