from langchain_core.tools import tool
import datetime
import pytz

@tool
def get_current_time(timezone: str = "UTC") -> str:
    """Get the current time in the specified timezone."""
    try:
        tz = pytz.timezone(timezone)
        current_time = datetime.datetime.now(tz)
        return current_time.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception as e:
        return f"Error: {str(e)}" 