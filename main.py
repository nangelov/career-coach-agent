import uvicorn
from app import app

def main():
    """
    Run the FastAPI server with integrated Gradio UI
    """
    port = 7860
    host = "0.0.0.0"
    
    print(f"Starting server on {host}:{port}...")
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    main() 