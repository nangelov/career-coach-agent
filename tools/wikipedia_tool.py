from langchain_core.tools import tool
from langchain_community.tools import WikipediaQueryRun
from langchain_community.utilities import WikipediaAPIWrapper

@tool
def wikipedia_search(topic: str) -> str:
    """Useful for when you need to look up a topic, country, coaching methods or person on wikipedia
    """
    try:
        wiki = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())
        return wiki.run(topic)
    except Exception as e:
        return f"Error: {str(e)}" 