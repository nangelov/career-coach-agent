from langchain_huggingface import HuggingFaceEndpoint
from langchain.agents import AgentExecutor
from langchain.agents.format_scratchpad import format_log_to_str
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.memory import ConversationBufferMemory
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.tools.render import render_text_description
from langchain.text_splitter import RecursiveCharacterTextSplitter

from output_parser import FlexibleOutputParser, clean_llm_response, validate_pdp_response, PDPOutputParser
from tools import *
from helpers import *
import logging


import os
import yaml
import uuid
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
import asyncio
import tempfile
from io import BytesIO
import re
from datetime import datetime

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
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
    max_new_tokens=1024,  # Increase to avoid truncation
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

agent = (
    {
        "input": lambda x: x["input"],
        "agent_scratchpad": lambda x: format_log_to_str(x["intermediate_steps"]) if x["intermediate_steps"] else "",
        "chat_history": lambda x: x.get("chat_history", []) 
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
    max_iterations=5,  
    return_intermediate_steps=True,
    early_stopping_method="force",  
    memory=memory
)

#initialize PDP agent
pdp_llm = HuggingFaceEndpoint(
    repo_id=model,
    huggingfacehub_api_token=os.getenv('HUGGINGFACEHUB_API_TOKEN'),
    provider="hf-inference",
    task="text-generation",
    temperature=0.1,
    max_new_tokens=3072,  # Much higher for comprehensive PDPs
    top_p=0.9,
    repetition_penalty=1.15,
    do_sample=True,
    verbose=True,
    return_full_text=False
)

# Create separate agent executor for PDP
pdp_chat_model_with_stop = pdp_llm.bind(
    stop=["\nHuman:", "Human:", "\n\nHuman", "\nUser:"] 
)

pdp_agent = (
    {
        "input": lambda x: x["input"],
        "agent_scratchpad": lambda x: format_log_to_str(x["intermediate_steps"]) if x["intermediate_steps"] else "",
        "chat_history": lambda x: x.get("chat_history", []) 
    }
    | prompt
    | pdp_chat_model_with_stop
    | PDPOutputParser()
)

pdp_agent_executor = AgentExecutor(
    agent=pdp_agent,
    tools=tools,
    verbose=True,
    handle_parsing_errors=True,
    max_iterations=5,  
    return_intermediate_steps=True,
    early_stopping_method="force",  
    memory=memory
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Add this function to clear corrupted memory
def clear_memory_if_corrupted():
    """Clear memory if it contains too many corrupted entries"""
    messages = memory.chat_memory.messages
    if not messages:
        return

    corrupted_count = sum(1 for msg in messages if not msg.content.strip() or "Human:" in msg.content or msg.content == "Human:")

    logging.info(f"Memory check: {corrupted_count}/{len(messages)} corrupted messages")

    if corrupted_count > len(messages) * 0.2:  # If 20% of messages are corrupted
        logging.info("Clearing corrupted memory...")
        memory.clear()

# API Models
class QueryRequest(BaseModel):
    query: str
    thread_id: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)

class PDPRequest(BaseModel):
    career_goal: str
    additional_context: str = ""
    target_date: str
    cv_content: str = ""  # To store extracted CV text

# API Routes
@app.get("/get-feedback")
async def get_feedback(key: str):
    """
    Read out all feedback files. Requires Hugging Face API token for authentication.
    """
    try:
        token = os.getenv('HUGGINGFACEHUB_API_TOKEN')
        
        if not token:
            raise HTTPException(status_code=500, detail="HUGGINGFACEHUB_API_TOKEN not configured")
            
        if key != token:
            raise HTTPException(status_code=401, detail="Unauthorized access")
            
        result = read_out_feedback()
        return result

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error retrieving feedback: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving feedback: {str(e)}"
        )

@app.post("/agent/feedback")
async def feedback(contact: str, feedback: str):
    """
    Receive and store user feedback
    """
    try:
        logging.info(f"Feedback: {contact}, {feedback}")
        result = store_feedback(contact, feedback)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/agent/cancel/{thread_id}")
