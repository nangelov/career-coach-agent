import React, { useState, FC, ChangeEvent, DragEvent, MouseEvent } from 'react';
import styled from 'styled-components';

// Declare gtag on the Window object to resolve TypeScript error
declare global {
  interface Window {
    gtag?: (...args: any[]) => void;
  }
}

const DialogOverlay = styled.div`
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
`;

const DialogContainer = styled.div`
  background: white;
  border-radius: 8px;
  padding: 24px;
  width: 90%;
  max-width: 600px;
  max-height: 80vh;
  overflow-y: auto;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);
`;

const DialogHeader = styled.div`
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  padding-bottom: 10px;
  border-bottom: 1px solid #eee;
`;

const DialogTitle = styled.h2`
  margin: 0;
  color: #333;
  font-size: 24px;
`;

const CloseButton = styled.button`
  background: none;
  border: none;
  font-size: 24px;
  cursor: pointer;
  color: #666;
  
  &:hover {
    color: #333;
  }
`;

const FormGroup = styled.div`
  margin-bottom: 20px;
`;

const Label = styled.label`
  display: block;
  margin-bottom: 8px;
  font-weight: 600;
  color: #333;
`;

const FileUploadArea = styled.div`
  border: 2px dashed #ddd;
  border-radius: 8px;
  padding: 20px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.3s;
  
  &:hover {
    border-color: #0084ff;
  }
  
  &.dragover {
    border-color: #0084ff;
    background-color: #f8f9fa;
  }
`;

const FileInput = styled.input`
  display: none;
`;

const TextArea = styled.textarea`
  width: 100%;
  min-height: 80px;
  padding: 12px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-family: inherit;
  font-size: 14px;
  resize: vertical;
  box-sizing: border-box;
  
  &:focus {
    outline: none;
    border-color: #0084ff;
  }
`;

const DateInput = styled.input`
  width: 100%;
  padding: 12px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-family: inherit;
  font-size: 14px;
  box-sizing: border-box;
  
  &:focus {
    outline: none;
    border-color: #0084ff;
  }
`;

const ButtonGroup = styled.div`
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  margin-top: 24px;
`;

const Button = styled.button`
  padding: 10px 20px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
  transition: background-color 0.3s;
`;

const CancelButton = styled(Button)`
  background-color: #6c757d;
  color: white;
  
  &:hover {
    background-color: #5a6268;
  }
`;

const SubmitButton = styled(Button)`
  background-color: #0084ff;
  color: white;
  
  &:hover {
    background-color: #0056b3;
  }
  
  &:disabled {
    background-color: #ccc;
    cursor: not-allowed;
  }
`;

const FileName = styled.div`
  margin-top: 8px;
  font-size: 14px;
  color: #666;
`;

interface PDPDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (data: PDPFormData) => void;
}

export interface PDPFormData {
  cvFile: File | null;
  careerGoal: string;
  additionalContext: string;
  targetDate: string;
}

const PDPDialog: FC<PDPDialogProps> = ({ isOpen, onClose, onSubmit }) => {
  const [formData, setFormData] = useState<PDPFormData>({
    cvFile: null,
    careerGoal: '',
    additionalContext: '',
    targetDate: ''
  });

  const [dragOver, setDragOver] = useState(false);

  if (!isOpen) return null;

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file && file.type === 'application/pdf') {
      setFormData((prev: PDPFormData) => ({ ...prev, cvFile: file }));
    } else {
      alert('Please select a PDF file');
    }
  };

  const handleDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragOver(false);
    
    const file = event.dataTransfer.files[0];
    if (file && file.type === 'application/pdf') {
      setFormData((prev: PDPFormData) => ({ ...prev, cvFile: file }));
    } else {
      alert('Please select a PDF file');
    }
  };

  const handleDragOver = (event: DragEvent) => {
    event.preventDefault();
    setDragOver(true);
  };

  const handleDragLeave = () => {
    setDragOver(false);
  };

  const handleSubmit = () => {
    if (!formData.cvFile || !formData.careerGoal.trim() || !formData.targetDate) {
      alert('Please fill in all required fields');
      return;
    }
    
    // Track Generate PDP button click
    if (window.gtag) {
      window.gtag('event', 'click', {
        'event_category': 'Button',
        'event_label': 'Generate PDP Button - Dialog',
      });
    }
    
    onSubmit(formData);
    onClose();
    
    // Reset form
    setFormData({
      cvFile: null,
      careerGoal: '',
      additionalContext: '',
      targetDate: ''
    });
  };

  const handleOverlayClick = (event: MouseEvent) => {
    if (event.target === event.currentTarget) {
      onClose();
    }
  };

  return (
    <DialogOverlay onClick={handleOverlayClick}>
      <DialogContainer>
        <DialogHeader>
          <DialogTitle>Generate Personal Development Plan</DialogTitle>
          <CloseButton onClick={onClose}>&times;</CloseButton>
        </DialogHeader>

        <FormGroup>
          <Label>Upload your CV in PDF *</Label>
          <FileUploadArea
            className={dragOver ? 'dragover' : ''}
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onClick={() => document.getElementById('cv-upload')?.click()}
          >
            <div>📄 Click to upload or drag and drop your CV (PDF only)</div>
            {formData.cvFile && (
              <FileName>Selected: {formData.cvFile.name}</FileName>
            )}
          </FileUploadArea>
          <FileInput
            id="cv-upload"
            type="file"
            accept=".pdf"
            onChange={handleFileChange}
          />
        </FormGroup>

        <FormGroup>
          <Label>Set your career goal *</Label>
          <TextArea
            placeholder="Describe your career aspirations and goals..."
            value={formData.careerGoal}
            onChange={(e) => setFormData((prev: PDPFormData) => ({ ...prev, careerGoal: e.target.value }))}
          />
        </FormGroup>

        <FormGroup>
          <Label>Any Additional Context required?</Label>
          <TextArea
            placeholder="Any specific skills, industries, or preferences you'd like to mention..."
            value={formData.additionalContext}
            onChange={(e) => setFormData((prev: PDPFormData) => ({ ...prev, additionalContext: e.target.value }))}
          />
        </FormGroup>

        <FormGroup>
          <Label>Goal target date *</Label>
          <DateInput
            type="date"
            value={formData.targetDate}
            onChange={(e) => setFormData((prev: PDPFormData) => ({ ...prev, targetDate: e.target.value }))}
            min={new Date().toISOString().split('T')[0]}
          />
        </FormGroup>

        <ButtonGroup>
          <CancelButton onClick={onClose}>Cancel</CancelButton>
          <SubmitButton onClick={handleSubmit}>Generate PDP</SubmitButton>
        </ButtonGroup>
      </DialogContainer>
    </DialogOverlay>
  );
};

export default PDPDialog;