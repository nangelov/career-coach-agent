export interface Message {
  role: 'user' | 'assistant';
  content: string;
  thread_id?: string;
}

export interface ChatResponse {
  status: string;
  thread_id: string;
  response: string;
  full_thought_process?: string;
}

export interface PDPResponse {
  status: string;
  message: string;
  pdp: string;
  filename: string;
  career_goal: string;
  target_date: string;
}

export interface FeedbackFormData {
  contact: string;
  feedback: string;
}

export interface FeedbackResponse {
  status: string;
  message: string;
}