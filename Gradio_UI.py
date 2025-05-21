import gradio as gr
from typing import Optional
import os
from fastapi.responses import RedirectResponse

class GradioUI:
    """A Gradio interface that serves as a frontend for the agent API"""

    def __init__(self, agent=None, file_upload_folder: str = None):
        self.agent = agent
        self.file_upload_folder = file_upload_folder
        
        if self.file_upload_folder is not None:
            if not os.path.exists(file_upload_folder):
                os.makedirs(file_upload_folder, exist_ok=True)

    def create_interface(self):
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
                flex-grow: 1;
            }
            .button-container {
                padding: 10px;
            }
        """) as interface:
            with gr.Row(elem_id="main-container"):
                # Left menu strip (1/4 width)
                with gr.Column(scale=1, elem_id="menu-column"):
                    gr.Markdown("# Menu")
                    with gr.Group(elem_classes="button-container"):
                        new_chat_btn = gr.Button("New Chat", variant="primary")
                    
                    # Output area for button actions
                    menu_output = gr.HTML(label="Action Result")
                
                # Right chat console (3/4 width)
                with gr.Column(scale=3, elem_id="chat-column"):
                    gr.Markdown("# AI Assistant")
                    chatbot = gr.Chatbot(
                        height=500,
                        type='messages'
                    )
                    msg = gr.Textbox(
                        placeholder="Ask me anything...",
                        show_label=False,
                        container=False
                    )
                    clear = gr.Button("Clear")

            def handle_new_chat():
                return None, "Started new conversation"

            def user_input(message, history):
                # Show user message immediately
                history = history + [{"role": "user", "content": message}]
                yield "", history  # This updates the UI right away

                try:
                    response = self.agent.invoke({
                        "input": message
                    })
                    final_answer = response.get("output", "No response generated")
                    thought_process = response.get("full_thought_process") or response.get("intermediate_steps") or ""
                    if thought_process and thought_process != final_answer:
                        assistant_message = f"**Final Answer:** {final_answer}\n\n**Thought Process:**\n{thought_process}"
                    else:
                        assistant_message = final_answer
                    history = history + [{"role": "assistant", "content": assistant_message}]
                    yield "", history  # This updates the UI with the assistant's response
                except Exception as e:
                    history = history + [{"role": "assistant", "content": f"Error: {str(e)}"}]
                    yield "", history

            # Set up event handlers
            msg.submit(user_input, [msg, chatbot], [msg, chatbot])
            clear.click(lambda: None, None, chatbot, queue=False)
            new_chat_btn.click(
                fn=handle_new_chat,
                inputs=[],
                outputs=[chatbot, menu_output]
            )

        return interface

    def launch(self, **kwargs):
        """Launch the Gradio interface standalone (for development)"""
        interface = self.create_interface()
        interface.launch(**kwargs)

__all__ = ["GradioUI"] 