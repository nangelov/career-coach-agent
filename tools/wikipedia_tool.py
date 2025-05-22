from langchain_core.tools import tool
from langchain_community.tools import WikipediaQueryRun
from langchain_community.utilities import WikipediaAPIWrapper

@tool
def wikipedia_search(topic: str) -> str:
    """Useful for when you need to look up a topic, country, coaching methods or person on wikipedia.
    Args:
        topic: The topic to search for on Wikipedia
    Returns:
        A string containing the Wikipedia summary of the topic
    """
    try:
        print("Wikipedia search called with topic: ",topic)
        wiki = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())
        result = wiki.run(topic)
        if not result:
            return f"No Wikipedia article found for '{topic}'"
        return result
    except Exception as e:
        return f"Error searching Wikipedia for '{topic}': {str(e)}" 