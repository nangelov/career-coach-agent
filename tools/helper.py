import re

def clean_input(input: str) -> str:
    """Clean the code input by removing special tokens and unwanted text"""
    # Remove special tokens
    input = re.sub(r'<\|eom_id\|>', '', input)
    input = re.sub(r'<\|eot_id\|>', '', input)
    input = re.sub(r'<\|.*?\|>', '', input)  # Remove any other special tokens

    # Remove any trailing newlines or whitespace
    input = input.strip()

    # Remove any text after common stop patterns
    stop_patterns = [
        'Observation:',
        'Human:',
        'Assistant:',
        'Thought:',
        'Action:',
        'Action Input:'
    ]

    for pattern in stop_patterns:
        if pattern in input:
            input = input.split(pattern)[0].strip()

    return input