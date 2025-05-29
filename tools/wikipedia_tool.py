from langchain_core.tools import tool
from langchain_community.tools import WikipediaQueryRun
from langchain_community.utilities import WikipediaAPIWrapper
from helpers.helper import clean_input

@tool
def wikipedia_search(topic: str) -> str:
    """Useful for when you need to look up a topic, country, coaching methods or person on wikipedia.
    Args:
        topic: The topic to search for on Wikipedia
    Returns:
        A string containing the Wikipedia summary of the topic
    """
    try:
        print("\n Wikipedia search called with topic: ",topic)
        wiki = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())
        clean_topic = clean_input(topic)
        result = wiki.run(clean_topic)
        if not result:
            return f"No Wikipedia article found for '{clean_topic}'"
        return result
    except Exception as e:
        return f"Error searching Wikipedia for '{clean_topic}': {str(e)}" 