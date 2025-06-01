import React from 'react';
import styled from 'styled-components';

// Declare gtag on the Window object to resolve TypeScript error
declare global {
  interface Window {
    gtag?: (...args: any[]) => void;
  }
}

const FooterContainer = styled.div`
  display: flex;
  justify-content: space-around;
  align-items: center;
  padding: 10px;
  background-color: #f5f5f5;
  border-top: 1px solid #ddd;
`;

const Button = styled.button`
  padding: 10px 15px;
  border: none;
  border-radius: 20px;
  cursor: pointer;
  font-size: 16px;
  
  &:hover {
    opacity: 0.9;
  }
`;

const FeedbackButton = styled(Button)`
  background-color: rgb(131, 138, 145);
  color: white;
  align-items: left;
`;

const PDPButton = styled(Button)`
  background-color: #28a745;
  color: white;
  flex: 1;
  align-items: right;
`;

interface ChatFooterProps {
  onOpenFeedback: () => void;
  onOpenPDP: () => void;
}

const ChatFooter: React.FC<ChatFooterProps> = ({ onOpenFeedback, onOpenPDP }) => {
  const handlePDPButtonClick = () => {
    if (window.gtag) {
      window.gtag('event', 'click', {
        event_category: 'ChatFooter',
        event_label: 'PDPButton',
        value: 1,
      });
    }
    onOpenPDP();
  };

  return (
    <FooterContainer>
      <FeedbackButton onClick={onOpenFeedback}>
        Send Feedback
      </FeedbackButton>
      <PDPButton onClick={handlePDPButtonClick}>
        Generate Personal Development Plan
      </PDPButton>
    </FooterContainer>
  );
};

export default ChatFooter;