from langchain_core.tools import tool
from datetime import datetime
import pytz
from helpers.helper import clean_input
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


@tool
def current_date_and_time(timezone: str) -> str:
    """Get current date and time based on the timezone
    Args:
        timezone: timezone such as 'America/New_York', 'Europe/Athens', 'US/Central'
    Returns:
        return current date and time in format '%Y:%m:%d %H:%M:%S %Z %z'
    """
    try:
        logging.info(f"\n Get current date and time for Timezone: {timezone}")
        clean_timezone = clean_input(timezone)
        tz = pytz.timezone(clean_timezone)
        current_time = datetime.now(tz)
        result = current_time.strftime('%Y:%m:%d %H:%M:%S %Z %z')
        if not result:
            return f"Can't get current time and date for timezone '{clean_timezone}'"
        return result
    except Exception as e:
        return f"Error getting current time and date for timezone '{clean_timezone}': {str(e)}" 