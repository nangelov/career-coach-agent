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

# Career Coach Agent

An AI-powered career coaching assistant that helps users create personalized development plans and provides career guidance.

## Project Structure

```
career-coach-agent/
├── app.py              # Main FastAPI application with agent setup
├── main.py            # Application entry point
├── prompts.yaml       # System prompts and templates
├── output_parser.py   # Response parsing and validation
├── frontend/          # React frontend application
│   ├── src/
│   │   ├── components/    # React components
│   │   ├── types/        # TypeScript type definitions
│   │   └── App.tsx       # Main application component
├── tools/             # Tool implementations
│   ├── visit_webpage.py    # Web page content fetcher
│   ├── wikipedia_tool.py   # Wikipedia search tool
│   ├── python_repl.py      # Python code execution tool
│   ├── internet_search.py  # Internet search tool
│   ├── google_jobs_search.py # Google Jobs search tool
│   └── date_and_time.py    # Date and time utilities
├── helpers/           # Helper functions
│   ├── helper.py         # General helper functions
│   └── feedback_handler.py # Feedback processing
└── README.md          # This file
```

## Requirements

### Backend
- Python 3.12+
- FastAPI
- LangChain
- Hugging Face Hub API token
- Additional dependencies:
  - requests
  - markdownify
  - wikipedia
  - duckduckgo-search
  - pytz
  - python-multipart
  - uvicorn

### Frontend
- Node.js 16+
- React
- TypeScript
- Additional dependencies:
  - styled-components
  - axios
  - @types/react
  - @types/styled-components

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

2. Install backend dependencies:
```bash
pip install -r requirements.txt
```

3. Install frontend dependencies:
```bash
cd frontend
npm install
```

4. Set up your Hugging Face API token as an environment variable.

## Running the Application

### Development Mode

1. Start the backend:
```bash
uvicorn main:app --reload
```

2. Start the frontend development server:
```bash
cd frontend
npm start
```

### Production Mode

1. Build the frontend:
```bash
cd frontend
npm run build
```

2. Start the application:
```bash
uvicorn main:app
```

The application will be available at:
- Web Interface: http://localhost:7860
- API Documentation: http://localhost:7860/docs
- Alternative API Documentation: http://localhost:7860/redoc

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

### `/agent/feedback` (POST)
Submit user feedback.

Request body:
```json
{
    "contact": "string",
    "feedback": "string"
}
```

### `/pdp-generator` (POST)
Generate a Personal Development Plan.

Request body:
```json
{
    "file": "PDF file",
    "career_goal": "string",
    "additional_context": "string (optional)",
    "target_date": "string"
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

5. **Google Jobs Search**
   - Searches for job listings on Google Jobs
   - Returns relevant job opportunities
   - Helps with career research

6. **Date and Time**
   - Provides current date and time information
   - Supports multiple timezones
   - Useful for scheduling and planning

## Features

### Frontend
- Modern, responsive UI built with React and TypeScript
- Real-time chat interface with message history
- Personal Development Plan (PDP) generation
- PDF upload and processing
- User feedback system
- Mobile-friendly design

### Backend
- FastAPI-based REST API
- LangChain-powered AI agent
- Conversation memory and context management
- Error handling and graceful degradation
- CORS support
- Interactive API documentation
- Tool execution with proper error handling
- Markdown formatting for better readability

## Architecture

- **Frontend**:
  - React with TypeScript
  - Styled Components for styling
  - Axios for API communication
  - Responsive design for all devices

- **Backend**:
  - FastAPI: Handles HTTP requests and API endpoints
  - LangChain: Manages the AI agent and tools
  - Llama-3.3-70B-Instruct: Powers the AI responses
  - YAML Configuration: Manages system prompts and templates
  - Tools Integration: Wikipedia, Web, Python, Search, and more

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

[Add your license here]
