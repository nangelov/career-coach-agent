from langchain_core.tools import tool
from langchain_huggingface import HuggingFaceEndpoint
from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.prompts import PromptTemplate

from tools.visit_webpage import visit_webpage
from tools.time_tools import get_current_time

import os
import yaml
import uuid
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import gradio as gr

from Gradio_UI import GradioUI

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
        "stop": ["Human:", "Assistant:", "Observation:"]
    }
)

# Load system prompt and template
with open("prompts.yaml", 'r') as stream:
    prompt_templates = yaml.safe_load(stream)

# Create the ReAct prompt template with system prompt as a partial variable
prompt = PromptTemplate.from_template(
    template=prompt_templates["template"],
    partial_variables={"system_prompt": prompt_templates["system_prompt"]}
)

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
@app.post("/agent/query")
async def query_agent(request: QueryRequest):
    try:
        thread_id = request.thread_id or str(uuid.uuid4())
        response = agent_executor.invoke({
            "input": request.query
        })
        return {
            "status": "success",
            "thread_id": thread_id,
            "response": response["output"] if "output" in response else "No response generated"
        }
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=str(e))

# Create and mount the Gradio interface
gradio_ui = GradioUI(agent=agent_executor)
app = gr.mount_gradio_app(app, gradio_ui.create_interface(), path="")