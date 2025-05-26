import React, { useState, useEffect, useRef } from 'react';
import styled from 'styled-components';
import axios from 'axios';
import ChatHeader from './ChatHeader';
import ChatWindow from './ChatWindow';
import ChatInput from './ChatInput';
import { Message, ChatResponse } from '../types';

const ChatContainer = styled.div`
  display: flex;
  flex-direction: column;
  height: 100vh;
  max-width: 800px;
  margin: 0 auto;
  border: 1px solid #ddd;
  box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
`;

const ChatBot: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const cancelTokenRef = useRef<AbortController | null>(null);

  // Add welcome message when component mounts
  useEffect(() => {
    setMessages([
      {
        role: 'assistant',
        content: 'Hello! I\'m CareerCoach AI, your personal career development assistant. How can I help you today?'
      }
    ]);
  }, []);

  const cancelRequest = async () => {
    if (cancelTokenRef.current) {
      cancelTokenRef.current.abort();
    }
    
    if (threadId) {
      try {
        await axios.post(`/agent/cancel/${threadId}`);
      } catch (error) {
        console.error('Error cancelling request:', error);
      }
    }
    
    setIsLoading(false);
    
    // Add cancellation message
    setMessages(prev => [
      ...prev,
      {
        role: 'assistant',
        content: 'Request was cancelled.'
      }
    ]);
  };

  const sendMessage = async (content: string) => {
    // Add user message to chat
    const userMessage: Message = { role: 'user', content };
    setMessages(prev => [...prev, userMessage]);
    
    setIsLoading(true);
    
    // Create new abort controller
    cancelTokenRef.current = new AbortController();
    
    try {
      // Send message to API
      const response = await axios.post<ChatResponse>('/agent/query', {
        query: content,
        thread_id: threadId,
        context: {}
      }, {
        signal: cancelTokenRef.current.signal
      });
      
      // Update thread ID
      if (response.data.thread_id) {
        setThreadId(response.data.thread_id);
      }
      
      // Add assistant response to chat
      const assistantMessage: Message = {
        role: 'assistant',
        content: response.data.response,
        thread_id: response.data.thread_id
      };
      
      setMessages(prev => [...prev, assistantMessage]);
    } catch (error) {
      if (axios.isCancel(error)) {
        console.log('Request was cancelled');
        return; // Don't add error message for cancelled requests
      }
      
      console.error('Error sending message:', error);
      
      // Add error message
      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          content: 'Sorry, I encountered an error. Please try again later.'
        }
      ]);
    } finally {
      setIsLoading(false);
      cancelTokenRef.current = null;
    }
  };

  const clearChat = () => {
    setMessages([
      {
        role: 'assistant',
        content: 'Hello! I\'m CareerCoach AI, your personal career development assistant. How can I help you today?'
      }
    ]);
    setThreadId(null);
  };

  return (
    <ChatContainer>
      <ChatHeader onClearChat={clearChat} />
      <ChatWindow messages={messages} isLoading={isLoading} />
      <ChatInput 
        onSendMessage={sendMessage} 
        onCancelRequest={cancelRequest}
        isLoading={isLoading} 
      />
    </ChatContainer>
  );
};

export default ChatBot;