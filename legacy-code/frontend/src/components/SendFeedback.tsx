import React, { useState, FormEvent, ChangeEvent } from 'react';
import styled from 'styled-components';
import { FeedbackFormData } from '../types';

const Overlay = styled.div`
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
`;

const Modal = styled.div`
  background: white;
  padding: 30px;
  border-radius: 8px;
  width: 90%;
  max-width: 500px;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);

  @media screen and (max-width: 768px) {
    padding: 20px;
    width: 95%;
  }

  @media screen and (max-width: 480px) {
    padding: 15px;
    width: 100%;
    margin: 10px;
  }
`;

const Title = styled.h2`
  margin: 0 0 20px 0;
  color: #333;
  font-size: 24px;

  @media screen and (max-width: 768px) {
    font-size: 20px;
    margin-bottom: 15px;
  }

  @media screen and (max-width: 480px) {
    font-size: 18px;
    margin-bottom: 12px;
  }
`;

const Form = styled.form`
  display: flex;
  flex-direction: column;
  gap: 15px;

  @media screen and (max-width: 768px) {
    gap: 12px;
  }

  @media screen and (max-width: 480px) {
    gap: 10px;
  }
`;

const Label = styled.label`
  font-weight: bold;
  color: #555;
  font-size: 16px;

  @media screen and (max-width: 768px) {
    font-size: 14px;
  }

  @media screen and (max-width: 480px) {
    font-size: 13px;
  }
`;

const Input = styled.input`
  padding: 10px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 16px;

  @media screen and (max-width: 768px) {
    padding: 8px;
    font-size: 14px;
  }

  @media screen and (max-width: 480px) {
    padding: 6px;
    font-size: 13px;
  }
`;

const TextArea = styled.textarea`
  padding: 10px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 16px;
  min-height: 100px;
  resize: vertical;

  @media screen and (max-width: 768px) {
    padding: 8px;
    font-size: 14px;
    min-height: 80px;
  }

  @media screen and (max-width: 480px) {
    padding: 6px;
    font-size: 13px;
    min-height: 70px;
  }
`;

const ButtonGroup = styled.div`
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  margin-top: 20px;

  @media screen and (max-width: 768px) {
    gap: 8px;
    margin-top: 15px;
  }

  @media screen and (max-width: 480px) {
    gap: 6px;
    margin-top: 12px;
  }
`;

const Button = styled.button`
  padding: 10px 20px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 16px;

  @media screen and (max-width: 768px) {
    padding: 8px 16px;
    font-size: 14px;
  }

  @media screen and (max-width: 480px) {
    padding: 6px 12px;
    font-size: 13px;
  }
`;

const SubmitButton = styled(Button)`
  background-color: #0084ff;
  color: white;
  
  &:hover {
    background-color: #0073e6;
  }
  
  &:disabled {
    background-color: #ccc;
    cursor: not-allowed;
  }

  @media (hover: none) {
    &:hover {
      background-color: #0084ff;
    }
  }
`;

const CancelButton = styled(Button)`
  background-color: #6c757d;
  color: white;
  
  &:hover {
    background-color: #5a6268;
  }

  @media (hover: none) {
    &:hover {
      background-color: #6c757d;
    }
  }
`;

interface SendFeedbackProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (data: FeedbackFormData) => void;
}

const SendFeedback: React.FC<SendFeedbackProps> = ({ isOpen, onClose, onSubmit }) => {
  const [contact, setContact] = useState('');
  const [feedbackContent, setFeedbackContent] = useState('');

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    onSubmit({
      contact: contact,
      feedback: feedbackContent
    });
    setContact('');
    setFeedbackContent('');
    onClose();
  };

  if (!isOpen) return null;

  return (
    <Overlay onClick={onClose}>
      <Modal onClick={(e: React.MouseEvent) => e.stopPropagation()}>
        <Title>Send Feedback</Title>
        <Form onSubmit={handleSubmit}>
          <div>
            <Label htmlFor="contact">Contact Information (Email/Name):</Label>
            <Input
              id="contact"
              type="text"
              value={contact}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setContact(e.target.value)}
              placeholder="your email or name"
              required
            />
          </div>
          
          <div>
            <Label htmlFor="feedback">Feedback:</Label>
            <TextArea
              id="feedback"
              value={feedbackContent}
              onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setFeedbackContent(e.target.value)}
              placeholder="Please share your feedback, suggestions, or report any issues..."
              required
            />
          </div>
          
          <ButtonGroup>
            <CancelButton type="button" onClick={onClose}>
              Cancel
            </CancelButton>
            <SubmitButton type="submit">
              Send Feedback
            </SubmitButton>
          </ButtonGroup>
        </Form>
      </Modal>
    </Overlay>
  );
};

export default SendFeedback;