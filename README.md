---
title: Career Coach Agent
emoji: 🧑‍💼
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
python_version: 3.12.3
short_description: "AI career coach powered by Llama-3.3-70B"
tags:
  - career
  - ai
  - langchain
  - fastapi
  - coaching
---

# Career Coach AI Assistant

A FastAPI-based AI assistant that helps users with career development, powered by Llama-3.3-70B-Instruct and LangChain.

## Features

- Interactive chat interface
- Career-focused AI assistant using Llama-3.3-70B-Instruct model
- FastAPI backend with RESTful endpoints
- LangChain integration for advanced prompt handling and tool usage
- System prompts and templates managed through YAML configuration

## Project Structure

```
career-coach-agent/
├── app.py              # Main FastAPI application with agent setup
├── prompts.yaml        # System prompts and templates
├── tools/             # Tool implementations
│   ├── visit_webpage.py    # Web page content fetcher
│   ├── wikipedia_tool.py   # Wikipedia search tool
│   ├── python_repl.py      # Python code execution tool
│   └── internet_search.py  # Internet search tool
└── README.md          # This file
```

## Requirements

- Python 3.12+
- FastAPI
- LangChain
- Hugging Face Hub API token
- Additional dependencies:
  - requests
  - markdownify
  - wikipedia
  - duckduckgo-search

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
pip install fastapi langchain langchain_huggingface pydantic python-multipart uvicorn requests markdownify wikipedia duckduckgo-search
```

3. Set up your Hugging Face API token as an environment variable.

## Running the Application

Start the application:
```bash
uvicorn app:app --reload
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

## Available Tools

The AI assistant has access to the following tools:

1. **Wikipedia Search**
   - Searches Wikipedia for information about topics, people, or concepts
   - Returns relevant summaries and information

2. **Web Page Visitor**
   - Fetches and processes content from web pages
   - Converts HTML to markdown for better readability
   - Handles timeouts and errors gracefully

3. **Python Code Execution**
   - Executes Python code in a safe environment
   - Returns execution results
   - Handles syntax errors and runtime exceptions

4. **Internet Search**
   - Performs web searches using DuckDuckGo
   - Returns relevant search results
   - Useful for finding current information

## Technical Features

- Real-time chat interface
- Conversation memory and context management
- Error handling and graceful degradation
- CORS support
- Interactive API documentation
- Tool execution with proper error handling
- Markdown formatting for better readability

## Architecture

- **FastAPI**: Handles HTTP requests and API endpoints
- **LangChain**: Manages the AI agent and tools
- **Llama-3.3-70B-Instruct**: Powers the AI responses
- **YAML Configuration**: Manages system prompts and templates
- **Tools Integration**: Wikipedia, Web, Python, and Search capabilities

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

[Add your license here]
