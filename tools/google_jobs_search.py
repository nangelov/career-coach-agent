from langchain_community.tools.google_jobs import GoogleJobsQueryRun
from langchain_community.utilities.google_jobs import GoogleJobsAPIWrapper
from langchain_core.tools import tool
from helpers.helper import clean_input
import os

if not os.getenv('SERPAPI_API_KEY'):
    raise ValueError("Please set SERPAPI_API_KEY environment variable")

def format_job_results(jobs: list, query: str) -> str:
    """Format job results into a readable string"""
    if not jobs:
        return f"No job results found for query: '{query}'. Try using different keywords or location terms."

    formatted_results = []
    formatted_results.append(f"Found {len(jobs)} job results for '{query}':\n")

    for i, job in enumerate(jobs[:10], 1):  # Limit to first 10 results
        try:
            title = job.get('title', 'No title available')
            company = job.get('company_name', job.get('company', 'Company not specified'))
            location = job.get('location', 'Location not specified')
            link = job.get('link', job.get('url', job.get('apply_link', '')))
            description = job.get('description', job.get('snippet', ''))
            salary = job.get('salary', '')

            job_text = f"{i}. **{title}**\n"
            job_text += f"   Company: {company}\n"
            job_text += f"   Location: {location}\n"

            if salary:
                job_text += f"   Salary: {salary}\n"

            if link:
                job_text += f"   Apply: {link}\n"

            if description:
                desc_preview = description[:150] + "..." if len(description) > 150 else description
                job_text += f"   Description: {desc_preview}\n"

            job_text += "\n"
            formatted_results.append(job_text)

        except Exception:
            continue

    return "".join(formatted_results)

def serpapi_fallback(query: str) -> str:
    """Direct SerpAPI call as fallback when LangChain wrapper fails"""
    try:
        import serpapi

        search = serpapi.GoogleSearch({
            "q": query,
            "location": "Munich, Germany" if "munich" in query.lower() else None,
            "api_key": os.getenv('SERPAPI_API_KEY'),
            "engine": "google_jobs"
        })

        results = search.get_dict()
        jobs = results.get('jobs_results', [])

        if jobs:
            return format_job_results(jobs, query)
        else:
            return f"No job results found for query: '{query}'. Try using different keywords or location terms."

    except ImportError:
        return f"Fallback search unavailable. Please try searching manually on Google Jobs, LinkedIn, Indeed, or other job boards for '{query}'."
    except Exception:
        return f"Search temporarily unavailable. Please try searching manually on Google Jobs, LinkedIn, Indeed, or other job boards for '{query}'."

@tool
def google_job_search(query: str) -> str:
    """Performs a search for actual jobs and job posts in internet using Google jobs tool. Use when asked to provide jobs or job ads or job posts
    Args:
        query: The search query to look for job postings
    Returns:
        A formatted string containing job listings with titles, companies, locations, and links
    """
    try:
        clean_query = clean_input(query)

        # Try LangChain wrapper first
        try:
            api_wrapper = GoogleJobsAPIWrapper()
            tool_instance = GoogleJobsQueryRun(api_wrapper=api_wrapper)
            results = tool_instance.run(clean_query)

            if results and results.strip():
                return results
            else:
                return serpapi_fallback(clean_query)

        except KeyError as e:
            # LangChain wrapper failed with jobs_results error, use fallback
            if "'jobs_results'" in str(e):
                return serpapi_fallback(clean_query)
            else:
                raise e

    except Exception:
        # Try fallback for any other errors
        if "clean_query" in locals():
            fallback_result = serpapi_fallback(clean_query)
            if "Search temporarily unavailable" not in fallback_result:
                return fallback_result

        # If fallback also fails, return helpful error message
        query_name = clean_query if "clean_query" in locals() else query
        return f"I'm unable to search for jobs right now. Please try searching manually on Google Jobs, LinkedIn, Indeed, or other job boards for '{query_name}'."
