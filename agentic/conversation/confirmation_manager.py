"""
Confirmation Manager
====================

Parses positive/negative intent without hitting the LLM.
Manages the 60s confirmation timeout and applies pending actions if confirmed.
"""

import re
from typing import Tuple, Optional
from agentic.memory.session_state import get_session
from agentic.schemas import ActionStep
from execution.executor import DesktopExecutor

# Fast regex patterns for Yes/No detection
POSITIVE_REGEX = re.compile(r"^(yes|yeah|sure|yep|okay|do it|proceed|continue|send it|go ahead)$", re.IGNORECASE)
NEGATIVE_REGEX = re.compile(r"^(no|cancel|stop|don't|never mind|abort|nope|exit)$", re.IGNORECASE)

def is_positive(text: str) -> bool:
    """Check if the text is a fast positive confirmation."""
    text = re.sub(r"[^\w\s]", "", text).strip()
    return bool(POSITIVE_REGEX.match(text))

def is_negative(text: str) -> bool:
    """Check if the text is a fast negative rejection."""
    text = re.sub(r"[^\w\s]", "", text).strip()
    return bool(NEGATIVE_REGEX.match(text))

def handle_pending_confirmation(transcript: str) -> Tuple[bool, Optional[str]]:
    """
    Check if there is a pending action and if the transcript answers it.
    Returns (handled: bool, response_message: str | None).
    """
    session = get_session()

    # 0. Check Telegram router pending state
    try:
        from automation.telegram import get_telegram_router, TelegramFlowMode, FlowStatus, _run_async
        tg_router = get_telegram_router()
        if tg_router.state.mode in (TelegramFlowMode.DISAMBIGUATION, TelegramFlowMode.CONFIRMATION):
            if session.is_confirmation_timeout():
                tg_router.reset()
                session.clear_pending_action()
                return True, "Telegram confirmation timed out. The action has been cancelled."

            res = _run_async(tg_router.handle_input(transcript))

            if res.status in (FlowStatus.SEND_KEY_DISPATCHED, FlowStatus.CANCELLED, FlowStatus.ALREADY_EXECUTED, FlowStatus.ERROR):
                session.clear_pending_action()

            return True, res.message
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Telegram pending interceptor exception: %s", e, exc_info=True)
        pass

    if not session.pending_action:
        return False, None
        
    # Check timeout first
    if session.is_confirmation_timeout():
        session.clear_pending_action()
        return True, "Confirmation timed out. The action has been cancelled."
        
    if is_positive(transcript):
        # Execute the pending action
        action_data = session.pending_action
        session.clear_pending_action()
        
        # We need to run it through the executor safely, bypassing the confirmation block for THIS exact tool
        # To do this cleanly, we can temporarily wrap it in an ActionStep and run the handler directly.
        from execution.registry import get_handler
        handler = get_handler(action_data["tool"])
        
        if handler:
            result = handler(action_data["args"])
            return True, result.message
        else:
            return True, f"Failed to execute. Tool {action_data['tool']} is missing."

    if is_negative(transcript):
        # Reject and clear
        session.interrupted_task = session.pending_action
        session.clear_pending_action()
        return True, "Okay, I have cancelled the action."
        
    # If it's neither yes nor no, we treat it as an interruption or a new command.
    # In Jarvis mode, if they ask something else while pending, we usually discard the pending action.
    session.interrupted_task = session.pending_action
    session.clear_pending_action()
    return False, None
