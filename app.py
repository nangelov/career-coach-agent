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
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

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

# Initialize the HuggingFace pipeline with more strict parameters
llm = HuggingFaceEndpoint(
    repo_id="meta-llama/Llama-3.3-70B-Instruct",
    huggingfacehub_api_token=os.getenv('HUGGINGFACEHUB_API_TOKEN'),
    provider="hf-inference",
    task="text-generation",
    temperature=0.1,  # Keep low for more deterministic responses
    max_new_tokens=2048,  # Increase token limit
    top_p=0.95,
    repetition_penalty=1.2,  # Slightly increase to prevent repetition
    do_sample=True,
    return_full_text=False,
)

# Load system prompt and template
with open("prompts.yaml", 'r') as stream:
    prompt_templates = yaml.safe_load(stream)

# Create the ReAct prompt template with system prompt as a partial variable
prompt = PromptTemplate.from_template(
    template=prompt_templates["template"],
    partial_variables={"system_prompt": prompt_templates["system_prompt"]}
)

tools = [visit_webpage, wikipedia_search, run_python_code, internet_search]
# Create the agent with more explicit instructions
agent = create_react_agent(
    llm=llm,
    tools=tools,
    prompt=prompt
)

# Set up agent executor with better error handling
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,
    handle_parsing_errors=True,
    max_iterations=5,  # Increased to give more chances
    return_intermediate_steps=True,  # Return thought process
    early_stopping_method="force",  # Force stop after max iterations
    stop=["Human:", "Assistant:"]
)
# API Models
class QueryRequest(BaseModel):
    query: str  # This matches the "query" field sent by Gradio
    thread_id: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)

# API Routes
@app.post("/agent/query")
async def query_agent(request: QueryRequest):
    print("Received query:", request.query)
    try:
        thread_id = request.thread_id or str(uuid.uuid4())

        # Preprocess the query to help guide the agent
        query = request.query

        # Check if this is likely a factual question
        factual_indicators = ["who is", "what is", "when did", "where is", "why did", "how does"]
        is_likely_factual = any(query.lower().startswith(indicator) for indicator in factual_indicators)

        # Add a hint for factual questions
        if is_likely_factual:
            query = f"{query} (Please use your tools to find accurate information about this.)"

        response = agent_executor.invoke({
            "input": query
        })

        print("full_thought_process: ", response.get("intermediate_steps", "No thought process generated"))

        # Clean up the response if needed
        output = response.get("output", "No response generated")
        if "<|eot_id|>" in output:
            output = output.split("<|eot_id|>")[0]

        return {
            "status": "success",
            "thread_id": thread_id,
            "response": output,
            "full_thought_process": str(response.get("intermediate_steps", "No thought process generated"))
        }
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=str(e))

# Check if the frontend build directory exists
if os.path.exists("frontend/build"):
    # Serve static files from React build
    app.mount("/static", StaticFiles(directory="frontend/build/static"), name="static")

    # Serve other static files from the build directory
    if os.path.exists("frontend/build/assets"):
        app.mount("/assets", StaticFiles(directory="frontend/build/assets"), name="assets")

    # Serve React app for all other routes that don't match API endpoints
    @app.get("/{full_path:path}")
    async def serve_react_app(full_path: str):
        # Skip API routes
        if full_path.startswith("agent/"):
            raise HTTPException(status_code=404, detail="Not found")

        # For all other routes, serve the React app
        return FileResponse("frontend/build/index.html")