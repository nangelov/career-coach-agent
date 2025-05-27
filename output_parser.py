from langchain.agents.output_parsers import ReActSingleInputOutputParser
from langchain.schema import AgentAction, AgentFinish
import re

class FlexibleOutputParser(ReActSingleInputOutputParser):
    def parse(self, text):
        # Clean up the text first
        text = text.strip()
        print(f"Raw LLM output: {text[:200]}...")  # Debug output

        # CRITICAL: Detect if LLM generated both Action and Final Answer
        has_action = "Action:" in text
        has_final_answer = "Final Answer:" in text

        if has_action and has_final_answer:
            print("ERROR: LLM generated both Action and Final Answer - extracting Action only")
            # Extract only the Action part, ignore Final Answer
            lines = text.split('\n')
            action_lines = []
            for line in lines:
                if line.strip().startswith("Final Answer:"):
                    break  # Stop at Final Answer
                action_lines.append(line)
            text = '\n'.join(action_lines).strip()
            print(f"Cleaned text: {text}")

        # Remove any trailing "Observation" that appears without content
        text = re.sub(r'\nObservation\s*:?\s*$', '', text)
        text = re.sub(r'Observation\s*:?\s*$', '', text)

        # Handle direct responses (greetings, simple questions)
        if not any(keyword in text for keyword in ["Thought:", "Action:", "Final Answer:"]):
            return AgentFinish(
                return_values={"output": text},
                log=text
            )

        # Handle responses that start with Final Answer directly
        if text.startswith("Final Answer:"):
            final_answer = text.replace("Final Answer:", "").strip()
            return AgentFinish(
                return_values={"output": final_answer},
                log=text
            )

        try:
            # Try standard ReAct parsing first
            return super().parse(text)
        except Exception as e:
            print(f"Standard parsing failed: {e}")
            # Custom parsing for malformed ReAct format
            return self._parse_malformed_react(text)
    def _handle_truncated_action(self, text):
        """Handle cases where Action is cut off"""
        if "Action:" in text and "Action Input:" not in text:
            # Action was truncated, treat as final answer
            return AgentFinish(
                return_values={"output": "I need to search for more information. Could you please ask your question again?"},
                log=text
            )
        return None

    def _parse_malformed_react(self, text):
        """Handle malformed ReAct format responses"""

        # Clean special tokens from the entire text first
        text = re.sub(r'<\|eot_id\|>', '', text)
        text = re.sub(r'<\|eom_id\|>', '', text)
        text = re.sub(r'<\|.*?\|>', '', text)
        text = text.strip()

        # Check if this is a response that should be a Final Answer but is missing the prefix
        if self._should_be_final_answer(text):
            print("Detected response that should be Final Answer - treating as final answer")
            return AgentFinish(
                return_values={"output": text},
                log=text
            )

        # Check if this looks like job search results that should be preserved as-is
        if self._is_job_search_result(text) and "Action:" not in text:
            print("Detected job search results in full text - preserving formatting")
            return AgentFinish(
                return_values={"output": text},
                log=text
            )

        lines = [line.strip() for line in text.split('\n') if line.strip()]

        thought = ""
        action = ""
        action_input = ""
        final_answer = ""

        i = 0
        while i < len(lines):
            line = lines[i]

            if line.startswith("Thought:"):
                thought = line.replace("Thought:", "").strip()

            elif line.startswith("Action:"):
                action = line.replace("Action:", "").strip()

            elif line.startswith("Action Input:"):
                action_input = line.replace("Action Input:", "").strip()

                # Clean action input more aggressively
                action_input = self._clean_action_input(action_input)

            elif line.startswith("Final Answer:"):
                final_answer = line.replace("Final Answer:", "").strip()

                # Collect multi-line final answer
                j = i + 1
                while j < len(lines):
                    if lines[j].strip() and not lines[j].startswith(("Thought:", "Action:", "Observation:", "Human:")):
                        final_answer += " " + lines[j].strip()
                        j += 1
                    else:
                        break

            i += 1

        # Additional cleaning of action_input if it exists
        if action_input:
            action_input = re.sub(r'\s*Observation\s*:?\s*$', '', action_input)
            action_input = re.sub(r'^["\']|["\']$', '', action_input)
            action_input = re.sub(r'\s*#.*$', '', action_input)
            action_input = action_input.strip()

            if len(action_input) > 200:
                print(f"WARNING: Action input too long ({len(action_input)} chars), truncating")
                action_input = action_input[:200].strip()

        # Check for incomplete action
        if action and not action_input:
            print("ERROR: Action without Action Input - treating as final answer")
            return AgentFinish(
                return_values={"output": "I apologize, but I need more information to help you properly. Could you please rephrase your question?"},
                log=text
            )

        # If we have action and action_input, return AgentAction
        if action and action_input:
            print(f"Parsed Action: {action}")
            print(f"Parsed Action Input: '{action_input}'")
            return AgentAction(
                tool=action,
                tool_input=action_input,
                log=text
            )

        # If we have final_answer, return AgentFinish
        if final_answer:
            return AgentFinish(
                return_values={"output": final_answer},
                log=text
            )

        # Fallback: return the whole text as final answer
        return AgentFinish(
            return_values={"output": text},
            log=text
        )

    def _should_be_final_answer(self, text):
        """Check if this text should be treated as a final answer"""
        # Indicators that this is a final response
        final_indicators = [
            "based on the observation",
            "based on the search",
            "according to",
            "the winner",
            "manchester city",
            "liverpool",
            "premier league",
            "champions",
            "most recent",
            "in conclusion",
            "therefore",
            "the answer is",
            "the results show",
            "from the search results"
        ]

        # Check if it contains final answer indicators and no action keywords
        has_final_indicators = any(indicator in text.lower() for indicator in final_indicators)
        has_action_keywords = any(keyword in text for keyword in ["Action:", "Thought:", "Action Input:"])

        return has_final_indicators and not has_action_keywords

    def _clean_action_input(self, action_input: str) -> str:
        """Clean action input by removing special tokens and unwanted text"""
        # Remove special tokens
        action_input = re.sub(r'<\|eot_id\|>', '', action_input)
        action_input = re.sub(r'<\|eom_id\|>', '', action_input)
        action_input = re.sub(r'<\|.*?\|>', '', action_input)

        # Remove everything after newlines (take only first line)
        action_input = action_input.split('\n')[0]

        # Remove everything after common stop words
        stop_words = ['Thought:', 'Action:', 'Observation:', 'Human:', 'Assistant:']
        for stop_word in stop_words:
            if stop_word in action_input:
                action_input = action_input.split(stop_word)[0]

        # Remove quotes if they wrap the entire input
        action_input = re.sub(r'^["\']|["\']$', '', action_input)

        # Remove any trailing special characters or whitespace
        action_input = action_input.strip()

        return action_input

    def _is_job_search_result(self, text):
        """Check if the text contains job search results that should be preserved"""
        job_indicators = [
            "Job Title:", "Company:", "Location:", "job listings",
            "Found", "jobs", "position", "role", "employment",
            "**", "- Company:", "- Location:", "Link:"
        ]
        return any(indicator.lower() in text.lower() for indicator in job_indicators)

def clean_llm_response(output):
    """Clean up the LLM response to extract just the user-facing part."""

    # Remove special tokens first
    if "<|eot_id|>" in output:
        output = output.split("<|eot_id|>")[0]

    # Remove "Human:" and everything after it (most aggressive cleaning)
    if "Human:" in output:
        output = output.split("Human:")[0].strip()

    # Remove trailing newlines and "Human" without colon
    output = re.sub(r'\s*Human\s*$', '', output)
    output = re.sub(r'\s*\n\s*$', '', output)

    # If there's a Final Answer, extract only that part
    if "Final Answer:" in output:
        # Find the last occurrence of "Final Answer:" in case there are multiple
        last_final_answer_index = output.rindex("Final Answer:")
        final_answer = output[last_final_answer_index + len("Final Answer:"):].strip()

        # Clean up any remaining artifacts from final answer
        if "Human:" in final_answer:
            final_answer = final_answer.split("Human:")[0].strip()

        return final_answer

    # Remove any remaining internal instructions or notes
    lines = output.split("\n")
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        # Skip lines that look like internal notes or instructions
        if (line.startswith("Let's") or "instead" in line.lower() or
            "attempt" in line.lower() or "should" in line.lower() or
            line.startswith("Human") or not line):
            continue
        cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()