async def cancel_request(thread_id: str):
    if thread_id in active_requests:
        active_requests[thread_id].cancel()
        del active_requests[thread_id]
        return {"status": "cancelled", "thread_id": thread_id}
    return {"status": "not_found", "thread_id": thread_id}

# Configure text splitter
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    length_function=len,
)

@app.post("/pdp-generator")
async def pdp_generator(
    file: UploadFile = File(...),
    career_goal: str = Form(...),
    additional_context: str = Form(""),
    target_date: str = Form(...)
):
    """
    Generate Personal Development Plan as PDF using uploaded CV and user inputs
    """
    # Validate file type
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    # Create temporary file
    tmp_file_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            # Write uploaded content to temp file
            content = await file.read()
            if not content:
                raise HTTPException(status_code=400, detail="Empty file uploaded")
            tmp_file.write(content)
            tmp_file_path = tmp_file.name

        # Load PDF using LangChain
        try:
            loader = PyPDFLoader(tmp_file_path)
            documents = loader.load()
            if not documents:
                raise HTTPException(status_code=400, detail="Could not extract content from PDF")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error processing PDF: {str(e)}")

        # Split documents into chunks
        chunks = text_splitter.split_documents(documents)
        if not chunks:
            raise HTTPException(status_code=400, detail="No content could be extracted from the PDF")

        # Extract CV content
        cv_content = "\n".join([chunk.page_content for chunk in chunks])
        if not cv_content.strip():
            raise HTTPException(status_code=400, detail="No text content found in the PDF")

        # Create PDP request
        pdp_request = PDPRequest(
            career_goal=career_goal,
            additional_context=additional_context,
            target_date=target_date,
            cv_content=cv_content
        )
        #debug
        logging.info(f"PDP request: {pdp_request}")

        # Generate PDP using the agent
        pdp_query = f"""
        Create a comprehensive Personal Development Plan for transitioning to {pdp_request.career_goal} by {pdp_request.target_date}.
        DO NOT ASK FOR CONFIRMATION OF THIS REQUEST!

        Based on this CV content: {pdp_request.cv_content}
        Additional context: {pdp_request.additional_context}

        Structure your response with these exact sections:

        ## Current Skills Assessment
        [Analyze current skills from CV]

        ## Skills Gap Analysis
        [Identify missing skills for the target role]

        ## Learning Objectives and Milestones
        [Specific, measurable goals with dates]

        ## Recommended Training and Development
        [Specific courses, certifications, resources]

        ## Timeline and Action Steps
        [Month-by-month plan until {pdp_request.target_date}]

        ## Progress Tracking and KPIs
        [How to measure success]

        Do NOT include any code execution and Python scripts.
        Focus on creating a clear, actionable career development plan.
        """

        max_retries = 1
        for attempt in range(max_retries):
            try:
                # Clear memory before each attempt to avoid contamination
                memory.clear()

                agent_input = {"input": pdp_query}
                response = pdp_agent_executor.invoke(agent_input)
                pdp_response = response.get("output", "")
                               
                logging.info(f"DEBUG: After cleanup length: {len(pdp_response)}")
                
                # Validate the response
                if validate_pdp_response(pdp_response):
                    # Create PDF only if validation passes
                    logging.info(f"raw-pdp_response: {pdp_response}")
                    try:
                        pdf_buffer = create_pdp_pdf(
                            pdp_content=pdp_response,
                            career_goal=career_goal,
                            target_date=target_date,
                            filename=file.filename
                        )

                        # Return successful PDF
                        safe_career_goal = re.sub(r'[^\w\s-]', '', career_goal).strip()
                        safe_career_goal = re.sub(r'[-\s]+', '-', safe_career_goal)
                        pdf_filename = f"PDP_{safe_career_goal}_{datetime.now().strftime('%Y%m%d')}.pdf"

                        # Add PDP request to chat history memory
                        user_pdp_message = f"User requested a Personal Development Plan.\nCareer Goal: {pdp_request.career_goal}\nTarget Date: {pdp_request.target_date}\nAdditional Context: {pdp_request.additional_context or 'None'}\nCV Provided: {'Yes' if cv_content.strip() else 'No'}"
                        assistant_pdp_ack = "Okay, I 've successfully generated you PDP PDF file"
                        memory.save_context(
                            {"input": user_pdp_message},
                            {"output": assistant_pdp_ack}
                        )

                        return StreamingResponse(
                            BytesIO(pdf_buffer.read()),
                            media_type="application/pdf",
                            headers={"Content-Disposition": f"attachment; filename={pdf_filename}"}
                        )

                    except Exception as e:
                        logging.info(f"PDF creation error on attempt {attempt + 1}: {str(e)}")
                        if attempt == max_retries - 1:
                            raise HTTPException(status_code=500, detail=f"Error creating PDF: {str(e)}")
                else:
                    logging.info(f"Invalid PDP response on attempt {attempt + 1}")
                    if attempt == max_retries - 1:
                        raise HTTPException(
                            status_code=500,
                            detail="Unable to generate a properly formatted PDP. Please try again with different inputs or contact support."
                        )

            except Exception as e:
                logging.info(f"Agent execution error on attempt {attempt + 1}: {str(e)}")
                if attempt == max_retries - 1:
                    raise HTTPException(
                        status_code=500,
                        detail="The AI assistant encountered an issue generating your PDP. Please try again or contact support if the problem persists."
                    )

        # This should never be reached, but just in case
        raise HTTPException(status_code=500, detail="Failed to generate PDP after multiple attempts")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing request: {str(e)}")
    finally:
        # Clean up temporary file if it exists
        if tmp_file_path and os.path.exists(tmp_file_path):
            try:
                os.unlink(tmp_file_path)
            except Exception as e:
                logging.info(f"Error cleaning up temporary file: {str(e)}")

