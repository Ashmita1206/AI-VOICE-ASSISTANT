"""
Pending Action Manager
======================

Stores and manages dynamic execution plans awaiting user confirmation.
"""

import os
import json
import uuid
import time
import logging
import threading
from typing import Dict, Any, Optional
from agentic.discovery.indexer import CACHE_DIR

logger = logging.getLogger(__name__)

PENDING_ACTION_PATH = os.path.join(CACHE_DIR, "pending_action.json")
_PENDING_ACTION_LOCK = threading.RLock()

class PendingActionManager:
    """Manages the disk-persisted state of blocked, awaiting-confirmation execution plans."""

    @staticmethod
    def get_pending_action() -> Optional[Dict[str, Any]]:
        """Load pending action from disk if it exists and hasn't expired (60s)."""
        if os.path.exists(PENDING_ACTION_PATH):
            try:
                with open(PENDING_ACTION_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    
                # Check timeout (60 seconds)
                created_at = data.get("created_at", 0.0)
                if time.time() - created_at > 60.0:
                    PendingActionManager.clear()
                    return None
                return data
            except Exception as e:
                logger.error(f"Failed to load pending action: {e}")
        return None

    @staticmethod
    def save(plan_dict: Dict[str, Any]) -> str:
        """Save a pending plan to disk. Returns the confirmation ID."""
        action_id = uuid.uuid4().hex[:16]
        data = {
            "id": action_id,
            "status": "awaiting_confirmation",
            "created_at": time.time(),
            "plan": plan_dict
        }
        os.makedirs(CACHE_DIR, exist_ok=True)
        try:
            with _PENDING_ACTION_LOCK:
                with open(PENDING_ACTION_PATH, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved pending action {action_id} to disk.")
        except Exception as e:
            logger.error(f"Failed to save pending action: {e}")
        return action_id

    @staticmethod
    def claim(action_id: str) -> Optional[Dict[str, Any]]:
        """Atomically consume and return the matching pending action.

        Streaming clients may reconnect or double-submit a confirmation.  Only
        the first caller is allowed to claim the plan; later callers receive
        ``None`` and cannot replay external side effects.
        """
        with _PENDING_ACTION_LOCK:
            data = PendingActionManager.get_pending_action()
            if not data or data.get("id") != action_id:
                return None
            PendingActionManager.clear()
            return data

    @staticmethod
    def clear():
        """Clear the pending action file."""
        with _PENDING_ACTION_LOCK:
            if os.path.exists(PENDING_ACTION_PATH):
                try:
                    os.remove(PENDING_ACTION_PATH)
                    logger.info("Cleared pending action from disk.")
                except OSError as e:
                    logger.error(f"Failed to remove pending action file: {e}")
