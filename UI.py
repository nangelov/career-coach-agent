import mimetypes
import os
import re
import shutil
from typing import Optional, List, Dict, Any, Callable

from smolagents.agent_types import AgentAudio, AgentImage, AgentText, handle_agent_output_types
from smolagents.agents import ActionStep, MultiStepAgent
from smolagents.memory import MemoryStep
from smolagents.utils import _is_package_available
import gradio as gr
import requests


def pull_messages_from_step(
    step_log: MemoryStep,
):
    """Extract ChatMessage objects from agent steps with proper nesting"""
    if isinstance(step_log, ActionStep):
        # Output the step number
        step_number = f"Step {step_log.step_number}" if step_log.step_number is not None else ""
        yield gr.ChatMessage(role="assistant", content=f"**{step_number}**")

        # First yield the thought/reasoning from the LLM
        if hasattr(step_log, "model_output") and step_log.model_output is not None:
            # Clean up the LLM output
            model_output = step_log.model_output.strip()
            # Remove any trailing <end_code> and extra backticks, handling multiple possible formats
            model_output = re.sub(r"```\s*<end_code>", "```", model_output)  # handles ```<end_code>
            model_output = re.sub(r"<end_code>\s*```", "```", model_output)  # handles <end_code>```
            model_output = re.sub(r"```\s*\n\s*<end_code>", "```", model_output)  # handles ```\n<end_code>
            model_output = model_output.strip()
            yield gr.ChatMessage(role="assistant", content=model_output)

        # For tool calls, create a parent message
        if hasattr(step_log, "tool_calls") and step_log.tool_calls is not None:
            first_tool_call = step_log.tool_calls[0]
            used_code = first_tool_call.name == "python_interpreter"
            parent_id = f"call_{len(step_log.tool_calls)}"

            # Tool call becomes the parent message with timing info
            # First we will handle arguments based on type
            args = first_tool_call.arguments
            if isinstance(args, dict):
                content = str(args.get("answer", str(args)))
            else:
                content = str(args).strip()

            if used_code:
                # Clean up the content by removing any end code tags
                content = re.sub(r"```.*?\n", "", content)  # Remove existing code blocks
                content = re.sub(r"\s*<end_code>\s*", "", content)  # Remove end_code tags
                content = content.strip()
                if not content.startswith("```python"):
                    content = f"```python\n{content}\n```"

            parent_message_tool = gr.ChatMessage(
                role="assistant",
                content=content,
                metadata={
                    "title": f"🛠️ Used tool {first_tool_call.name}",
                    "id": parent_id,
                    "status": "pending",
                },
            )
            yield parent_message_tool

            # Nesting execution logs under the tool call if they exist
            if hasattr(step_log, "observations") and (
                step_log.observations is not None and step_log.observations.strip()
            ):  # Only yield execution logs if there's actual content
                log_content = step_log.observations.strip()
                if log_content:
                    log_content = re.sub(r"^Execution logs:\s*", "", log_content)
                    yield gr.ChatMessage(
                        role="assistant",
                        content=f"{log_content}",
                        metadata={"title": "📝 Execution Logs", "parent_id": parent_id, "status": "done"},
                    )

            # Nesting any errors under the tool call
            if hasattr(step_log, "error") and step_log.error is not None:
                yield gr.ChatMessage(
                    role="assistant",
                    content=str(step_log.error),
                    metadata={"title": "💥 Error", "parent_id": parent_id, "status": "done"},
                )

            # Update parent message metadata to done status without yielding a new message
            parent_message_tool.metadata["status"] = "done"

        # Handle standalone errors but not from tool calls
        elif hasattr(step_log, "error") and step_log.error is not None:
            yield gr.ChatMessage(role="assistant", content=str(step_log.error), metadata={"title": "💥 Error"})

        # Calculate duration and token information
        step_footnote = f"{step_number}"
        if hasattr(step_log, "input_token_count") and hasattr(step_log, "output_token_count"):
            token_str = (
                f" | Input-tokens:{step_log.input_token_count:,} | Output-tokens:{step_log.output_token_count:,}"
            )
            step_footnote += token_str
        if hasattr(step_log, "duration"):
            step_duration = f" | Duration: {round(float(step_log.duration), 2)}" if step_log.duration else None
            step_footnote += step_duration
        step_footnote = f"""<span style="color: #bbbbc2; font-size: 12px;">{step_footnote}</span> """
        yield gr.ChatMessage(role="assistant", content=f"{step_footnote}")
        yield gr.ChatMessage(role="assistant", content="-----")


