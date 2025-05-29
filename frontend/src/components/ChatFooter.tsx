import React from 'react';
import styled from 'styled-components';

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
  return (
    <FooterContainer>
      <FeedbackButton onClick={onOpenFeedback}>
        Send Feedback
      </FeedbackButton>
      <PDPButton onClick={onOpenPDP}>
        Generate Personal Development Plan
      </PDPButton>
    </FooterContainer>
  );
};

export default ChatFooter; 