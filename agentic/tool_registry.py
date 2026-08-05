"""
Tool Registry
=============

Declarative definitions of all tools available to the LLM Planner.
These definitions are injected into the system prompt as JSON schemas.
"""

from agentic.schemas import ToolDefinition

# ══════════════════════════════════════════════════════════════════════
# THE REGISTRY
# ══════════════════════════════════════════════════════════════════════

_TOOLS: list[ToolDefinition] = [

    ToolDefinition(
        name="open_browser",
        description="Launch the default web browser. Do not use this if you also need to search immediately; use search_web instead.",
        parameters={
            "type": "object",
            "properties": {
                "browser": {
                    "type": "string",
                    "description": "Optional specific browser to open (e.g., 'chrome', 'firefox')."
                }
            },
            "required": []
        }
    ),
    
    ToolDefinition(
        name="search_web",
        description="Search the internet for a specific query.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query."
                },
                "application": {
                    "type": "string",
                    "description": "Optional browser or search engine to use (e.g., 'chrome', 'google')."
                }
            },
            "required": ["query"]
        }
    ),
    
    ToolDefinition(
        name="open_application",
        description="Open or launch a desktop application.",
        parameters={
            "type": "object",
            "properties": {
                "application": {
                    "type": "string",
                    "description": "The name of the application to open."
                }
            },
            "required": ["application"]
        }
    ),
    
    ToolDefinition(
        name="check_time",
        description="Get the current system local time.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),
    
    ToolDefinition(
        name="list_files",
        description="List files in a given directory.",
        parameters={
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "The path to the directory. Omit to list the current directory."
                }
            },
            "required": []
        }
    ),
    
    ToolDefinition(
        name="take_screenshot",
        description="Take a screenshot of the user's screen.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),
    
    ToolDefinition(
        name="open_file_manager",
        description="Open the OS file explorer/manager.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),
    
    ToolDefinition(
        name="check_memory",
        description="Check the current RAM/memory usage of the system.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),
    
    ToolDefinition(
        name="open_folder",
        description="Open a system folder or workspace by its absolute path or folder name.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The absolute path or name of the folder to open."
                }
            },
            "required": ["path"]
        }
    ),

    ToolDefinition(
        name="open_file",
        description="Open a file with its default associated desktop application.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The absolute path or name of the file to open."
                }
            },
            "required": ["path"]
        }
    ),

    ToolDefinition(
        name="resolve_and_open",
        description="Resolve and open a desktop application, website, file or folder by fuzzy matching.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The name of the application, website, file or folder to search and open."
                }
            },
            "required": ["query"]
        }
    ),

    ToolDefinition(
        name="is_app_running",
        description="Check if a specific desktop application is currently running.",
        parameters={
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "description": "The name of the application to check."
                }
            },
            "required": ["app"]
        }
    ),

    ToolDefinition(
        name="activate_window",
        description="Bring a running application window to the foreground.",
        parameters={
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "description": "The name of the application to bring to the foreground."
                }
            },
            "required": ["app"]
        }
    ),

    ToolDefinition(
        name="get_active_window",
        description="Get details of the currently active foreground window.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),

    ToolDefinition(
        name="perform_app_action",
        description="Perform application-specific actions (e.g. Spotify search/play/pause, WhatsApp send message).",
        parameters={
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "description": "The application name (e.g. 'spotify', 'whatsapp')."
                },
                "action": {
                    "type": "string",
                    "description": "The action to perform (e.g., 'play', 'pause', 'send_message')."
                },
                "payload": {
                    "type": "object",
                    "description": "Arbitrary payload mapping containing arguments (e.g. {'song': 'Darkhaast'}, {'contact': 'Harshita', 'message': 'hi'})."
                }
            },
            "required": ["app", "action"]
        }
    ),

    # ── Hierarchical Agent Tools ─────────────────────────────────────
    
    ToolDefinition(
        name="focus_window",
        description="Bring a running application window to the foreground.",
        parameters={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "The name or window title of the target application."
                }
            },
            "required": ["target"]
        }
    ),

    ToolDefinition(
        name="launch_application",
        description="Launch an application. Integrates Windows Search as search backup if shortcuts not found.",
        parameters={
            "type": "object",
            "properties": {
                "application": {
                    "type": "string",
                    "description": "The name of the application to launch."
                }
            },
            "required": ["application"]
        }
    ),

    ToolDefinition(
        name="wait_for_window",
        description="Wait for a window with the given target title or name to load.",
        parameters={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "The window title or application name to wait for."
                },
                "timeout": {
                    "type": "integer",
                    "description": "Max timeout in seconds (default 10)."
                }
            },
            "required": ["target"]
        }
    ),

    ToolDefinition(
        name="click",
        description="Click at specific coordinate or current cursor position.",
        parameters={
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate."},
                "y": {"type": "integer", "description": "Y coordinate."},
                "button": {"type": "string", "description": "Left, right, or middle button."},
                "clicks": {"type": "integer", "description": "Number of clicks."}
            },
            "required": []
        }
    ),

    ToolDefinition(
        name="double_click",
        description="Double-click at specific coordinate or current cursor position.",
        parameters={
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate."},
                "y": {"type": "integer", "description": "Y coordinate."}
            },
            "required": []
        }
    ),

    ToolDefinition(
        name="right_click",
        description="Right-click at specific coordinate or current cursor position.",
        parameters={
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate."},
                "y": {"type": "integer", "description": "Y coordinate."}
            },
            "required": []
        }
    ),

    ToolDefinition(
        name="scroll",
        description="Scroll active window direction.",
        parameters={
            "type": "object",
            "properties": {
                "direction": {"type": "string", "description": "scroll direction ('up' or 'down')."},
                "clicks": {"type": "integer", "description": "Number of scroll intervals."}
            },
            "required": ["direction"]
        }
    ),

    ToolDefinition(
        name="type_text",
        description="Type the provided text using keyboard input simulator.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text to type."}
            },
            "required": ["text"]
        }
    ),

    ToolDefinition(
        name="press_key",
        description="Press a single keyboard key (e.g. 'enter', 'tab', 'backspace').",
        parameters={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The key name."}
            },
            "required": ["key"]
        }
    ),

    ToolDefinition(
        name="copy",
        description="Copy selection to clipboard (Ctrl+C).",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),

    ToolDefinition(
        name="paste",
        description="Paste clipboard contents (Ctrl+V).",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),

    ToolDefinition(
        name="drag",
        description="Drag mouse from start coordinate (x1, y1) to end coordinate (x2, y2).",
        parameters={
            "type": "object",
            "properties": {
                "x1": {"type": "integer"},
                "y1": {"type": "integer"},
                "x2": {"type": "integer"},
                "y2": {"type": "integer"}
            },
            "required": ["x1", "y1", "x2", "y2"]
        }
    ),

    ToolDefinition(
        name="find_text",
        description="Locate screen coordinates of text on active screen.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text to locate."}
            },
            "required": ["text"]
        }
    ),

    ToolDefinition(
        name="ocr",
        description="Perform OCR scan on foreground active window, returning structured text elements and coordinates.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),

    ToolDefinition(
        name="locate_ui_element",
        description="Find coordinates of a specific element type (e.g., button, search, input) matching a label name.",
        parameters={
            "type": "object",
            "properties": {
                "element_type": {"type": "string", "description": "E.g. 'button', 'input', 'icon', 'dropdown'."},
                "label": {"type": "string", "description": "The text label or name of the target element."}
            },
            "required": ["element_type", "label"]
        }
    ),

    ToolDefinition(
        name="wait_until",
        description="Wait until a condition is met (e.g. element visible).",
        parameters={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "The UI element name/label to wait for."},
                "timeout": {"type": "integer"}
            },
            "required": ["target"]
        }
    ),

    ToolDefinition(
        name="search_inside_application",
        description="Perform application-level search using fast keyboard shortcuts and typing.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The query to search for."}
            },
            "required": ["query"]
        }
    ),

    ToolDefinition(
        name="close_window",
        description="Close active foreground window.",
        parameters={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Application name or title to verify closing."}
            },
            "required": []
        }
    ),

    ToolDefinition(
        name="switch_tab",
        description="Switch active application tabs.",
        parameters={
            "type": "object",
            "properties": {
                "direction": {"type": "string", "description": "'next' or 'previous'."}
            },
            "required": []
        }
    ),

    ToolDefinition(
        name="select_dropdown",
        description="Select an option from a target dropdown selector.",
        parameters={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Dropdown label."},
                "option": {"type": "string", "description": "Option value to select."}
            },
            "required": ["target", "option"]
        }
    ),

    # ── Notepad Automation Tools ──────────────────────────────────────

    ToolDefinition(
        name="notepad_open",
        description="Open Microsoft Notepad. If Notepad is already running, brings it to the foreground. Always use this before any other notepad_ tool.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),

    ToolDefinition(
        name="notepad_close",
        description="Close the active Microsoft Notepad window.",
        parameters={
            "type": "object",
            "properties": {
                "save_before_close": {
                    "type": "boolean",
                    "description": "If true, saves the file before closing. Default is false."
                },
                "discard_changes": {
                    "type": "boolean",
                    "description": "If true, discards unsaved changes without saving. Default is true."
                },
                "save_first": {
                    "type": "boolean",
                    "description": "Legacy fallback argument (equivalent to save_before_close)."
                }
            },
            "required": []
        }
    ),

    ToolDefinition(
        name="notepad_type",
        description="Type text into the active Notepad window. Notepad must be open first. Use this to write content.",
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to type into Notepad."
                }
            },
            "required": ["text"]
        }
    ),

    ToolDefinition(
        name="notepad_press_enter",
        description="Press the Enter key inside Notepad to insert a new line.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),

    ToolDefinition(
        name="notepad_select_all",
        description="Select all text in Notepad (Ctrl+A).",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),

    ToolDefinition(
        name="notepad_copy",
        description="Copy the selected text in Notepad to the clipboard (Ctrl+C).",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),

    ToolDefinition(
        name="notepad_paste",
        description="Paste clipboard contents into Notepad at the current cursor position (Ctrl+V).",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),

    ToolDefinition(
        name="notepad_undo",
        description="Undo the last action performed in Notepad (Ctrl+Z).",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),

    ToolDefinition(
        name="notepad_redo",
        description="Redo the last undone action in Notepad (Ctrl+Y).",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),

    ToolDefinition(
        name="notepad_delete",
        description="Delete the currently selected text in Notepad. If nothing is selected, selects all first then deletes.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),

    ToolDefinition(
        name="notepad_clear",
        description="Clear the entire Notepad document — removes all text content.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),

    ToolDefinition(
        name="notepad_save",
        description="Save the current Notepad file (Ctrl+S). If the file has no name yet, this may open a Save-As dialog.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),

    ToolDefinition(
        name="notepad_save_as",
        description="Save the current Notepad document with a specific filename using the Save-As dialog.",
        parameters={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "The target filename, e.g. 'notes.txt'."
                },
                "directory": {
                    "type": "string",
                    "description": "Optional absolute path of the directory to save in."
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "If true, replaces the file if it already exists. Otherwise fails."
                }
            },
            "required": ["filename"]
        }
    ),

    ToolDefinition(
        name="notepad_open_file",
        description="Open an existing file inside Notepad using the Open dialog.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The absolute or relative path to the file to open in Notepad."
                }
            },
            "required": ["path"]
        }
    ),

    ToolDefinition(
        name="notepad_new_file",
        description="Create a new empty document in Notepad (Ctrl+N). Discards any unsaved changes in the current document.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),

    # ── Context-Based Document Search ────────────────────────────────────

    ToolDefinition(
        name="find_document_by_context",
        description=(
            "Intelligently locate files on the local computer when the user does NOT know the "
            "exact filename. Uses AI semantic search to match topic, project, organization, "
            "keywords, approximate content, year, technology, person name, or any phrase. "
            "Use this for intents like: find file, open document, search document, find PDF, "
            "find report, find PPT, find Excel, find my old X, I need the document about Y. "
            "Returns up to 5 ranked candidate files for the user to choose from."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "The user's free-form description of the document. "
                        "Include all context clues: topic, project name, organization, "
                        "keywords, year, technology, person name, phrases remembered. "
                        "Example: 'CDOT proposal battery project from 2021'"
                    )
                },
                "top_n": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 5, max 5)."
                }
            },
            "required": ["query"]
        }
    ),

    ToolDefinition(
        name="open_document_result",
        description=(
            "Open one of the files returned by a previous find_document_by_context call. "
            "Use this when the user selects a result by saying 'open number 1', "
            "'first one', 'second', 'number 3', etc. "
            "Always call find_document_by_context before calling this tool."
        ),
        parameters={
            "type": "object",
            "properties": {
                "result_number": {
                    "type": "integer",
                    "description": (
                        "The 1-based index of the result to open (1 through 5). "
                        "Map 'first' → 1, 'second' → 2, 'third' → 3, etc."
                    )
                }
            },
            "required": ["result_number"]
        }
    ),

    # ── External Application Pipeline Tools ──────────────────────────

    ToolDefinition(
        name="open_telegram",
        description="Launch Telegram desktop app or web interface securely via backend pipeline execution.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),

    ToolDefinition(
        name="open_gmail",
        description="Launch Gmail web interface securely via backend pipeline execution.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),

    ToolDefinition(
        name="open_spotify",
        description="Launch Spotify app or web player securely via backend pipeline execution.",
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),
]

# ══════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════

_TOOL_MAP = {t.name: t for t in _TOOLS}

def get_all_tools() -> list[ToolDefinition]:
    """Return all registered tools."""
    return _TOOLS

def get_tool(name: str) -> ToolDefinition | None:
    """Retrieve a tool definition by name."""
    return _TOOL_MAP.get(name)

def get_tool_schemas() -> list[dict]:
    """Return the raw JSON schemas for all tools."""
    return [t.to_json_schema() for t in _TOOLS]
