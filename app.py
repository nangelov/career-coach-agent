from langchain_huggingface import HuggingFaceEndpoint
from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.prompts import PromptTemplate
from langchain.memory import ConversationBufferMemory

from tools.visit_webpage import visit_webpage
from tools.wikipedia_tool import wikipedia_search
from tools.python_repl import run_python_code
from tools.internet_search import internet_search

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
    endpoint_url="https://api-inference.huggingface.co/models/meta-llama/Meta-Llama-3-70B-Instruct",
    huggingfacehub_api_token=os.getenv('HUGGINGFACEHUB_API_TOKEN'),
    task="text-generation",
    temperature=0.1,
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
tools = [visit_webpage, wikipedia_search, run_python_code, internet_search]  
agent = create_react_agent(
    llm=llm,
    tools=tools,
    prompt=prompt
)

memory = ConversationBufferMemory(return_messages=True)
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    memory=memory,
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
    print("Received query:", request.query)
    try:
        thread_id = request.thread_id or str(uuid.uuid4())
        response = agent_executor.invoke({
            "input": request.query
        })
        return {
            "status": "success",
            "thread_id": thread_id,
            "response": response.get("output", "No response generated"),
            "full_thought_process": response.get("full_thought_process", "No thought process generated")
        }
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=str(e))

# Create and mount the Gradio interface
gradio_ui = GradioUI(agent=agent_executor)
app = gr.mount_gradio_app(app, gradio_ui.create_interface(), path="")