"""
Command Registry
================

Centralised, declarative repository of all supported commands.

No logic lives here.  This module simply defines the dataset of
available intents using the schemas defined in ``agent.schemas``.
Adding a new voice command is as simple as adding a new
``IntentDefinition`` to the ``_REGISTRY`` list.

Usage:
    from agent.command_registry import get_all_intents, get_intent

    all_defs = get_all_intents()
    search_def = get_intent("search_web")
"""

from __future__ import annotations

from agent.schemas import IntentDefinition, IntentPattern

# ══════════════════════════════════════════════════════════════════════
# THE REGISTRY
# ══════════════════════════════════════════════════════════════════════

_REGISTRY: list[IntentDefinition] = [

    # ──────────────────────────────────────────────────────────────────
    # APPLICATION COMMANDS
    # ──────────────────────────────────────────────────────────────────

    IntentDefinition(
        name="open_application",
        category="application",
        description="Open or launch a desktop application.",
        patterns=[
            # Standard English forms
            IntentPattern("open {application}"),
            IntentPattern("launch {application}"),
            IntentPattern("start {application}"),
            # Hinglish preprocessor output (e.g., "chrome kholo" -> "chrome open")
            IntentPattern("{application} open"),
        ],
        keywords=["open", "launch", "start", "application", "app"],
        entity_schema={"application": "str"},
    ),
    IntentDefinition(
        name="close_application",
        category="application",
        description="Close or terminate a running application.",
        patterns=[
            IntentPattern("close {application}"),
            IntentPattern("quit {application}"),
            IntentPattern("terminate {application}"),
            # Hinglish preprocessor output
            IntentPattern("{application} close"),
        ],
        keywords=["close", "quit", "terminate", "exit", "kill"],
        entity_schema={"application": "str"},
    ),
    IntentDefinition(
        name="open_terminal",
        category="application",
        description="Open the system terminal/command prompt.",
        patterns=[
            IntentPattern("open terminal"),
            IntentPattern("terminal open"),
            IntentPattern("launch terminal"),
        ],
        keywords=["terminal", "prompt", "console", "bash"],
        entity_schema={},
    ),
    IntentDefinition(
        name="open_file_manager",
        category="application",
        description="Open the OS file explorer.",
        patterns=[
            IntentPattern("open file manager"),
            IntentPattern("file manager open"),
            IntentPattern("open explorer"),
        ],
        keywords=["file", "manager", "explorer", "files"],
        entity_schema={},
    ),
    IntentDefinition(
        name="open_telegram",
        category="application",
        description="Open or launch Telegram messenger app or web interface.",
        patterns=[
            IntentPattern("open telegram"),
            IntentPattern("launch telegram"),
            IntentPattern("start telegram"),
            IntentPattern("check telegram"),
            IntentPattern("telegram open"),
        ],
        keywords=["telegram", "open", "launch", "check", "chat", "messenger"],
        entity_schema={},
    ),
    IntentDefinition(
        name="open_gmail",
        category="application",
        description="Open or check Gmail web service.",
        patterns=[
            IntentPattern("open gmail"),
            IntentPattern("check gmail"),
            IntentPattern("check my gmail"),
            IntentPattern("open my gmail"),
            IntentPattern("launch gmail"),
            IntentPattern("gmail open"),
            IntentPattern("open my mail"),
        ],
        keywords=["gmail", "mail", "email", "inbox", "check", "open"],
        entity_schema={},
    ),
    IntentDefinition(
        name="open_spotify",
        category="application",
        description="Open or launch Spotify music player.",
        patterns=[
            IntentPattern("open spotify"),
            IntentPattern("launch spotify"),
            IntentPattern("start spotify"),
            IntentPattern("check spotify"),
            IntentPattern("spotify open"),
            IntentPattern("play music on spotify"),
        ],
        keywords=["spotify", "music", "player", "open", "launch", "play"],
        entity_schema={},
    ),

    IntentDefinition(
        name="play_music",
        category="media",
        description="Play a song, artist, or playlist on Spotify or another music player.",
        patterns=[
            IntentPattern("play {query} on {application}"),
            IntentPattern("play {query} in {application}"),
            IntentPattern("play {query}"),
            IntentPattern("play song {query}"),
            IntentPattern("search {query} on {application}"),
            IntentPattern("search {query} in {application}"),
        ],
        keywords=["play", "music", "song", "spotify", "sing", "audio"],
        entity_schema={"query": "str", "application": "str"},
    ),
    IntentDefinition(
        name="send_message",
        category="communication",
        description="Send a chat message or text to a contact via WhatsApp or another messenger.",
        patterns=[
            IntentPattern("send message to {contact} saying {message}"),
            IntentPattern("send {message} to {contact}"),
            IntentPattern("message {contact} and write {message}"),
            IntentPattern("message {contact} saying {message}"),
            IntentPattern("message {contact} {message}"),
            IntentPattern("text {contact} {message}"),
        ],
        keywords=["message", "whatsapp", "send", "text", "write", "chat"],
        entity_schema={"contact": "str", "message": "str"},
    ),

    # ──────────────────────────────────────────────────────────────────
    # BROWSER & WEB COMMANDS
    # ──────────────────────────────────────────────────────────────────

    IntentDefinition(
        name="open_browser",
        category="browser",
        description="Launch the default web browser.",
        patterns=[
            IntentPattern("open browser"),
            IntentPattern("browser open"),
        ],
        keywords=["browser", "internet", "web"],
        entity_schema={},
    ),
    IntentDefinition(
        name="search_web",
        category="browser",
        description="Search for a query, optionally on a specific application/engine.",
        patterns=[
            IntentPattern("search {query} on {application}"),
            IntentPattern("search {query} in {application}"),
            IntentPattern("{application} on {query} search"), # Google pe ML search kro -> google on ML search
            IntentPattern("{application} in {query} search"),
            IntentPattern("search {query}"),
            IntentPattern("{query} search"),
            IntentPattern("google {query}"),
            IntentPattern("search for {query}"),
        ],
        keywords=["search", "google", "find", "query", "look"],
        entity_schema={"query": "str", "application": "str"},
    ),
    IntentDefinition(
        name="open_website",
        category="browser",
        description="Open a specific website by name.",
        patterns=[
            IntentPattern("open website {website}"),
            IntentPattern("open {website}"),
            IntentPattern("{website} open"),
            IntentPattern("go to {website}"),
        ],
        keywords=["website", "site", "com", "www"],
        entity_schema={"website": "str"},
    ),

    # ──────────────────────────────────────────────────────────────────
    # SYSTEM COMMANDS
    # ──────────────────────────────────────────────────────────────────

    IntentDefinition(
        name="system_info",
        category="system",
        description="Get general system health and info.",
        patterns=[
            IntentPattern("system info"),
            IntentPattern("system information"),
            IntentPattern("pc info"),
        ],
        keywords=["system", "info", "information", "health", "status"],
        entity_schema={},
    ),
    IntentDefinition(
        name="check_time",
        category="system",
        description="Get the current local time.",
        patterns=[
            IntentPattern("what time is it"),
            IntentPattern("tell me the time"),
            IntentPattern("check time"),
            IntentPattern("time is what"),
            IntentPattern("time tell"),
        ],
        keywords=["time", "clock", "hour"],
        entity_schema={},
    ),
    IntentDefinition(
        name="check_date",
        category="system",
        description="Get the current date.",
        patterns=[
            IntentPattern("what is the date"),
            IntentPattern("what date is today"),
            IntentPattern("check date"),
            IntentPattern("date tell"),
        ],
        keywords=["date", "today", "day", "month", "year"],
        entity_schema={},
    ),
    IntentDefinition(
        name="check_memory",
        category="system",
        description="Check RAM usage.",
        patterns=[
            IntentPattern("check memory"),
            IntentPattern("memory usage"),
            IntentPattern("how much ram"),
        ],
        keywords=["memory", "ram", "usage", "free"],
        entity_schema={},
    ),
    IntentDefinition(
        name="check_disk",
        category="system",
        description="Check storage usage.",
        patterns=[
            IntentPattern("check disk"),
            IntentPattern("disk space"),
            IntentPattern("storage space"),
        ],
        keywords=["disk", "storage", "space", "drive"],
        entity_schema={},
    ),
    IntentDefinition(
        name="ip_address",
        category="system",
        description="Get local/public IP address.",
        patterns=[
            IntentPattern("what is my ip"),
            IntentPattern("ip address"),
            IntentPattern("check ip"),
        ],
        keywords=["ip", "address", "network"],
        entity_schema={},
    ),
    IntentDefinition(
        name="uptime",
        category="system",
        description="Check how long the system has been running.",
        patterns=[
            IntentPattern("system uptime"),
            IntentPattern("how long has the pc been on"),
            IntentPattern("uptime"),
        ],
        keywords=["uptime", "running", "since"],
        entity_schema={},
    ),

    # ──────────────────────────────────────────────────────────────────
    # UTILITIES
    # ──────────────────────────────────────────────────────────────────

    IntentDefinition(
        name="list_files",
        category="utilities",
        description="List files in the current or specified directory.",
        patterns=[
            IntentPattern("list files"),
            IntentPattern("show files"),
            IntentPattern("what is in this folder"),
            IntentPattern("list files in {directory}"),
        ],
        keywords=["list", "files", "show", "directory", "folder", "ls", "dir"],
        entity_schema={"directory": "str"},
    ),
    IntentDefinition(
        name="take_screenshot",
        category="utilities",
        description="Capture the current screen.",
        patterns=[
            IntentPattern("take screenshot"),
            IntentPattern("take a screenshot"),
            IntentPattern("capture screen"),
        ],
        keywords=["screenshot", "capture", "screen", "snip"],
        entity_schema={},
    ),

    # ──────────────────────────────────────────────────────────────────
    # FALLBACK
    # ──────────────────────────────────────────────────────────────────

    IntentDefinition(
        name="unknown",
        category="fallback",
        description="Fallback intent when nothing else matches with sufficient confidence.",
        patterns=[],  # Explicitly empty; handled dynamically by the classifier
        keywords=[],
        entity_schema={},
    ),

    # ──────────────────────────────────────────────────────────────────
    # NOTEPAD COMMANDS
    # ──────────────────────────────────────────────────────────────────

    IntentDefinition(
        name="notepad_open_intent",
        category="notepad",
        description="Open Microsoft Notepad.",
        patterns=[
            IntentPattern("open notepad"),
            IntentPattern("launch notepad"),
            IntentPattern("start notepad"),
            IntentPattern("notepad open"),
            IntentPattern("notepad start"),
        ],
        keywords=["notepad", "open", "launch", "start", "text editor"],
        entity_schema={},
    ),

    IntentDefinition(
        name="notepad_close_intent",
        category="notepad",
        description="Close Microsoft Notepad.",
        patterns=[
            IntentPattern("close notepad"),
            IntentPattern("quit notepad"),
            IntentPattern("exit notepad"),
            IntentPattern("notepad close"),
            IntentPattern("notepad quit"),
        ],
        keywords=["notepad", "close", "quit", "exit"],
        entity_schema={},
    ),

    IntentDefinition(
        name="notepad_type_intent",
        category="notepad",
        description="Type or write text into Notepad.",
        patterns=[
            IntentPattern("write {text}"),
            IntentPattern("type {text}"),
            IntentPattern("write in notepad {text}"),
            IntentPattern("type in notepad {text}"),
            IntentPattern("notepad write {text}"),
            IntentPattern("notepad type {text}"),
            IntentPattern("write text {text}"),
        ],
        keywords=["write", "type", "text", "notepad", "input"],
        entity_schema={"text": "str"},
    ),

    IntentDefinition(
        name="notepad_press_enter_intent",
        category="notepad",
        description="Press Enter in Notepad to create a new line.",
        patterns=[
            IntentPattern("press enter"),
            IntentPattern("new line"),
            IntentPattern("next line"),
            IntentPattern("enter notepad"),
            IntentPattern("notepad enter"),
        ],
        keywords=["enter", "new line", "return", "line break"],
        entity_schema={},
    ),

    IntentDefinition(
        name="notepad_select_all_intent",
        category="notepad",
        description="Select all text in Notepad.",
        patterns=[
            IntentPattern("select all"),
            IntentPattern("select all text"),
            IntentPattern("notepad select all"),
        ],
        keywords=["select", "all", "notepad"],
        entity_schema={},
    ),

    IntentDefinition(
        name="notepad_copy_intent",
        category="notepad",
        description="Copy selected text in Notepad.",
        patterns=[
            IntentPattern("copy"),
            IntentPattern("copy text"),
            IntentPattern("notepad copy"),
            IntentPattern("copy in notepad"),
        ],
        keywords=["copy", "clipboard", "notepad"],
        entity_schema={},
    ),

    IntentDefinition(
        name="notepad_paste_intent",
        category="notepad",
        description="Paste clipboard contents into Notepad.",
        patterns=[
            IntentPattern("paste"),
            IntentPattern("paste text"),
            IntentPattern("notepad paste"),
            IntentPattern("paste in notepad"),
        ],
        keywords=["paste", "clipboard", "notepad"],
        entity_schema={},
    ),

    IntentDefinition(
        name="notepad_undo_intent",
        category="notepad",
        description="Undo the last action in Notepad.",
        patterns=[
            IntentPattern("undo"),
            IntentPattern("notepad undo"),
            IntentPattern("undo last action"),
            IntentPattern("undo in notepad"),
        ],
        keywords=["undo", "revert", "notepad"],
        entity_schema={},
    ),

    IntentDefinition(
        name="notepad_redo_intent",
        category="notepad",
        description="Redo the last undone action in Notepad.",
        patterns=[
            IntentPattern("redo"),
            IntentPattern("notepad redo"),
            IntentPattern("redo in notepad"),
        ],
        keywords=["redo", "repeat", "notepad"],
        entity_schema={},
    ),

    IntentDefinition(
        name="notepad_delete_intent",
        category="notepad",
        description="Delete selected or all text in Notepad.",
        patterns=[
            IntentPattern("delete text"),
            IntentPattern("delete all text"),
            IntentPattern("notepad delete"),
            IntentPattern("delete in notepad"),
        ],
        keywords=["delete", "remove", "text", "notepad"],
        entity_schema={},
    ),

    IntentDefinition(
        name="notepad_clear_intent",
        category="notepad",
        description="Clear the entire Notepad document.",
        patterns=[
            IntentPattern("clear notepad"),
            IntentPattern("clear document"),
            IntentPattern("clear all"),
            IntentPattern("notepad clear"),
            IntentPattern("empty notepad"),
        ],
        keywords=["clear", "empty", "document", "notepad"],
        entity_schema={},
    ),

    IntentDefinition(
        name="notepad_save_intent",
        category="notepad",
        description="Save the current Notepad file.",
        patterns=[
            IntentPattern("save file"),
            IntentPattern("save notepad"),
            IntentPattern("save the file"),
            IntentPattern("notepad save"),
            IntentPattern("save document"),
            IntentPattern("save file as {filename} on {directory}"),
            IntentPattern("save file as {filename} in {directory}"),
            IntentPattern("save file as {filename} to {directory}"),
            IntentPattern("save file as {filename}"),
        ],
        keywords=["save", "file", "notepad", "document"],
        entity_schema={"filename": "str", "directory": "str"},
    ),

    IntentDefinition(
        name="notepad_save_as_intent",
        category="notepad",
        description="Save the Notepad document with a specific filename.",
        patterns=[
            IntentPattern("save as {filename} in {directory}"),
            IntentPattern("save as {filename} on {directory}"),
            IntentPattern("save as {filename} to {directory}"),
            IntentPattern("save file as {filename} in {directory}"),
            IntentPattern("save file as {filename} on {directory}"),
            IntentPattern("save file as {filename} to {directory}"),
            IntentPattern("save notepad as {filename} in {directory}"),
            IntentPattern("save notepad as {filename} on {directory}"),
            IntentPattern("save notepad as {filename} to {directory}"),
            IntentPattern("save document as {filename} in {directory}"),
            IntentPattern("save document as {filename} on {directory}"),
            IntentPattern("save document as {filename} to {directory}"),
            IntentPattern("save as {filename}"),
            IntentPattern("save file as {filename}"),
            IntentPattern("save notepad as {filename}"),
            IntentPattern("notepad save as {filename}"),
            IntentPattern("save document as {filename}"),
        ],
        keywords=["save", "as", "filename", "directory", "notepad"],
        entity_schema={"filename": "str", "directory": "str"},
    ),

    IntentDefinition(
        name="notepad_open_file_intent",
        category="notepad",
        description="Open an existing file in Notepad.",
        patterns=[
            IntentPattern("open file {path}"),
            IntentPattern("open {path} in notepad"),
            IntentPattern("notepad open file {path}"),
            IntentPattern("load file {path}"),
        ],
        keywords=["open", "file", "load", "notepad", "path"],
        entity_schema={"path": "str"},
    ),

    IntentDefinition(
        name="notepad_new_file_intent",
        category="notepad",
        description="Create a new empty document in Notepad.",
        patterns=[
            IntentPattern("new file"),
            IntentPattern("new document"),
            IntentPattern("notepad new file"),
            IntentPattern("create new file"),
            IntentPattern("notepad new document"),
        ],
        keywords=["new", "file", "document", "create", "notepad"],
        entity_schema={},
    ),

    # ── Context-Based Document Search ─────────────────────────────────────

    IntentDefinition(
        name="find_document",
        category="document_search",
        description=(
            "Find or locate a file/document using context clues when the user "
            "does not know the exact filename."
        ),
        patterns=[
            IntentPattern("find {query}"),
            IntentPattern("find my {query}"),
            IntentPattern("find the {query}"),
            IntentPattern("find document {query}"),
            IntentPattern("find file {query}"),
            IntentPattern("find report {query}"),
            IntentPattern("find pdf {query}"),
            IntentPattern("search for {query}"),
            IntentPattern("search document {query}"),
            IntentPattern("search file {query}"),
            IntentPattern("open the {query} document"),
            IntentPattern("open my {query} document"),
            IntentPattern("open my {query} file"),
            IntentPattern("open {query} document"),
            IntentPattern("open {query} report"),
            IntentPattern("open {query} presentation"),
            IntentPattern("open {query} spreadsheet"),
            IntentPattern("locate {query}"),
            IntentPattern("locate file {query}"),
            IntentPattern("need the {query} file"),
            IntentPattern("need my {query}"),
            IntentPattern("i need {query} document"),
            IntentPattern("show me {query} document"),
            IntentPattern("where is {query}"),
            IntentPattern("where is my {query}"),
        ],
        keywords=[
            "find", "search", "locate", "document", "file", "report",
            "pdf", "proposal", "presentation", "ppt", "spreadsheet",
            "excel", "docx", "word", "notebook", "notes", "invoice",
            "project", "old", "remember", "forgot", "looking", "need",
        ],
        entity_schema={"query": "str"},
    ),

    IntentDefinition(
        name="open_selected_document",
        category="document_search",
        description="Open a numbered result from a previous document search.",
        patterns=[
            IntentPattern("open number {result_number}"),
            IntentPattern("open {result_number}"),
            IntentPattern("select {result_number}"),
            IntentPattern("choose {result_number}"),
            IntentPattern("number {result_number}"),
            IntentPattern("pick {result_number}"),
            IntentPattern("open the first one"),
            IntentPattern("open the second one"),
            IntentPattern("open the third one"),
            IntentPattern("open the fourth one"),
            IntentPattern("open the fifth one"),
            IntentPattern("first one"),
            IntentPattern("second one"),
            IntentPattern("third one"),
            IntentPattern("fourth one"),
            IntentPattern("fifth one"),
        ],
        keywords=[
            "open", "select", "choose", "number", "first", "second",
            "third", "fourth", "fifth", "one", "two", "three", "four", "five",
            "pick", "result",
        ],
        entity_schema={"result_number": "str"},
    ),
]


# ══════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════

# Cache for fast lookup by name
_INTENT_MAP = {defn.name: defn for defn in _REGISTRY}


def get_all_intents() -> list[IntentDefinition]:
    """Return a list of all defined intents in the registry."""
    return _REGISTRY


def get_intent(name: str) -> IntentDefinition | None:
    """Look up a specific intent by its canonical name.

    Returns ``None`` if the intent is not found.
    """
    return _INTENT_MAP.get(name)


def list_intent_names() -> list[str]:
    """Return a list of all intent names (e.g. for logging or CLI)."""
    return list(_INTENT_MAP.keys())
