from langchain_core.tools import tool
from langchain_experimental.utilities import PythonREPL
from helpers.helper import clean_input
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

@tool
def run_python_code(code: str) -> str:
    """Runs Python code and returns the output.
    Args:
        code: The Python code to execute
    Returns:
        A string containing the output of the executed code
    """
    try:
        logging.info(f"\n run python code with code: {code}")

        # Clean the code by removing special tokens and unwanted text
        cleaned_code = clean_input(code)
        logging.info(f"cleaned code: {cleaned_code}")

        python_repl = PythonREPL()
        result = python_repl.run(cleaned_code)
        if result is None:
            return "Code executed successfully but returned no output."
        return str(result)
    except SyntaxError as e:
        return f"Error: Invalid Python syntax - {str(e)}"
    except NameError as e:
        return f"Error: Undefined variable or function - {str(e)}"
    except Exception as e:
        return f"Error: Failed to execute Python code - {str(e)}"

