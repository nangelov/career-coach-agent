# Career Coach Agent 🤖

An AI-powered career coaching assistant built with FastAPI, Gradio UI, and the SmolaGents framework. This application provides an interactive interface for career guidance through both a REST API and a web-based UI.

## 🚀 Features

- **Dual Interface**: REST API (FastAPI) and Web UI (Gradio)
- **Google Calendar Integration**: Create and manage calendar events
- **AI-Powered Responses**: Utilizing Qwen2.5-Coder-32B-Instruct model
- **Interactive Chat Interface**: Real-time conversation with the AI agent
- **Multi-tool Integration**: Including webpage visits, time zone conversions, and calendar management

## 🛠️ Technical Stack

- **Backend Framework**: FastAPI
- **UI Framework**: Gradio
- **AI Framework**: SmolaGents
- **ML Models**: Transformers (Qwen2.5-Coder-32B-Instruct)
- **Authentication**: Google OAuth2 for Calendar integration
- **Additional Key Libraries**:
  - `google-auth` & `google-auth-oauthlib`: Google Calendar integration
  - `uvicorn`: ASGI server
  - `torch` & `accelerate`: ML model support
  - `pandas`: Data handling
  - `duckduckgo_search`: Web search capabilities

## 📋 Prerequisites

- Python 3.8+
- Google Cloud Console account
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

4. Set up Google Cloud Project and Credentials:
   
   a. Go to [Google Cloud Console](https://console.cloud.google.com/)
   b. Create a new project or select an existing one
   c. Enable the Google Calendar API:
      - Go to "APIs & Services" > "Library"
      - Search for "Google Calendar API"
      - Click "Enable"
   
   d. Create OAuth 2.0 credentials:
      - Go to "APIs & Services" > "Credentials"
      - Click "Create Credentials" > "OAuth client ID"
      - Select "Desktop app" as application type
      - Give it a name (e.g., "Career Coach Agent")
      - Click "Create"
      - Download the credentials (this will be your `credentials.json`)
   
   e. Place the downloaded `credentials.json` in the project root directory

5. (Optional) Set up Hugging Face token:
```bash
export HF_READ_TOKEN=your_token_here
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
- `POST /calendar/create-event`: Create Google Calendar events
- `POST /google/connect`: Connect Google account
- `GET /`: Redirects to Gradio UI

## 🔐 First-Time Google Calendar Setup

When you first run the application and try to use Google Calendar features:

1. The application will prompt you to authenticate
2. A browser window will open asking you to sign in to your Google account
3. You may see a warning that the app is "unverified" - click "Advanced" and "Go to [Your App Name] (unsafe)"
4. Grant the requested Calendar permissions
5. The application will save the authentication token locally as `token.pickle` for future use

## ⚠️ Important Notes

- The application requires active internet connection for AI model access
- Some features may require Hugging Face API token for full functionality
- Google Calendar integration will work in "unverified app" mode for development
- For production use, you should verify your app with Google

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.
