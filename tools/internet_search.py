from langchain_core.tools import tool
from langchain_community.tools import DuckDuckGoSearchResults

@tool
def internet_search(query: str) -> str:
    """Performs an internet search using DuckDuckGo.
    Args:
        query: The search query to look up
    Returns:
        A string containing the search results
    """
    try:
        print("Internet search tool with query: ",query)
        search = DuckDuckGoSearchResults()
        results = search.run(query)
        if not results:
            return f"No results found for query: '{query}'"
        return results
    except Exception as e:
        return f"Error: Failed to perform internet search - {str(e)}" 