"""
Telegram Hybrid Automation
==========================

Safe, multi-turn Telegram messaging workflow:
Voice Command → NLU → Contact Search → Disambiguation → Visual Preview → Confirmation → Send

Public API
----------
- ``TelegramAutomationRouter``  — multi-turn state-machine orchestrator
- ``TelegramFlowState``         — explicit flow state
- ``TelegramService``           — Pyrogram-backed contact search & preview adapter
- ``parse_telegram_input``      — NLU parser entry point
- ``get_telegram_router``       — singleton router provider

Decomposed tool handlers are registered in ``telegram_automation.py``:
  open_telegram, search_telegram_contact, verify_telegram_contact,
  open_telegram_chat, type_telegram_message, send_telegram_message,
  verify_telegram_message_sent, close_telegram
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import time
from typing import Any, Dict, Optional

from automation.telegram.models import (
    ConfirmationResult,
    DisambiguationResult,
    FlowStatus,
    NewCommandResult,
    NLUState,
    TelegramContact,
    TelegramFlowMode,
    TelegramFlowResult,
    TelegramFlowState,
)
from automation.telegram.nlu import parse_telegram_input
from automation.telegram.router import TelegramAutomationRouter
from automation.telegram.telegram_automation import TelegramService

# ---------------------------------------------------------------------------
# Singleton instances for persistent state across turns
# ---------------------------------------------------------------------------

_service_instance: Optional[TelegramService] = None
_router_instance: Optional[TelegramAutomationRouter] = None


def get_telegram_service() -> TelegramService:
    """Return singleton TelegramService instance."""
    global _service_instance
    if _service_instance is None:
        _service_instance = TelegramService()
    return _service_instance


def get_telegram_router() -> TelegramAutomationRouter:
    """Return singleton TelegramAutomationRouter instance."""
    global _router_instance
    if _router_instance is None:
        _router_instance = TelegramAutomationRouter(get_telegram_service())
    return _router_instance


# ---------------------------------------------------------------------------
# Async runner helper (prevents nested event loop errors)
# ---------------------------------------------------------------------------

def _run_async(coro: Any) -> Any:
    """Run an async coroutine from a sync tool execution context cleanly."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(lambda: asyncio.run(coro)).result()
    else:
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Decomposed tool handlers are registered in telegram_automation.py
# They are auto-loaded via execution.registry.load_all_tools()
# The old monolithic handler has been replaced by the decomposed sequence.
# ---------------------------------------------------------------------------


__all__ = [
    "TelegramAutomationRouter",
    "TelegramFlowState",
    "TelegramFlowMode",
    "NLUState",
    "FlowStatus",
    "TelegramContact",
    "TelegramFlowResult",
    "NewCommandResult",
    "DisambiguationResult",
    "ConfirmationResult",
    "TelegramService",
    "parse_telegram_input",
    "get_telegram_service",
    "get_telegram_router",
    "_run_async",
]
