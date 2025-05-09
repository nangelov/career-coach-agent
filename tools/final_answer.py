from langchain_core.tools import tool
from typing import Any

@tool
def final_answer(answer: Any) -> Any:
    """Provides a final answer to the given problem.
    
    Args:
        answer: The final answer to the problem
        
    Returns:
        The final answer unchanged
    """
    return answer
