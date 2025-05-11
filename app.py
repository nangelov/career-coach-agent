from langchain_core.tools import tool
from langchain_huggingface import HuggingFaceEndpoint
from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.prompts import PromptTemplate

from tools.visit_webpage import visit_webpage

import gradio as gr
import datetime 
import pytz
import os
import yaml
import json
import uuid
from typing import Optional, Type, Dict, Any, List
from pydantic import BaseModel, Field

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
import requests

# Initialize FastAPI app
app = FastAPI(title="AI Assistant", description="AI Assistant with LangChain and Gradio")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Token authentication for Hugging Face
if not os.getenv('HUGGINGFACEHUB_API_TOKEN'):
    raise ValueError("Please set HUGGINGFACEHUB_API_TOKEN environment variable")

# Initialize the HuggingFace endpoint
llm = HuggingFaceEndpoint(
    endpoint_url="https://api-inference.huggingface.co/models/mistralai/Mixtral-8x7B-Instruct-v0.1",
    huggingfacehub_api_token=os.getenv('HUGGINGFACEHUB_API_TOKEN'),
    task="text-generation",
    temperature=0.7,
    max_new_tokens=1024,
    top_p=0.95,
    repetition_penalty=1.1,
    do_sample=True,
    return_full_text=False,
    model_kwargs={
        "stop": ["Human:", "Assistant:", "Observation:"]  # Reduced to 3 stop sequences
    }
)

# Define tools
@tool
def get_current_time(timezone: str = "UTC") -> str:
    """Get the current time in the specified timezone."""
    try:
        tz = pytz.timezone(timezone)
        current_time = datetime.datetime.now(tz)
        return current_time.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception as e:
        return f"Error: {str(e)}"

@tool
def visit_webpage(url: str) -> str:
    """Visit a webpage and return its content as markdown."""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return f"Successfully visited {url}. Content length: {len(response.text)} characters"
    except Exception as e:
        return f"Error visiting webpage: {str(e)}"

# Load system prompt and template
with open("prompts.yaml", 'r') as stream:
    prompt_templates = yaml.safe_load(stream)

# Create the ReAct prompt template
prompt = PromptTemplate.from_template(prompt_templates["template"])

# Create the agent
tools = [get_current_time, visit_webpage]  
agent = create_react_agent(
    llm=llm,
    tools=tools,
    prompt=prompt
)
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,
    handle_parsing_errors=True
)

# API Models
class QueryRequest(BaseModel):
    query: str
    thread_id: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)

# API Routes
@app.get("/")
async def root():
    return HTMLResponse("<h2>Welcome! Please use the Gradio UI above.</h2>")

@app.get("/docs")
async def redirect_to_docs():
    return RedirectResponse(url=f"{app.url_path_for('root')}:8000/docs")

@app.post("/agent/query")
async def query_agent(request: QueryRequest):
    try:
        # Generate thread_id if not provided
        thread_id = request.thread_id or str(uuid.uuid4())
        
        # Execute the agent
        response = agent_executor.invoke({
            "input": request.query,
            "system_prompt": prompt_templates["system_prompt"]
        })
        
        return {
            "status": "success",
            "thread_id": thread_id,
            "response": response["output"] if "output" in response else "No response generated"
        }
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=str(e))
