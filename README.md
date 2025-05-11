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

# Career Coach AI Assistant

A FastAPI and Gradio-based AI assistant that helps users with career development, powered by Mixtral-8x7B-Instruct and LangChain.

## Features

- Interactive chat interface built with Gradio
- Career-focused AI assistant using Mixtral-8x7B-Instruct model
- FastAPI backend with RESTful endpoints
- LangChain integration for advanced prompt handling and tool usage
- System prompts and templates managed through YAML configuration

## Project Structure

```
career-coach-agent/
├── app.py              # Main FastAPI application with agent setup
├── Gradio_UI.py        # Gradio interface implementation
├── prompts.yaml        # System prompts and templates
├── main.py            # Application entry point
└── README.md          # This file
```

## Requirements

- Python 3.12+
- FastAPI
- Gradio
- LangChain
- Hugging Face Hub API token

## Environment Variables

Required environment variables:
```bash
HUGGINGFACEHUB_API_TOKEN=your_huggingface_token
```

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd career-coach-agent
```

2. Install dependencies:
```bash
pip install fastapi gradio langchain langchain_huggingface pydantic python-multipart uvicorn
```

3. Set up your Hugging Face API token as an environment variable.

## Running the Application

Start the application:
```bash
uvicorn main:app --reload
```

The application will be available at:
- Web Interface: http://localhost:8000
- API Documentation: http://localhost:8000/docs
- Alternative API Documentation: http://localhost:8000/redoc

## API Endpoints

### `/agent/query` (POST)
Submit queries to the AI assistant.

Request body:
```json
{
    "query": "string",
    "thread_id": "string (optional)",
    "context": {} (optional)
}
```

## Features

### AI Assistant
- Career planning and goal setting
- Professional development advice
- Job search strategies
- Skill development recommendations
- Industry insights and trends

### Technical Features
- Real-time chat interface
- Timezone-aware responses
- Session management
- Error handling
- CORS support
- Interactive documentation

## Architecture

- **FastAPI**: Handles HTTP requests and API endpoints
- **Gradio**: Provides the web interface
- **LangChain**: Manages the AI agent and tools
- **Mixtral-8x7B-Instruct**: Powers the AI responses
- **YAML Configuration**: Manages system prompts and templates

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

[Add your license here]
