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

                # Handle multi-line action input (especially for code blocks)
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    # Stop if we hit another ReAct keyword
                    if any(next_line.startswith(keyword) for keyword in ["Thought:", "Action:", "Observation:", "Final Answer:", "Human:"]):
                        break
                    action_input += "\n" + next_line
                    j += 1
                i = j - 1  # Adjust index to account for consumed lines

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
            print(f"Parsed Action Input: '{action_input[:100]}...'")
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
            "from the search results",
            "personal development plan",
            "skills gap analysis",
            "development objectives",
            "career progression",
            "learning milestones"
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

        # Handle code blocks properly
        if "```" in action_input:
            # Extract content between triple backticks
            code_match = re.search(r'```(?:python)?\s*(.*?)\s*```', action_input, re.DOTALL)
            if code_match:
                action_input = code_match.group(1).strip()
            else:
                # If we have opening ``` but no closing, take everything after it
                if action_input.count('```') == 1:
                    parts = action_input.split('```', 1)
                    if len(parts) > 1:
                        action_input = parts[1].strip()
                        # Remove any language identifier
                        if action_input.startswith('python'):
                            action_input = action_input[6:].strip()
                        elif action_input.startswith('\npython'):
                            action_input = action_input[7:].strip()

        # Remove everything after common stop words (but preserve code structure)
        stop_words = ['Thought:', 'Action:', 'Observation:', 'Human:', 'Assistant:', 'Please see below', 'Now that we']
        for stop_word in stop_words:
            if stop_word in action_input:
                action_input = action_input.split(stop_word)[0]

        # Remove quotes if they wrap the entire input (but not if they're part of code)
        if not ('"""' in action_input or "'''" in action_input or 'print(' in action_input):
            action_input = re.sub(r'^["\']|["\']$', '', action_input)

        # Remove any trailing special characters or whitespace
        action_input = action_input.strip()

        # Remove any trailing text that looks like instructions
        lines = action_input.split('\n')
        cleaned_lines = []
        skip_rest = False
        
        for line in lines:
            # Skip lines that look like instructions or comments after code
            if (skip_rest or 
                line.strip().startswith('Please see below') or
                line.strip().startswith('Now that we') or
                line.strip().startswith('Based on the output') or
                line.strip().startswith('After running') or
                line.strip().startswith('The output') or
                line.strip().startswith('Here is') or
                line.strip().startswith('Let me') or
                line.strip().startswith('I will') or
                line.strip().startswith('Next,') or
                line.strip().startswith('Then,') or
                line.strip().startswith('Finally,') or
                re.match(r'^\s*#.*instructions.*', line, re.IGNORECASE) or
                re.match(r'^\s*#.*note.*', line, re.IGNORECASE)):
                skip_rest = True
                break
            cleaned_lines.append(line)

        action_input = '\n'.join(cleaned_lines).strip()

        # Final cleanup - remove any remaining trailing instructions
        action_input = re.sub(r'\n\s*Please.*$', '', action_input, flags=re.DOTALL)
        action_input = re.sub(r'\n\s*Now.*$', '', action_input, flags=re.DOTALL)
        action_input = re.sub(r'\n\s*Based on.*$', '', action_input, flags=re.DOTALL)

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

    if "<|eom_id|>" in output:
        output = output.split("<|eom_id|>")[0]

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
            line.startswith("Human") or not line or
            line.startswith("I will") or line.startswith("Next,") or
            line.startswith("Then,") or line.startswith("Finally,")):
            continue
        cleaned_lines.append(line)

    result = "\n".join(cleaned_lines).strip()

    # Final cleanup
    result = re.sub(r'\n\s*Please.*$', '', result, flags=re.DOTALL)
    result = re.sub(r'\n\s*Now.*$', '', result, flags=re.DOTALL)
    result = re.sub(r'\n\s*Based on.*$', '', result, flags=re.DOTALL)

    return result