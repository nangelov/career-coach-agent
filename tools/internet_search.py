from langchain_core.tools import tool
from langchain_community.tools import DuckDuckGoSearchResults

@tool
def internet_search(query: str) -> str:
    """Description: Useful for when you need to do a search on the internet to find information that another tool can't find. be specific with your input."""
    try:
        search = DuckDuckGoSearchResults()
        return search.run(query)
    except Exception as e:
        return f"Error: {str(e)}" 