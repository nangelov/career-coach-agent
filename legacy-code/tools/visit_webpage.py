from langchain_core.tools import tool
import requests
import markdownify
import re
from requests.exceptions import RequestException
from helpers.helper import clean_input
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

@tool
def visit_webpage(url: str) -> str:
    """Visits a webpage at the given url and reads its content as a markdown string.
    Args:
        url: The URL of the webpage to visit
    Returns:
        A string containing the webpage content in markdown format
    """
    try:
        logging.info(f"\n Visit Webpage search called with url: {url}")
        # Send a GET request to the URL with a 20-second timeout
        clean_url = clean_input(url)
        response = requests.get(clean_url, timeout=20)
        response.raise_for_status()  # Raise an exception for bad status codes

        # Convert the HTML content to Markdown
        markdown_content = markdownify.markdownify(response.text).strip()

        # Remove multiple line breaks
        markdown_content = re.sub(r"\n{3,}", "\n\n", markdown_content)

        # Truncate content to reasonable size
        max_length = 10000
        if len(markdown_content) > max_length:
            markdown_content = markdown_content[:max_length] + "...(content truncated)"

        return markdown_content

    except requests.exceptions.Timeout:
        return "Error: The request timed out after 20 seconds. Please try again later or check the URL."
    except requests.exceptions.HTTPError as e:
        return f"Error: HTTP {e.response.status_code} - Could not access the webpage. Please check the URL."
    except requests.exceptions.ConnectionError:
        return "Error: Could not connect to the webpage. Please check your internet connection and the URL."
    except RequestException as e:
        return f"Error: Failed to fetch the webpage: {str(e)}"
    except Exception as e:
        return f"Error: An unexpected error occurred while visiting the webpage: {str(e)}"

