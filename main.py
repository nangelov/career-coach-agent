import threading
import time
import uvicorn
from app import app, agent
from UI import AgentUI

def main():
    """
    Run both FastAPI and Gradio UI together
    """
    # Start FastAPI in a background thread
    def run_fastapi():
        uvicorn.run(app, host="0.0.0.0", port=8000)
    
    api_thread = threading.Thread(target=run_fastapi)
    api_thread.daemon = True
    api_thread.start()
    
    # Give FastAPI time to start
    print("Starting FastAPI server...")
    time.sleep(1)
    
    # Start Gradio UI in the main thread
    print("Starting Gradio UI...")
    gradio_ui = AgentUI(agent=agent, api_url="http://localhost:8000")
    gradio_ui.launch(server_port=7860)

if __name__ == "__main__":
    main() 