"""
Response Generator
==================

Translates raw execution results into natural, conversational language
for the TTS engine to speak.
"""

from typing import Any
import re

def _clean_time_string(time_str: str) -> str:
    """Format an ISO time string like '2026-06-22 15:16:00' into speakable English."""
    try:
        from datetime import datetime
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("The current time is %I:%M %p.")
    except Exception:
        return f"The current time is {time_str}"


def generate_response(execution_results: list[dict[str, Any]]) -> str:
    """Generate a single cohesive spoken response from a list of execution results."""
    
    if not execution_results:
        return "I have completed the request."
        
    phrases = []
    
    for result in execution_results:
        success = result.get("success", False)
        tool = result.get("tool", "")
        args = result.get("args", {})
        output = result.get("output", "")
        requires_confirm = result.get("requires_confirmation", False)
        
        # 1. Handle Safety Blocks
        if requires_confirm:
            phrases.append("I have blocked this command for safety reasons. Please confirm if you want to proceed.")
            continue
            
        # 2. Handle Execution Errors
        if not success:
            msg = result.get("message", "")
            if msg and ("couldn't" in msg.lower() or "failed" in msg.lower() or "not" in msg.lower()):
                phrases.append(msg)
            else:
                tool_friendly = tool.replace("_", " ")
                phrases.append(f"I encountered an error while trying to {tool_friendly}.")
            continue
            
        # 3. Handle specific tools
        msg = result.get("message", "")

        if tool in ("resolve_and_open", "open_application", "launch_application", "open_spotify", "open_gmail", "open_telegram"):
            if msg:
                phrases.append(msg)
            else:
                phrases.append("Opened the application.")
        elif tool == "open_browser":
            if msg:
                phrases.append(msg)
            else:
                phrases.append("Opening the browser.")
        elif tool == "open_website":
            if msg:
                phrases.append(msg)
            else:
                phrases.append("Opened the website.")
        elif tool == "search_web":
            if "Searched web for:" in msg:
                query = msg.split("Searched web for: ")[-1]
                phrases.append(f"Searching for {query}.")
            elif msg:
                phrases.append(msg)
            else:
                phrases.append("Searching the web.")
        elif tool == "open_terminal":
            phrases.append("Opening the terminal.")
        elif tool == "open_file_manager":
            phrases.append("Opening the file manager.")
        elif tool == "check_time":
            phrases.append(_clean_time_string(output))
        elif tool == "take_screenshot":
            phrases.append("Taking a screenshot.")
        elif tool == "list_files":
            match = re.search(r"Listed (\d+) files", msg)
            count = match.group(1) if match else "several"
            phrases.append(f"I found {count} files in the directory.")
        elif tool == "check_memory":
            phrases.append("I have retrieved the memory usage.")
        elif tool == "system_info":
            phrases.append("I have retrieved the system information.")
        elif tool == "find_document_by_context":
            if output and isinstance(output, str):
                phrases.append(output)
            else:
                phrases.append("I have searched for the requested document.")
        else:
            if msg and not msg.startswith("{"):
                phrases.append(msg)
            elif output and isinstance(output, str) and not output.startswith("{"):
                phrases.append(output)
            else:
                tool_friendly = tool.replace("_", " ")
                phrases.append(f"Completed {tool_friendly}.")
            
    # Combine phrases elegantly. If multiple actions, join with "and"
    if len(phrases) == 1:
        return phrases[0]
    elif len(phrases) == 2:
        return f"{phrases[0]} {phrases[1]}".replace("Opening the browser. Searching for", "Opening the browser and searching for")
    else:
        return " ".join(phrases[:-1]) + " and " + phrases[-1].lower()