def stream_to_gradio(
    agent,
    task: str,
    reset_agent_memory: bool = False,
    additional_args: Optional[dict] = None,
):
    """Runs an agent with the given task and streams the messages from the agent as gradio ChatMessages."""
    if not _is_package_available("gradio"):
        raise ModuleNotFoundError(
            "Please install 'gradio' extra to use the AgentUI: `pip install 'smolagents[gradio]'`"
        )

    total_input_tokens = 0
    total_output_tokens = 0

    for step_log in agent.run(task, stream=True, reset=reset_agent_memory, additional_args=additional_args):
        # Track tokens if model provides them
        if hasattr(agent.model, "last_input_token_count"):
            total_input_tokens += agent.model.last_input_token_count
            total_output_tokens += agent.model.last_output_token_count
            if isinstance(step_log, ActionStep):
                step_log.input_token_count = agent.model.last_input_token_count
                step_log.output_token_count = agent.model.last_output_token_count

        for message in pull_messages_from_step(
            step_log,
        ):
            yield message

    final_answer = step_log  # Last log is the run's final_answer
    final_answer = handle_agent_output_types(final_answer)

    if isinstance(final_answer, AgentText):
        yield gr.ChatMessage(
            role="assistant",
            content=f"**Final answer:**\n{final_answer.to_string()}\n",
        )
    elif isinstance(final_answer, AgentImage):
        yield gr.ChatMessage(
            role="assistant",
            content={"path": final_answer.to_string(), "mime_type": "image/png"},
        )
    elif isinstance(final_answer, AgentAudio):
        yield gr.ChatMessage(
            role="assistant",
            content={"path": final_answer.to_string(), "mime_type": "audio/wav"},
        )
    else:
        yield gr.ChatMessage(role="assistant", content=f"**Final answer:** {str(final_answer)}")


class AgentUI:
    """A Gradio interface that serves as a frontend for the agent API"""

    def __init__(self, agent=None, file_upload_folder: str = None, api_url: str = "http://localhost:8080"):
        self.agent = agent
        self.file_upload_folder = file_upload_folder
        self.api_url = api_url
        self.thread_id = None
        
        if self.file_upload_folder is not None:
            if not os.path.exists(file_upload_folder):
                os.makedirs(file_upload_folder, exist_ok=True)
        
        self.chat_history = []
    
    def query_agent(self, message: str, history: List[List[str]]):
        """Send a query to the agent API and return the response"""
        if not message:
            return "", history
        
        try:
            # Prepare request payload matching QueryRequest model
            payload = {
                "query": message,
                "thread_id": self.thread_id,
                "context": {}
            }
            
            response = requests.post(
                f"{self.api_url}/agent/query",
                json=payload
            )
            
            if response.status_code == 200:
                data = response.json()
                # Update thread_id from response
                self.thread_id = data.get("thread_id")
                return "", history + [[message, data["response"]]]
            else:
                return "", history + [[message, f"Error: {response.status_code}"]]
        except Exception as e:
            return "", history + [[message, f"Error: {str(e)}"]]
    
    def reset_conversation(self):
        """Reset the conversation state"""
        self.thread_id = None
        self.chat_history = []
        return "Started new conversation"
    
    def launch(self, server_name: str = "0.0.0.0", server_port: int = 8000, **kwargs):
        """Launch the Gradio interface"""
        api_port = int(self.api_url.split(":")[-1])
        
        with gr.Blocks(css="""
            #main-container {
                display: flex;
                height: 100%;
            }
            #menu-column {
                min-height: 600px;
                border-right: 1px solid #ddd;
            }
            #chat-column {
                min-height: 600px;
            }
            .button-container {
                padding: 10px;
            }
        """) as interface:
            with gr.Row(elem_id="main-container"):
                # Left menu strip (1/4 width)
                with gr.Column(scale=1, elem_id="menu-column"):
                    gr.Markdown(f"# Menu\n\nClick [here](http://localhost:{api_port}/docs) to view API documentation.")
                    with gr.Group(elem_classes="button-container"):
                        docs_btn = gr.HTML(f"""
                            <button onclick="window.open('http://localhost:{api_port}/docs', '_blank')" 
                                    style="width: 100%; padding: 10px; background-color: #f0f0f0; 
                                           border: none; border-radius: 4px; cursor: pointer;">
                                API Documentation
                            </button>
                        """)
                        new_chat_btn = gr.Button("New Chat", variant="primary")
                    
                    # Output area for button actions
                    menu_output = gr.HTML(label="Action Result")
                
                # Right chat console (3/4 width)
                with gr.Column(scale=3, elem_id="chat-column"):
                    gr.Markdown("# AI Assistant")
                    chatbot = gr.Chatbot(height=500)
                    msg = gr.Textbox(
                        placeholder="Ask me anything...",
                        show_label=False,
                        container=False
                    )
                    clear = gr.Button("Clear")
            
            # Set up event handlers
            msg.submit(self.query_agent, [msg, chatbot], [msg, chatbot])
            clear.click(lambda: ([], None), outputs=[chatbot, menu_output])
            new_chat_btn.click(
                fn=self.reset_conversation,
                inputs=[],
                outputs=[menu_output]
            )
            docs_btn.click(
                lambda: gr.update(value=f"<script>window.open('http://localhost:{api_port}/docs', '_blank');</script>Opening documentation..."), 
                outputs=menu_output
            )
        
        # Launch the interface
        interface.launch(server_name=server_name, server_port=server_port, **kwargs)

# For standalone use
if __name__ == "__main__":
    ui = AgentUI()
    ui.launch()

__all__ = ["stream_to_gradio", "AgentUI"]