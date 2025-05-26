from langchain.agents.output_parsers import ReActSingleInputOutputParser
from langchain.schema import AgentAction, AgentFinish
import re

class FlexibleOutputParser(ReActSingleInputOutputParser):
    def parse(self, text):
        # Clean up the text first
        text = text.strip()

        # Remove any trailing "Observation" that appears without content
        text = re.sub(r'\nObservation\s*$', '', text)
        text = re.sub(r'Observation\s*$', '', text)

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

    def _parse_malformed_react(self, text):
        """Handle malformed ReAct format responses"""
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

                # Collect multi-line action input until we hit another keyword or end
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    if any(next_line.startswith(kw) for kw in ["Thought:", "Action:", "Final Answer:", "Observation"]):
                        break
                    if next_line.strip():  # Only add non-empty lines
                        action_input += " " + next_line.strip()
                    j += 1
                i = j - 1  # Adjust index since we've processed multiple lines

            elif line.startswith("Final Answer:"):
                final_answer = line.replace("Final Answer:", "").strip()

                # Collect multi-line final answer
                j = i + 1
                while j < len(lines):
                    if lines[j].strip():
                        final_answer += " " + lines[j].strip()
                    j += 1
                break

            i += 1

        # Clean up action_input - remove any trailing "Observation" or similar artifacts
        if action_input:
            action_input = re.sub(r'\s*Observation\s*$', '', action_input)
            action_input = action_input.strip()

        # If we have action and action_input, return AgentAction
        if action and action_input:
            print(f"Parsed Action: {action}")
            print(f"Parsed Action Input: {action_input}")
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

def clean_llm_response(output):
    """Clean up the LLM response to extract just the user-facing part."""

    # Remove special tokens
    if "<|eot_id|>" in output:
        output = output.split("<|eot_id|>")[0]

    # If there's a Final Answer, extract only that part
    if "Final Answer:" in output:
        # Find the last occurrence of "Final Answer:" in case there are multiple
        last_final_answer_index = output.rindex("Final Answer:")
        final_answer = output[last_final_answer_index + len("Final Answer:"):].strip()

        # Clean up any remaining artifacts
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
            not line):
            continue
        cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()