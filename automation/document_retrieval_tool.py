"""
Document Retrieval Tool
=======================

Agentic tool for searching and opening context documents.
Registers 'find_document_by_context' and 'open_document_result'.
"""

import logging
import os
import re
from typing import Any, Optional

from execution.registry import register_tool
from execution.schemas import ExecutionResult
from agentic.memory.session_state import get_session
from agentic.document_retrieval.manager import DocumentRetrievalManager
from agentic.file_context_search.preview import format_results_for_voice, format_results_for_display

logger = logging.getLogger(__name__)

WORD_TO_NUM = {
    "1": 1, "one": 1, "first": 1, "1st": 1,
    "2": 2, "two": 2, "second": 2, "2nd": 2,
    "3": 3, "three": 3, "third": 3, "3rd": 3,
    "4": 4, "four": 4, "fourth": 4, "4th": 4,
    "5": 5, "five": 5, "fifth": 5, "5th": 5,
}

def parse_result_number(val: Any) -> Optional[int]:
    """Parse raw argument into a 1-based result index (1..5)."""
    if val is None:
        return None
    val_str = str(val).strip().lower()
    if not val_str:
        return None
    if val_str in WORD_TO_NUM:
        return WORD_TO_NUM[val_str]
    match = re.search(r"\b(one|first|1st|two|second|2nd|three|third|3rd|four|fourth|4th|five|fifth|5th|[1-5])\b", val_str)
    if match:
        return WORD_TO_NUM.get(match.group(1))
    try:
        num = int(val_str)
        if 1 <= num <= 10:
            return num
    except (ValueError, TypeError):
        pass
    return None


