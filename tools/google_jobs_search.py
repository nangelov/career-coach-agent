from langchain_community.tools.google_jobs import GoogleJobsQueryRun
from langchain_community.utilities.google_jobs import GoogleJobsAPIWrapper
from langchain_core.tools import tool
from .helper import clean_input
import os

if not os.getenv('SERPAPI_API_KEY'):
    raise ValueError("Please set SERPAPI_API_KEY environment variable")

@tool
def google_job_search(query: str) -> str:
    """Performs a search for actual jobs and job posts in internet using Google jobs tool. Use when asked to provide jobs or job ads or job posts
    Args:
        query: The search query to look for job postings
    Returns:
        A formatted string containing job listings with titles, companies, locations, and links
    """
    try:
        print(f"\n Google Job search tool with query: {query}")

        clean_query = clean_input(query)
        # Initialize the API wrapper
        api_wrapper = GoogleJobsAPIWrapper()
        tool_instance = GoogleJobsQueryRun(api_wrapper=api_wrapper)

        # Run the search
        results = tool_instance.run(clean_query)

        if not results or results.strip() == "":
            return f"No job results found for query: '{clean_query}'. Try using different keywords or location terms."

        # Return results directly - let the agent handle formatting
        return results

    except Exception as e:
        error_msg = str(e)
        print(f"Error in google_job_search: {error_msg}")

        # Return a helpful error message instead of trying fallback
        return f"I'm unable to search for jobs right now due to a technical issue. Please try searching manually on Google Jobs, LinkedIn, Indeed, or other job boards for '{clean_query}'."