@app.post("/agent/query")
async def query_agent(request: QueryRequest):
    logging.info(f"\n" + "="*50)
    logging.info(f"Received query: {request.query}")
    logging.info("="*50 + "\n")

    thread_id = request.thread_id or str(uuid.uuid4())

    logging.info(f"thread_id: {thread_id}")

    # If no thread_id provided, this is a new conversation - clear memory
    if not request.thread_id:
        logging.info("New conversation started - clearing memory...")
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

        logging.info("\nStarting agent execution...")

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
                logging.info(f"Agent execution error: {str(e)}")
                raise e

        try:
            response = await run_agent()
            #debug
            logging.info(f"Raw agent response: {response}")
        except asyncio.CancelledError:
            return {
                "status": "cancelled",
                "thread_id": thread_id,
                "response": "Request was cancelled by user.",
                "full_thought_process": "Request cancelled"
            }
        except Exception as e:
            logging.info(f"Agent execution error: {str(e)}")
            return {
                "status": "error",
                "thread_id": thread_id,
                "response": "I apologize, but I'm having trouble processing your request right now. Please try again with a different question.",
                "full_thought_process": f"Agent execution failed: {str(e)}"
            }

        # Print detailed thought process
        logging.info(f"\n" + "-"*50)
        logging.info(f"Agent's Thought Process:")
        logging.info("-"*50)
        for step in response.get("intermediate_steps", []):
            logging.info("\nStep:")
            logging.info(f"Action: {step[0].tool}")
            logging.info(f"Action Input: {step[0].tool_input}")
            logging.info(f"Observation: {step[1]}")
            logging.info("-"*30)

        logging.info("\nFinal Response:")
        logging.info("-"*50)
        raw_output = response.get("output", "No response generated")
        output = clean_llm_response(raw_output)
        #debug
        logging.info(output)
        logging.info("="*50 + "\n")

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
        logging.info("\nError occurred:")
        logging.info("-"*50)
        logging.info(str(e))
        logging.info("="*50 + "\n")
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