@register_tool("find_document_by_context")
def find_document_by_context(args: dict[str, Any]) -> ExecutionResult:
    """Find a document using search or open a previously found result by number.
    
    If 'result_number' (or number/ordinal) is provided, it opens that result from previous search.
    Otherwise, it searches for 'query'.
    """
    logger.info("[TOOL DEBUG] ENTER find_document_by_context with args: %s", args)
    
    session = get_session()
    pending = getattr(session, "pending_document_results", []) or []

    raw_number = args.get("result_number") or args.get("number") or args.get("result")
    query_str = str(args.get("query", "")).strip()

    # If raw_number wasn't explicitly passed, check if query_str is a selection voice command
    if raw_number is None and query_str:
        num = parse_result_number(query_str)
        if num is not None and not any(kw in query_str.lower() for kw in ["healthsphere", "money", "mentor", "pdf", "docx", "pptx", "xlsx", "report"]):
            raw_number = num

    result_num = parse_result_number(raw_number) if raw_number is not None else None

    # ── MODE 1: Open a result by number ─────────────────────────────────────
    if result_num is not None:
        logger.info("[DOC OPEN] Result requested : %d", result_num)
        print(f"[DOC OPEN] Result requested : {result_num}")
        if not pending:
            logger.warning("[DOC OPEN] No pending search results found in session.")
            print("[DOC OPEN] No pending search results found in session.")
            return ExecutionResult(
                success=False,
                output="I don't have any recent search results to open. Please search for the document first.",
                message="No pending search results to open.",
                tool="find_document_by_context"
            )

        if not (1 <= result_num <= len(pending)):
            logger.warning("[DOC OPEN] Invalid result number %d (available: 1..%d)", result_num, len(pending))
            print(f"[DOC OPEN] Invalid result number {result_num} (available: 1..{len(pending)})")
            return ExecutionResult(
                success=False,
                output=f"Invalid selection. Please choose a number between 1 and {len(pending)}.",
                message=f"Invalid selection: {result_num}",
                tool="find_document_by_context"
            )

        chosen = pending[result_num - 1]
        file_path = chosen.get("path", "")
        filename = chosen.get("filename", os.path.basename(file_path) if file_path else "file")

        logger.info("[DOC OPEN] Resolved path : %s", file_path)
        print(f"[DOC OPEN] Resolved path : {file_path}")

        # ── PERMISSION CHECK: Require confirmation before opening ─────────
        confirmed = args.get("confirmed", False)
        if not confirmed:
            logger.info("[DOC OPEN] Permission not yet granted. Requesting confirmation.")
            print("[DOC OPEN] Permission not yet granted. Requesting confirmation.")
            return ExecutionResult(
                success=True,
                output=f"You are about to open: {filename}",
                message=f"Open document {result_num}: {filename}?",
                tool="find_document_by_context",
                requires_interaction=True,
                data={
                    "action": "open_permission_required",
                    "filename": filename,
                    "path": file_path,
                    "result_number": result_num
                }
            )

        exists = bool(file_path and os.path.exists(file_path))
        logger.info("[DOC OPEN] Exists : %s", exists)
        print(f"[DOC OPEN] Exists : {exists}")

        # ── PATH VALIDATION ────────────────────────────────────────────────
        if not exists:
            logger.warning("[DOC OPEN] File path does not exist on disk: %s. Purging stale index entry.", file_path)
            print(f"[DOC OPEN] File path does not exist on disk: {file_path}. Purging stale index entry.")
            try:
                from agentic.file_context_search import cache
                cache.delete_file(file_path)
            except Exception as e:
                logger.warning("[DOC OPEN] Failed to purge stale path: %s", e)

            # ── INDEX VALIDATION & RETRY ────────────────────────────────────
            fresh_results = []
            last_q = getattr(session, "last_document_query", "")
            if last_q:
                from agentic.file_context_search.manager import DocumentSearchManager
                fresh_results = DocumentSearchManager.find_documents(last_q, top_n=5)

            if fresh_results:
                session.pending_document_results = format_results_for_display(fresh_results)
                new_top_path = fresh_results[0].path
                if os.path.exists(new_top_path):
                    logger.info("[DOC OPEN] Re-indexed and attempting to launch fresh result: %s", new_top_path)
                    print(f"[DOC OPEN] Re-indexed and attempting to launch fresh result: {new_top_path}")
                    opened = DocumentRetrievalManager.open_result(new_top_path)
                    if opened:
                        return ExecutionResult(
                            success=True,
                            output=f"The requested path was stale. I re-indexed and opened {fresh_results[0].filename}.",
                            message=f"Opened {fresh_results[0].filename}.",
                            tool="find_document_by_context",
                            data={"opened": True, "path": new_top_path}
                        )

            return ExecutionResult(
                success=False,
                output=f"The file '{filename}' no longer exists on disk. I have updated the index.",
                message=f"This file no longer exists.",
                tool="find_document_by_context"
            )

        # ── WINDOWS NATIVE OPEN ─────────────────────────────────────────────
        logger.info("[DOC OPEN] Launching via os.startfile()")
        print("[DOC OPEN] Launching via os.startfile()")
        try:
            opened = DocumentRetrievalManager.open_result(file_path)
            if opened:
                logger.info("[DOC OPEN] Successfully opened file: %s", file_path)
                print(f"[DOC OPEN] Successfully opened file: {file_path}")
                return ExecutionResult(
                    success=True,
                    output=f"I have opened {filename}.",
                    message=f"Opening {filename}.",
                    tool="find_document_by_context",
                    data={"opened": True, "path": file_path}
                )
            else:
                logger.error("[DOC OPEN] Failed to launch file %s via os.startfile()", file_path)
                print(f"[DOC OPEN] Failed to launch file {file_path} via os.startfile()")
                return ExecutionResult(
                    success=False,
                    output=f"Failed to open {filename}.",
                    message=f"Failed to open {filename}.",
                    tool="find_document_by_context"
                )
        except Exception as exc:
            import traceback
            tb_str = traceback.format_exc()
            logger.exception("[DOC OPEN] Exception launching os.startfile() for path %s: %s\n%s", file_path, exc, tb_str)
            print(f"[DOC OPEN] Exception launching os.startfile() for path {file_path}: {exc}\n{tb_str}")
            return ExecutionResult(
                success=False,
                output=f"Exception opening {filename}: {exc}",
                message=f"Exception opening {filename}: {exc}",
                tool="find_document_by_context"
            )

    # ── MODE 2: Search for documents ──────────────────────────────────────
    if not query_str:
        return ExecutionResult(
            success=False,
            output="Please tell me what kind of document you are looking for.",
            message="No search query provided.",
            tool="find_document_by_context"
        )
        
    logger.info("[TOOL] Searching for documents matching: '%s'", query_str)
    session.last_document_query = query_str
    
    from agentic.file_context_search.manager import DocumentSearchManager
    results = DocumentSearchManager.find_documents(query_str, top_n=5)
    
    if not results:
        return ExecutionResult(
            success=True,
            output=f"I searched your files but couldn't find any documents matching '{query_str}'.",
            message=f"No documents found for '{query_str}'.",
            tool="find_document_by_context"
        )
        
    display_data = format_results_for_display(results)
    session.pending_document_results = display_data
    logger.info("[DOC SEARCH] Stored %d results in session", len(display_data))
    print(f"[DOC SEARCH] Stored {len(display_data)} results in session")

    # SCENARIO 1: If there is only ONE high-confidence result, let execution complete so frontend shows modal
    if len(results) == 1:
        single_path = results[0].path
        single_name = results[0].filename
        logger.info("[TOOL] [SCENARIO 1] Single result found. Returning results for frontend modal: %s", single_path)
        return ExecutionResult(
            success=True,
            output=f"I found 1 matching file: {single_name}.",
            message=f"Found 1 matching file: {single_name}.",
            tool="find_document_by_context",
            requires_interaction=False,  # Let execution complete; frontend will detect results and show modal
            data={
                "results": display_data,
                "query": query_str,
                "action": "document_search_results"
            }
        )

    # SCENARIO 2: Multiple results returned -> display popup and wait for user selection
    voice_text = format_results_for_voice(results)
    return ExecutionResult(
        success=True,
        output=voice_text,
        message=voice_text,
        tool="find_document_by_context",
        requires_interaction=False,  # Let execution complete; frontend will detect results and show modal
        data={
            "results": display_data,
            "query": query_str,
            "action": "document_search_results"
        }
    )


@register_tool("open_document_result")
def open_document_result(args: dict[str, Any]) -> ExecutionResult:
    """Open a file from the previously returned document search results."""
    return find_document_by_context(args)
