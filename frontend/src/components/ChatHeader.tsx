import React from 'react';
import styled from 'styled-components';

const HeaderContainer = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 15px 20px;
  background-color: #0084ff;
  color: white;
  font-weight: bold;
  font-size: 18px;
  box-shadow: 0 2px 5px rgba(0, 0, 0, 0.1);
`;

const Title = styled.div`
  display: flex;
  align-items: center;
`;

const Logo = styled.div`
  margin-right: 10px;
  font-size: 24px;
`;

const ClearButton = styled.button`
  background-color: transparent;
  color: white;
  border: 1px solid white;
  border-radius: 4px;
  padding: 5px 10px;
  cursor: pointer;
  font-size: 14px;
  
  &:hover {
    background-color: rgba(255, 255, 255, 0.1);
  }
`;

interface ChatHeaderProps {
  onClearChat: () => void;
}

const ChatHeader: React.FC<ChatHeaderProps> = ({ onClearChat }) => {
  return (
    <HeaderContainer>
      <Title>
        <Logo>👨‍💼</Logo>
        CareerCoach AI
      </Title>
      <ClearButton onClick={onClearChat}>New Chat</ClearButton>
    </HeaderContainer>
  );
};

export default ChatHeader;