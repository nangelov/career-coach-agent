import threading
import time
import uvicorn
from app import app, agent
from UI import AgentUI

def main():
    """
    Run both FastAPI and Gradio UI together
    """
    # Configuration
    api_port = 8080
    ui_port = 8000
    
    # Start FastAPI in a background thread
    def run_fastapi():
        uvicorn.run(app, host="0.0.0.0", port=api_port)
    
    api_thread = threading.Thread(target=run_fastapi)
    api_thread.daemon = True
    api_thread.start()
    
    # Give FastAPI time to start
    print(f"Starting FastAPI server on port {api_port}...")
    time.sleep(1)
    
    # Start Gradio UI in the main thread
    print(f"Starting Gradio UI on port {ui_port}...")
    gradio_ui = AgentUI(
        agent=agent,
        api_url=f"http://localhost:{api_port}"
    )
    gradio_ui.launch(server_port=ui_port)

if __name__ == "__main__":
    main() 