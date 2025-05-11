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

- **Unified Interface**: Combined FastAPI and Gradio UI on a single port (7860)
- **AI-Powered Responses**: Utilizing Mixtral-8x7B-Instruct-v0.1 model
- **Interactive Chat Interface**: Real-time conversation with the AI agent
- **Multi-tool Integration**: Including webpage visits and time zone conversions
- **ReAct Agent Pattern**: Step-by-step reasoning and tool usage

## 🛠️ Technical Stack

- **Backend Framework**: FastAPI (mounted with Gradio)
- **UI Framework**: Gradio with SmolaGents
- **AI Framework**: 
  - LangChain ReAct Agent (Backend) - For structured reasoning and tool usage
  - SmolaGents (UI) - For enhanced agent interactions and chat interface
- **ML Models**: Hugging Face (Mixtral-8x7B-Instruct-v0.1)
- **Additional Key Libraries**:
  - `uvicorn`: ASGI server
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

5. Run the application:
```bash
python main.py
```

The application will be available at:
- Main UI: http://localhost:7860
- API Documentation: http://localhost:7860/docs/

## 🌐 Hugging Face Spaces Deployment

This application is specifically designed to work with Hugging Face Spaces:
- Uses a single port (7860) as required by Spaces
- Combines FastAPI and Gradio on the same port
- API documentation is accessible at `/docs/` on the same port
- All functionality works within Spaces' constraints

## 📚 API Documentation

The API documentation is available at `/docs/` on the same port as the main application (7860). This unified setup ensures compatibility with Hugging Face Spaces while maintaining all functionality.

## 🔑 Key Endpoints

All endpoints are available on port 7860:
- `/`: Main Gradio UI
- `/docs/`: API Documentation
- `/agent/query`: Send queries to the AI agent

## 🔍 How It Works

The application uses a ReAct (Reasoning and Acting) agent pattern, which follows this structure:
1. **Thought**: The agent reasons about what to do
2. **Action**: The agent decides which tool to use
3. **Observation**: The tool returns a result
4. **Thought**: The agent reasons about the observation
5. **Action**: The agent either uses another tool or provides a final answer

## ⚠️ Important Notes

- The application requires active internet connection for AI model access
- Hugging Face API token is required for model access
- All services run on port 7860 to comply with Hugging Face Spaces requirements
- The UI and API are served from the same port for better integration

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.
