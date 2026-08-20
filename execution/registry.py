"""
Tool Execution Registry
=======================

Maps canonical tool names (e.g. "open_browser") to their
corresponding handler functions in the execution layer.
"""

from typing import Callable, Any
import logging
from execution.schemas import ExecutionResult

logger = logging.getLogger(__name__)

# A tool handler is a function that takes a dict of args and returns an ExecutionResult.
ToolHandler = Callable[[dict[str, Any]], ExecutionResult]

_REGISTRY: dict[str, ToolHandler] = {}

def register_tool(name: str) -> Callable[[ToolHandler], ToolHandler]:
    """Decorator to register a tool handler function."""
    def decorator(func: ToolHandler) -> ToolHandler:
        _REGISTRY[name] = func
        return func
    return decorator

def get_handler(name: str) -> ToolHandler | None:
    """Retrieve the execution handler for a tool by name."""
    return _REGISTRY.get(name)

# Ensure all tool modules are imported so their decorators fire
def load_all_tools() -> None:
    try:
        import automation.browser
        import automation.applications
        import automation.desktop
        import automation.filesystem
        import automation.whatsapp
        import automation.telegram
        import automation.notepad
        import automation.file_context_search_tool  # Context-based File Explorer Search
        import automation.document_retrieval_tool # v2 document retrieval
    except ImportError as e:
        logger.warning(f"Could not load automation tools: {e}")
        
    logger.debug(f"Loaded {len(_REGISTRY)} tool handlers.")
