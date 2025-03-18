from smolagents import CodeAgent, HfApiModel, load_tool, tool
import datetime 
import pytz
import yaml
from tools.final_answer import FinalAnswerTool
from tools.visit_webpage import VisitWebpageTool
import os
from huggingface_hub import login
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pickle
import os.path

# Import FastAPI dependencies
from fastapi import FastAPI, BackgroundTasks, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from smolagents.agent_types import AgentAudio, AgentImage, AgentText, handle_agent_output_types

# Token authentication for Hugging Face if needed
if os.getenv('HF_READ_TOKEN'):
    login(token=os.getenv('HF_READ_TOKEN'))

SCOPES = ['https://www.googleapis.com/auth/calendar']

def get_google_credentials():
    """Helper function to use Google SSO and get google authentication token."""
    creds = None
    
    # Check if credentials file exists
    check_credentials_file()
    
    # Check if token file exists and load credentials
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    
    # Check if credentials are valid
    if not creds or not creds.valid:
        # If credentials expired but have refresh token, refresh them
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # If no valid credentials, trigger OAuth flow
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json',  # Make sure this file exists with your Google API credentials
                SCOPES,
                redirect_uri='urn:ietf:wg:oauth:2.0:oob'  # This forces a pop-up authorization
            )
            
            # Run the local server auth flow - this opens a browser window
            creds = flow.run_local_server(port=0)
            
            # Save the credentials for next run
            with open('token.pickle', 'wb') as token:
                pickle.dump(creds, token)
    
    return creds

def get_calendar_service():
    """Helper function to authenticate and get Calendar service."""
    creds = get_google_credentials()
    return build('calendar', 'v3', credentials=creds)

@tool
def get_current_time_in_timezone(timezone: str) -> str:
    """A tool that fetches the current local time in a specified timezone.
    
    Args:
        timezone: A string representing a valid timezone (e.g., 'America/New_York').
    
    Returns:
        String with the current local time in the specified timezone.
    """
    try:
        tz = pytz.timezone(timezone)
        local_time = datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        return f"The current local time in {timezone} is: {local_time}"
    except Exception as e:
        return f"Error fetching time for timezone '{timezone}': {str(e)}"

@tool
def create_calendar_event(summary: str, start_time: str, end_time: str, description: str = "", location: str = "") -> str:
    """Creates a calendar event in Google Calendar.
    
    Args:
        summary: Title of the event
        start_time: Start time in ISO format (YYYY-MM-DDTHH:MM:SS)
        end_time: End time in ISO format (YYYY-MM-DDTHH:MM:SS)
        description: Optional description of the event
        location: Optional location of the event
    
    Returns:
        String confirming event creation with event ID
    """
    try:
        service = get_calendar_service()
        
        event = {
            'summary': summary,
            'location': location,
            'description': description,
            'start': {
                'dateTime': start_time,
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': end_time,
                'timeZone': 'UTC',
            },
        }

        event = service.events().insert(calendarId='primary', body=event).execute()
        return f"Event created successfully! Event ID: {event.get('id')}"
    except Exception as e:
        return f"Failed to create calendar event: {str(e)}"

@tool
def connect_google_account() -> str:
    """Authenticates user with Google and connects their Google account to the application.
    
    Args:
        No arguments required for this function.
    
    Returns:
        String confirming successful connection or error message
    """
    try:
        creds = get_google_credentials()
        if creds and creds.valid:
            service = build('calendar', 'v3', credentials=creds)
            calendar_list = service.calendarList().list().execute()
            return f"Successfully connected to Google account! Found {len(calendar_list.get('items', []))} calendars."
        else:
            return "Failed to connect Google account. Authentication unsuccessful."
    except Exception as e:
        return f"Error connecting Google account: {str(e)}"

def check_credentials_file():
    """Check if credentials.json exists and is valid"""
    if not os.path.exists('credentials.json'):
        raise FileNotFoundError(
            "credentials.json file not found. Please create a project in Google Cloud Console, "
            "enable the Calendar API, and download the OAuth credentials file as credentials.json."
        )
    return True

# Initialize tools
final_answer = FinalAnswerTool()
visit_webpage = VisitWebpageTool()
image_generation_tool = load_tool("agents-course/text-to-image", trust_remote_code=True)

# Initialize model
model = HfApiModel(
    max_tokens=1500,
    temperature=0.5,
    model_id='Qwen/Qwen2.5-Coder-32B-Instruct',
    custom_role_conversions=None,
)

# Load prompts
with open("prompts.yaml", 'r') as stream:
    prompt_templates = yaml.safe_load(stream)

# Initialize agent
agent = CodeAgent(
    model=model,
    tools=[final_answer, visit_webpage, get_current_time_in_timezone, 
           image_generation_tool, create_calendar_event, connect_google_account],
    max_steps=6,
    verbosity_level=1,
    grammar=None,
    planning_interval=None,
    name=None,
    description=None,
    prompt_templates=prompt_templates
)

# Create FastAPI app
app = FastAPI(title="Career Coach AI Agent API", description="API for interacting with AI agents")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define API models
class QueryRequest(BaseModel):
    query: str
    reset_memory: bool = False

class CalendarEventRequest(BaseModel):
    summary: str
    start_time: str
    end_time: str
    description: str = ""
    location: str = ""

@app.post("/calendar/create-event")
async def api_create_calendar_event(event_request: CalendarEventRequest):
    """FastAPI endpoint for creating calendar events"""
    try:
        result = create_calendar_event(
            event_request.summary,
            event_request.start_time,
            event_request.end_time,
            event_request.description,
            event_request.location
        )
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/agent/query")
async def query_agent(request: QueryRequest, background_tasks: BackgroundTasks):
    """FastAPI endpoint for querying the agent"""
    if agent is None:
        raise HTTPException(status_code=500, detail="Agent not initialized")
    
    try:
        # Process the query and return the result
        result = agent.run(request.query, reset=request.reset_memory)
        # Handle different types of results
        result = handle_agent_output_types(result)
        
        # Convert to appropriate response format
        if isinstance(result, AgentText):
            return {"status": "success", "response": result.to_string()}
        elif isinstance(result, AgentImage):
            return {"status": "success", "response": result.to_string(), "type": "image"}
        elif isinstance(result, AgentAudio):
            return {"status": "success", "response": result.to_string(), "type": "audio"}
        else:
            return {"status": "success", "response": str(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/google/connect")
async def api_connect_google():
    """FastAPI endpoint for connecting Google account"""
    try:
        result = connect_google_account()
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def root():
    """Redirect to the Gradio UI"""
    return RedirectResponse(url="http://localhost:7860")

@app.get("/api-docs-info")
async def api_docs_info():
    """Returns information about the API documentation"""
    return {
        "status": "success", 
        "docs_url": "http://localhost:8000/docs",
        "message": "API documentation is available at http://localhost:8000/docs"
    }
