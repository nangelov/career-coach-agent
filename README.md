---
title: Career Coach Agent
emoji: 🧑‍💼
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
python_version: 3.12.3
short_description: "AI career coaching assistant powered by Mixtral-8x7B."
tags:
  - career
  - ai
  - langchain
  - gradio
  - smolagents
  - fastapi
  - coaching
---

# Career Coach Agent 🤖

An AI-powered career coaching assistant built with FastAPI, Gradio UI, LangChain, and SmolaGents. This application provides an interactive interface for career guidance through both a REST API and a web-based UI.

## 🚀 Features

- **Dual Interface**: REST API (FastAPI) and Web UI (Gradio)
- **AI-Powered Responses**: Utilizing Mixtral-8x7B-Instruct-v0.1 model
- **Interactive Chat Interface**: Real-time conversation with the AI agent
- **Multi-tool Integration**: Including webpage visits and time zone conversions
- **ReAct Agent Pattern**: Step-by-step reasoning and tool usage

## 🛠️ Technical Stack

- **Backend Framework**: FastAPI
- **UI Framework**: Gradio with SmolaGents
- **AI Framework**: 
  - LangChain ReAct Agent (Backend) - For structured reasoning and tool usage
  - SmolaGents (UI) - For enhanced agent interactions and chat interface
- **ML Models**: Hugging Face (Mixtral-8x7B-Instruct-v0.1)
- **Additional Key Libraries**:
  - `uvicorn`: ASGI server
  - `torch` & `accelerate`: ML model support
  - `markdownify`: Web content processing
  - `langchain`: AI framework and tools
  - `smolagents`: UI agent framework

## 📋 Prerequisites

- Python 3.8+
- Hugging Face account (for model access)

## ⚙️ Installation

1. Clone the repository:
```bash
git clone https://github.com/nangelov/career-coach-agent.git
cd career-coach-agent
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. (Required) Set up Hugging Face token:
```bash
export HUGGINGFACEHUB_API_TOKEN=your_token_here
```

## 🚀 Running the Application

### Option 1: Complete Application (API + UI)
Run both the FastAPI backend and Gradio UI:
```bash
python main.py
```
This will start:
- FastAPI server on http://localhost:8000
- Gradio UI on http://localhost:7860

### Option 2: API Only
Run just the FastAPI backend:
```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

## 📚 API Documentation

Once the server is running, access the API documentation at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 🔑 Key Endpoints

- `POST /agent/query`: Send queries to the AI agent
- `GET /`: Redirects to Gradio UI

## 🔍 How It Works

The application uses a ReAct (Reasoning and Acting) agent pattern, which follows this structure:
1. **Thought**: The agent reasons about what to do
2. **Action**: The agent decides which tool to use
3. **Observation**: The tool returns a result
4. **Thought**: The agent reasons about the observation
5. **Action**: The agent either uses another tool or provides a final answer

This pattern allows the agent to:
- Use tools in a structured way
- Reason step-by-step about complex problems
- Provide transparent decision-making
- Handle multiple tool interactions

## ⚠️ Important Notes

- The application requires active internet connection for AI model access
- Hugging Face API token is required for model access
- The application uses the Mixtral-8x7B-Instruct-v0.1 model for generating responses
- The UI is built using SmolaGents framework for enhanced agent interactions
- The backend uses LangChain's ReAct agent for structured reasoning and tool usage

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.
