from langchain_huggingface import HuggingFaceEndpoint
from langchain.agents import AgentExecutor
from langchain.agents.format_scratchpad import format_log_to_str
from langchain.agents.output_parsers import ReActSingleInputOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.memory import ConversationBufferMemory
from langchain.tools.render import render_text_description

from tools.visit_webpage import visit_webpage
from tools.wikipedia_tool import wikipedia_search
from tools.python_repl import run_python_code
from tools.internet_search import internet_search

import os
import yaml
import uuid
from typing import Optional, Dict, Any, List
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
    repo_id="meta-llama/Llama-3.3-70B-Instruct",  # Change to one of the recommended models
    huggingfacehub_api_token=os.getenv('HUGGINGFACEHUB_API_TOKEN'),
    provider="hf-inference",
    task="text-generation",
    temperature=0.2,
    max_new_tokens=2048,
    top_p=0.95,
    repetition_penalty=1.2,
    do_sample=True,
    verbose=True,
    return_full_text=False
)

# Load system prompt and template
with open("prompts.yaml", 'r') as stream:
    prompt_templates = yaml.safe_load(stream)

# Define tools
tools = [visit_webpage, wikipedia_search, run_python_code, internet_search]

# Create memory for conversation history
memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True,
    output_key="output"  # Specify which key to use for the output
)

# Create the prompt template
prompt = ChatPromptTemplate.from_messages([
    ("system", prompt_templates["system_prompt"].format(
        tools=render_text_description(tools),
        tool_names=", ".join([t.name for t in tools])
    )),
    ("human", "Current question: {input}"),
    ("ai", "Let me help you with that.\n{agent_scratchpad}")
])

# Define the agent
chat_model_with_stop = llm.bind(stop=["\nObservation", "\nFinal Answer:", "\nHuman:", "\nAI:"])
agent = (
    {
        "input": lambda x: x["input"],
        "agent_scratchpad": lambda x: format_log_to_str(x["intermediate_steps"]) if x["intermediate_steps"] else "",
    }
    | prompt
    | chat_model_with_stop
    | ReActSingleInputOutputParser()
)

# Set up agent executor with better error handling
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,
    handle_parsing_errors=True,
    max_iterations=3,
    return_intermediate_steps=True,
    early_stopping_method="force",
    memory=memory
)

# API Models
class QueryRequest(BaseModel):
    query: str
    thread_id: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)

# API Routes
@app.post("/agent/query")
async def query_agent(request: QueryRequest):
    print("\n" + "="*50)
    print("Received query:", request.query)
    print("="*50 + "\n")
    try:
        thread_id = request.thread_id or str(uuid.uuid4())

        # Create the input with proper message formatting
        agent_input = {
            "input": request.query
        }

        print("\nStarting agent execution...")
        try:
            response = agent_executor.invoke(agent_input)
            print("Raw agent response:", response)
        except Exception as e:
            print(f"Agent execution error: {str(e)}")
            # If the agent fails, return a graceful error message
            return {
                "status": "error",
                "thread_id": thread_id,
                "response": "I apologize, but I'm having trouble processing your request right now. Please try again with a different question.",
                "full_thought_process": f"Agent execution failed: {str(e)}"
            }

        # Print detailed thought process
        print("\n" + "-"*50)
        print("Agent's Thought Process:")
        print("-"*50)
        for step in response.get("intermediate_steps", []):
            print("\nStep:")
            print(f"Action: {step[0].tool}")
            print(f"Action Input: {step[0].tool_input}")
            print(f"Observation: {step[1]}")
            print("-"*30)

        print("\nFinal Response:")
        print("-"*50)
        output = response.get("output", "No response generated")
        if "<|eot_id|>" in output:
            output = output.split("<|eot_id|>")[0]
        print(output)
        print("="*50 + "\n")

        # Save the response to memory
        memory.save_context(
            {"input": request.query},
            {"output": output}
        )

        return {
            "status": "success",
            "thread_id": thread_id,
            "response": output,
            "full_thought_process": str(response.get("intermediate_steps", "No thought process generated"))
        }
    except Exception as e:
        print("\nError occurred:")
        print("-"*50)
        print(str(e))
        print("="*50 + "\n")
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