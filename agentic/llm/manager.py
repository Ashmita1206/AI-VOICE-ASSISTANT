"""
Planner Manager
===============

Orchestrates Qwen3-8B inference for the planning layer.
Handles prompt construction, JSON parsing, retry logic,
response caching, and graceful fallback.
"""

from __future__ import annotations
import json
import time
import logging
import threading
from typing import Any

from agentic.llm import remote_client
from agentic.llm.schemas import PlannerOutput

logger = logging.getLogger(__name__)

# ── Singleton ────────────────────────────────────────────────────────
_manager: "PlannerManager | None" = None
_manager_lock = threading.Lock()


def get_planner_manager() -> "PlannerManager":
    """Return the singleton PlannerManager."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = PlannerManager()
    return _manager


class PlannerManager:
    """Sends transcriptions to the remote Colab API, parses JSON, and handles conversational logic."""

    MAX_RETRIES = 3

    def __init__(self) -> None:
        self._cache: dict[str, PlannerOutput] = {}
        # Start background resource indexer
        from agentic.discovery.indexer import get_indexer
        get_indexer().start()

    def _inject_context(self, transcription: str) -> str:
        """Prepend session memory context to the transcription so the LLM understands 'here', 'it', etc."""
        from agentic.memory.session_state import get_session
        session = get_session()
        
        context_str = ""
        if session.last_directory:
            context_str += f"[Context: Current directory is {session.last_directory}] "
            
        active_app = session.last_active_app or session.last_application
        if active_app:
            context_str += f"[Context: Last active app is {active_app}] "
            
        if session.last_contact:
            context_str += f"[Context: Last contact is {session.last_contact}] "
        if session.last_song:
            context_str += f"[Context: Last song is {session.last_song}] "
        if session.last_search_query:
            context_str += f"[Context: Last search query is {session.last_search_query}] "
            
        return context_str + transcription

    def plan(self, transcription: str) -> PlannerOutput:
        """Process a transcription, checking conversational interceptors first, then remote planning."""
        
        # --- CONVERSATIONAL INTERCEPTORS ---
        from agentic.conversation.interrupt_handler import check_interrupt
        from agentic.conversation.workflow_manager import check_resume_workflow
        from agentic.conversation.status_manager import check_status_query
        from agentic.conversation.confirmation_manager import handle_pending_confirmation
        
        # 1. Interrupts
        interrupt_msg = check_interrupt(transcription)
        if interrupt_msg:
            return PlannerOutput(intent="interrupt", reasoning=interrupt_msg, steps=[])
            
        # 2. Workflow Resume
        is_resume, resume_msg = check_resume_workflow(transcription)
        if is_resume:
            return PlannerOutput(intent="resume", reasoning=resume_msg, steps=[])
            
        # 3. Pending Confirmations
        handled, confirm_msg = handle_pending_confirmation(transcription)
        if handled:
            return PlannerOutput(intent="confirmation", reasoning=confirm_msg, steps=[])
            
        # 4. Meta/Status Queries
        status_msg = check_status_query(transcription)
        if status_msg:
            return PlannerOutput(intent="status", reasoning=status_msg, steps=[])
            
        # --- REGULAR PLANNING ---
        cache_key = transcription.strip().lower()
        if cache_key in self._cache:
            print("Remote Planner: Using Cache")
            logger.debug("Cache hit for: %s", cache_key)
            return self._cache[cache_key]

        print("Remote Planner: Connected")
        backoff = 1.0  

        # Inject memory context before sending to LLM
        enriched_transcription = self._inject_context(transcription)

        # Compile system discovery context
        from agentic.discovery.manager import get_system_context
        system_context = get_system_context()

        for attempt in range(1 + self.MAX_RETRIES):
            try:
                raw_json = remote_client.plan_remote(enriched_transcription, system_context)
                logger.debug("Remote JSON (attempt %d): %s", attempt, raw_json)
                
                result = PlannerOutput.from_json(raw_json)
                
                # Add to history
                from agentic.memory.session_state import get_session
                get_session().add_history(transcription, result.intent, result.to_dict(), "Plan generated")

                self._cache[cache_key] = result
                return result

            except Exception as e:
                err_str = str(e).lower()
                if "timeout" in err_str:
                    print("Remote Planner: Timeout")
                
                logger.warning("Remote planning failed (attempt %d): %s", attempt, e)
                
                # Fast fail if endpoint returns 404 Not Found or Connection Refused (not timeout)
                if ("404" in err_str or "connection refused" in err_str or "refused" in err_str or "not found" in err_str) and "timeout" not in err_str:
                    logger.info("Remote LLM endpoint unavailable (%s) — fast failing to local heuristic planner.", e)
                    break

                if attempt < self.MAX_RETRIES:
                    time.sleep(backoff)
                    backoff *= 2  

        # All retries exhausted
        print("⚠️  [REMOTE LLM] UNAVAILABLE — all retries exhausted.")
        print("⚠️  [REMOTE LLM] Falling back to LOCAL heuristic planner.")
        print("⚠️  This means the Colab Qwen server is not reachable.")
        print(f"⚠️  Check COLAB_API_URL in your .env: {__import__('config').COLAB_API_URL}")
        logger.error("Planning failed after retries for: %s", transcription)
        
        from agentic.llm.fallback import apply_heuristic_fallback
        fallback_result = apply_heuristic_fallback(transcription)
        
        return fallback_result
