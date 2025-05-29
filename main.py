import uvicorn
from app import app
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def main():
    """
    Run the FastAPI server with integrated React UI
    """
    port = 7860
    host = "0.0.0.0"

    logging.info(f"Starting server on {host}:{port}...")
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    main()