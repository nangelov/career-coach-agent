from langchain_huggingface import HuggingFaceEndpoint
from langchain.agents import AgentExecutor
from langchain.agents.format_scratchpad import format_log_to_str
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.memory import ConversationBufferMemory
from langchain.tools.render import render_text_description

from tools.visit_webpage import visit_webpage
from tools.wikipedia_tool import wikipedia_search
from tools.python_repl import run_python_code
from tools.internet_search import internet_search
from tools.google_jobs_search import google_job_search
from tools.date_and_time import current_date_and_time
from output_parser import FlexibleOutputParser, clean_llm_response

import os
import yaml
import uuid
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
import asyncio

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse


active_requests = {}

# Initialize FastAPI app
app = FastAPI(title="AI Assistant", description="AI Assistant with LangChain powered by Llama-3.3-70B-Instruct")

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

model = "meta-llama/Llama-3.3-70B-Instruct"

# Initialize the HuggingFace pipeline with more strict parameters
llm = HuggingFaceEndpoint(
    repo_id=model,
    huggingfacehub_api_token=os.getenv('HUGGINGFACEHUB_API_TOKEN'),
    provider="hf-inference",
    task="text-generation",
    temperature=0.1,  # Slightly higher for more natural responses
    max_new_tokens=512,  # Increase to avoid truncation
    top_p=0.9,  # More diverse responses
    repetition_penalty=1.15,  # Stronger penalty to avoid "Human:"
    do_sample=True,
    verbose=True,
    return_full_text=False
)

utc_date_and_time_now = current_date_and_time('UTC')
# Load system prompt and template
with open("prompts.yaml", 'r') as stream:
    prompt_templates = yaml.safe_load(stream)

# Define tools
tools = [visit_webpage, wikipedia_search, run_python_code, internet_search, google_job_search, current_date_and_time]

# Create memory for conversation history
memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True,
    output_key="output"  # Specify which key to use for the output
)

# Create the prompt template with chat history
prompt = ChatPromptTemplate.from_messages([
    ("system", prompt_templates["system_prompt"].format(
        tools=render_text_description(tools),
        tool_names=", ".join([t.name for t in tools]),
        current_utc_date_and_time=utc_date_and_time_now
    )),
    MessagesPlaceholder(variable_name="chat_history"),
    ("human", "{input}"),
    ("assistant", "{agent_scratchpad}")  # Remove the prefix text and change to "assistant"
])

# Define the agent
chat_model_with_stop = llm.bind(
    stop=["\nHuman:", "Human:", "\n\nHuman", "\nUser:"] 
)

# Update the agent to include chat_history
agent = (
    {
        "input": lambda x: x["input"],
        "agent_scratchpad": lambda x: format_log_to_str(x["intermediate_steps"]) if x["intermediate_steps"] else "",
        "chat_history": lambda x: x.get("chat_history", [])  # Add this line!
    }
    | prompt
    | chat_model_with_stop
    | FlexibleOutputParser()
)

agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,
   #handle_parsing_errors="Check your output and make sure it conforms to the expected format!",
    handle_parsing_errors=True,
    max_iterations=4,  
    return_intermediate_steps=True,
    early_stopping_method="force",  
    memory=memory
)

# Add this function to clear corrupted memory
def clear_memory_if_corrupted():
    """Clear memory if it contains too many corrupted entries"""
    messages = memory.chat_memory.messages
    if not messages:
        return

    corrupted_count = sum(1 for msg in messages if not msg.content.strip() or "Human:" in msg.content or msg.content == "Human:")

    print(f"Memory check: {corrupted_count}/{len(messages)} corrupted messages")

    if corrupted_count > len(messages) * 0.2:  # If 20% of messages are corrupted
        print("Clearing corrupted memory...")
        memory.clear()

# API Models
class QueryRequest(BaseModel):
    query: str
    thread_id: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)

# API Routes
@app.post("/agent/cancel/{thread_id}")
async def cancel_request(thread_id: str):
    if thread_id in active_requests:
        active_requests[thread_id].cancel()
        del active_requests[thread_id]
        return {"status": "cancelled", "thread_id": thread_id}
    return {"status": "not_found", "thread_id": thread_id}

# Modify the existing query_agent function
@app.post("/agent/query")
async def query_agent(request: QueryRequest):
    print("\n" + "="*50)
    print("Received query:", request.query)
    print("="*50 + "\n")

    thread_id = request.thread_id or str(uuid.uuid4())

    print("thread_id:", thread_id)

    # If no thread_id provided, this is a new conversation - clear memory
    if not request.thread_id:
        print("New conversation started - clearing memory...")
        memory.clear()

    # Clear corrupted memory
    clear_memory_if_corrupted()

    # Create a cancellation token
    cancel_event = asyncio.Event()
    active_requests[thread_id] = cancel_event

    try:
        # Create the input with proper message formatting
        agent_input = {
            "input": request.query
        }

        print("\nStarting agent execution...")

        # Create a task that can be cancelled
        async def run_agent():
            try:
                # Run the agent in a thread pool to avoid blocking
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(agent_executor.invoke, agent_input)

                    # Check for cancellation periodically
                    while not future.done():
                        if cancel_event.is_set():
                            future.cancel()
                            raise asyncio.CancelledError("Request was cancelled")
                        await asyncio.sleep(0.1)

                    return future.result()
            except Exception as e:
                print(f"Agent execution error: {str(e)}")
                raise e

        try:
            response = await run_agent()
            print("Raw agent response:", response)
        except asyncio.CancelledError:
            return {
                "status": "cancelled",
                "thread_id": thread_id,
                "response": "Request was cancelled by user.",
                "full_thought_process": "Request cancelled"
            }
        except Exception as e:
            print(f"Agent execution error: {str(e)}")
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
        raw_output = response.get("output", "No response generated")
        output = clean_llm_response(raw_output)
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
    finally:
        # Clean up the active request
        if thread_id in active_requests:
            del active_requests[thread_id]

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