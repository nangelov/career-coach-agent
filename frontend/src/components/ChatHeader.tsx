import React from 'react';
import styled from 'styled-components';

const HeaderContainer = styled.div`
  display: flex;
  align-items: center;
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
  flex: 1;
  justify-content: center;
`;

const Logo = styled.div`
  margin-right: 10px;
  font-size: 24px;
`;

const RightSection = styled.div`
  display: flex;
  gap: 10px;
  margin-left: auto;
`;

const LeftSection = styled.div`
  display: flex;
  gap: 10px;
`;

const Button = styled.button`
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

const PDPButton = styled(Button)`
  background-color: #28a745;
  border-color: #28a745;
  border: 1px solid white;
  border-radius: 4px;
  padding: 5px 10px;
  cursor: pointer;
  font-size: 14px;
  
  &:hover {
    background-color: #218838;
  }
`;

interface ChatHeaderProps {
  onClearChat: () => void;
  onOpenPDP: () => void;
}

const ChatHeader: React.FC<ChatHeaderProps> = ({ onClearChat, onOpenPDP }) => {
  return (
    <HeaderContainer>
      <LeftSection>
        <Button onClick={onClearChat}>New Chat</Button>
      </LeftSection>
      <Title>
        <Logo>👨‍💼</Logo>
        AI CareerCoach
      </Title>
      <RightSection>
        <PDPButton onClick={onOpenPDP}>Generate Personal Development Plan</PDPButton>
      </RightSection>
    </HeaderContainer>
  );
};

export default ChatHeader;