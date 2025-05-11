import uvicorn
from app import app, agent
from UI import AgentUI

def main():
    """
    Run FastAPI and Gradio UI on the same port
    """
    # Configuration
    port = 7860
    
    # Create and mount Gradio app
    gradio_ui = AgentUI(
        agent=agent,
        api_url=f"http://localhost:{port}"
    )
    app.mount("/", gradio_ui.get_gradio_app())
    
    # Start the combined app
    print(f"Starting combined server on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main() 