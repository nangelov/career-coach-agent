import React, { useState, useEffect, useRef } from 'react';
import styled from 'styled-components';
import axios from 'axios';
import ChatHeader from './ChatHeader';
import ChatWindow from './ChatWindow';
import ChatInput from './ChatInput';
import PDPDialog, { PDPFormData } from './PDPDialog';
import SendFeedback from './SendFeedback';
import ChatFooter from './ChatFooter';
import { Message, ChatResponse, FeedbackFormData } from '../types';

// Declare gtag on the Window object to resolve TypeScript error
declare global {
  interface Window {
    gtag?: (...args: any[]) => void;
  }
}

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
  const [isPDPDialogOpen, setIsPDPDialogOpen] = useState(false);
  const [isSendFeedbackDialogOpen, setIsSendFeedbackDialogOpen] = useState(false);
  const cancelTokenRef = useRef<AbortController | null>(null);

  // Add welcome message when component mounts
  useEffect(() => {
    setMessages([
      {
        role: 'assistant',
        content: 'Hello! I\'m AI CareerCoach, your personal career development assistant. How can I help you today?'
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
    
    if (window.gtag) {
      window.gtag('event', 'click-send-message', {
        event_category: 'ChatBot',
        event_label: 'SendMessage',
        value: 1,
      });
    }

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
        content: 'Hello! I\'m AI CareerCoach, your personal career development assistant. How can I help you today?'
      }
    ]);
    setThreadId(null);
  };

  const openPDPDialog = () => {
    setIsPDPDialogOpen(true);
  };

  const closePDPDialog = () => {
    setIsPDPDialogOpen(false);
  };

  const handlePDPSubmit = async (formData: PDPFormData) => {
    // Add chat message showing PDP generation details
    const pdpMessage: Message = {
      role: 'user',
      content: `Generating PDP from:
  CV: ${formData.cvFile?.name || 'No file'}
  Career Goal: ${formData.careerGoal}
  Additional Context: ${formData.additionalContext || 'None provided'}
  Target Date: ${formData.targetDate}`
    };
    
    setMessages(prev => [...prev, pdpMessage]);
    
    // Add loading message
    const loadingMessage: Message = {
      role: 'assistant',
      content: 'Generating your Personal Development Plan... This may take a few moments.'
    };
    
    setMessages(prev => [...prev, loadingMessage]);
    setIsLoading(true);
  
    try {
      const data = new FormData();
      if (formData.cvFile) {
        data.append('file', formData.cvFile);
      }
      data.append('career_goal', formData.careerGoal);
      data.append('additional_context', formData.additionalContext);
      data.append('target_date', formData.targetDate);
  
      const response = await fetch('/pdp-generator', {
        method: 'POST',
        body: data,
      });
  
      if (response.ok) {
        // Get the filename from the response headers
        const contentDisposition = response.headers.get('Content-Disposition');
        const filename = contentDisposition 
          ? contentDisposition.split('filename=')[1].replace(/"/g, '')
          : 'PDP.pdf';
  
        // Create blob and download
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
        
        // Add success message to chat
        const successMessage: Message = {
          role: 'assistant',
          content: `✅ Your Personal Development Plan has been generated successfully and downloaded as "${filename}"! 
  
  The PDP includes:
  - Current skills assessment based on your CV
  - Skills gap analysis for your career goal
  - Learning objectives and milestones
  - Recommended training and development
  - Timeline and action steps
  - Progress tracking and KPIs
  
  You can now review your personalized development plan and start working towards your career goals!`
        };
        
        setMessages(prev => [...prev.slice(0, -1), successMessage]); // Replace loading message
      } else {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Failed to generate PDP');
      }
    } catch (error) {
      console.error('Error generating PDP:', error);
      
      // Add error message to chat
      const errorMessage: Message = {
        role: 'assistant',
        content: `❌ Sorry, I encountered an error while generating your PDP: ${error instanceof Error ? error.message : 'Unknown error'}. Please try again.`
      };
      
      setMessages(prev => [...prev.slice(0, -1), errorMessage]); // Replace loading message
    } finally {
      setIsLoading(false);
    }
  };

  // The pdpDialog function as requested
  const pdpDialog = () => {
    openPDPDialog();
  };

  const closeSendFeedbackDialog = () => {
    setIsSendFeedbackDialogOpen(false);
  };

  const handleSendFeedbackSubmit = async (data: FeedbackFormData) => {
    if (window.gtag) {
      window.gtag('event', 'click-send-feedback', {
        event_category: 'ChatBot',
        event_label: 'SendFeedback',
        value: 1,
      });
    }
    try {
      console.log('Sending feedback data:', JSON.stringify(data));
      const url = new URL('/agent/feedback', window.location.origin);
      url.searchParams.append('contact', data.contact);
      url.searchParams.append('feedback', data.feedback);

      const response = await fetch(url.toString(), {
        method: 'POST'
      });

      if (!response.ok) {
        throw new Error('Failed to submit feedback');
      }

      alert('Thank you for your feedback!');
    } catch (error) {
      console.error('Error submitting feedback:', error);
      alert('Failed to submit feedback. Please try again later.');
    }
  };

  return (
    <ChatContainer>
      <ChatHeader 
        onClearChat={clearChat} 
      />
      <ChatWindow 
        messages={messages} 
        isLoading={isLoading} 
      />
      <ChatInput 
        onSendMessage={sendMessage} 
        onCancelRequest={cancelRequest}
        isLoading={isLoading}
      />
      <ChatFooter
        onOpenFeedback={() => setIsSendFeedbackDialogOpen(true)}
        onOpenPDP={pdpDialog}
      />
      <SendFeedback 
        isOpen={isSendFeedbackDialogOpen}
        onClose={closeSendFeedbackDialog}
        onSubmit={handleSendFeedbackSubmit}
      />
      <PDPDialog
        isOpen={isPDPDialogOpen}
        onClose={closePDPDialog}
        onSubmit={handlePDPSubmit}
      />
    </ChatContainer>
  );
};

export default ChatBot;