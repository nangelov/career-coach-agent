from langchain_core.tools import tool
from langchain_experimental.utilities import PythonREPL

@tool
def run_python_code(code: str) -> str:
    """Description: useful for when you need to use python to answer a question. You should input python code"""
    try:
        python_repl = PythonREPL()
        return python_repl.run(code)
    except Exception as e:
        return f"Error: {str(e)}" 