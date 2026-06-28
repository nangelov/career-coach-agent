from langchain_core.tools import tool
from langchain_community.tools import DuckDuckGoSearchResults
from helpers.helper import clean_input
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

@tool
def internet_search(query: str) -> str:
    """Performs an internet search using DuckDuckGo.
    Args:
        query: The search query to look up
    Returns:
        A string containing the search results
    """
    try:
        # Clean the query by removing special tokens
        cleaned_query = clean_input(query)
        logging.info(f"\n Internet search tool with query: {cleaned_query}")

        search = DuckDuckGoSearchResults()
        results = search.run(cleaned_query)
        if not results:
            return f"No results found for query: '{cleaned_query}'"
        return results
    except Exception as e:
        return f"Error: Failed to perform internet search - {str(e)}"

