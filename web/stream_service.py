"""
SSE Streaming Pipeline Service
================================

Mirrors run_pipeline() from services.py but yields Server-Sent Events (SSE)
at each stage boundary so the UI can progressively reveal results.

Wire format (each event is a separate flush):
    data: {"stage":"transcript","status":"completed","data":{...}}\n\n

Stages emitted (in order):
    transcript      → STT done
    intent          → IntentClassifier done
    entities        → Entity data ready (from classifier result)
    discovery       → System context compiled for planner
    planner         → PlannerManager.plan() done
    execution       → status:"running" per sub-step; status:"completed" when all done
    response        → Response text + audio URL ready
    done            → Final assembled payload (or no_speech / requires_confirmation)
"""

from __future__ import annotations

import json
import os
import time
import logging
import queue
import threading
from datetime import datetime
from typing import Any, Generator

import config
from web.services import get_stt, get_classifier, get_executor, _generate_tts_file
from tts.response_generator import generate_response
from storage.history_manager import save_session
from execution.registry import get_handler, load_all_tools
from agentic.llm.schemas import PlannerOutput

# Load registered tools
load_all_tools()

def validate_execution_plan(planner_output: PlannerOutput) -> str | None:
    """Validate the PlannerOutput execution plan.
    
    Returns a string reason if validation fails, or None if validation succeeds.
    """
    if not planner_output:
        return "Planner JSON is missing or null."
        
    if not hasattr(planner_output, "steps") or planner_output.steps is None:
        return "Steps array does not exist in the plan."
        
    if len(planner_output.steps) == 0:
        if planner_output.intent in ("chat", "conversational") and getattr(planner_output, "reasoning", None):
            return None
        return "Planner produced no executable steps."
        
    seen_steps = set()
    for idx, s in enumerate(planner_output.steps, 1):
        if not s.tool:
            return f"Step {idx} is missing a tool name."
        if s.args is None:
            return f"Step {idx} ({s.tool}) is missing arguments."
        if not getattr(s, "description", None) and not s.description:
            # We assign step description fallback here
            s.description = f"Execute {s.tool.replace('_', ' ')}"
            
        # Verify tool is registered
        handler = get_handler(s.tool)
        if handler is None:
            return f"Tool '{s.tool}' in step {idx} is not registered."
            
        step_fingerprint = (s.tool, json.dumps(s.args, sort_keys=True))
        if step_fingerprint in seen_steps:
            return f"Duplicate step detected: {s.tool} with args {s.args}."
        seen_steps.add(step_fingerprint)
        
    return None

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# SSE helpers
# ══════════════════════════════════════════════════════════════════════

def _sse(stage: str, status: str, data: Any = None, message: str | None = None) -> str:
    """Encode one SSE event as a string to be flushed."""
    payload: dict[str, Any] = {"stage": stage, "status": status}
    if data is not None:
        payload["data"] = data
    if message is not None:
        payload["message"] = message
    serialized = json.dumps(payload, ensure_ascii=False)
    try:
        safe_msg = message.encode("ascii", "replace").decode("ascii") if message else ""
        logger.debug("[SSE] stage=%s status=%s msg=%s", stage, status, safe_msg)
    except Exception:
        pass
    return f"data: {serialized}\n\n"


# ══════════════════════════════════════════════════════════════════════
# Main streaming generator
# ══════════════════════════════════════════════════════════════════════

def run_pipeline_stream(audio_path: str | None = None, text: str | None = None) -> Generator[str, None, None]:
    """
    Generator that runs the full pipeline and yields SSE events.

    Usage in Flask route:
        return Response(
            stream_with_context(run_pipeline_stream(audio_path=temp_path)),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    """
    pipeline_start = time.perf_counter()

    # ── Step 1: STT ──────────────────────────────────────
    if text is not None:
        transcription = text
        translated_text = text
        intent_input = text
        stt_metrics = {
            "model": "text-input",
            "device": "cpu",
            "compute_type": "none",
            "language": "en",
            "confidence": 100,
            "processing_time_ms": 0,
        }
        yield _sse("transcript", "completed", data={
            "text": transcription,
            "translated_text": translated_text,
            "stt": stt_metrics,
        })
    else:
        yield _sse("transcript", "processing", message="Transcribing audio...")

        stt = get_stt()
        mode_label = "REMOTE" if config.STT_USE_REMOTE else "LOCAL"
        logger.info("[PIPELINE][STT] Stage START  mode=%s  file=%s", mode_label, audio_path)
        t_stt = time.perf_counter()
        stt_result = stt.transcribe(audio_path)
        stt_ms = int((time.perf_counter() - t_stt) * 1000)
        transcription = stt_result.get("text", "")
        translated_text = stt_result.get("translated_text") or transcription
        intent_input = translated_text or transcription
        logger.info("[PIPELINE][STT] Stage DONE  latency_ms=%d  text=%r  translated=%r", stt_ms, transcription[:120], translated_text[:120])

        stt_metrics = {
            "model": config.STT_MODEL_ID,
            "device": config.DEVICE,
            "compute_type": config.COMPUTE_TYPE,
            "language": stt_result.get("language", ""),
            "confidence": round(stt_result.get("language_probability", 0) * 100, 1),
            "processing_time_ms": int(stt_result.get("processing_time", 0) * 1000),
        }
        yield _sse("transcript", "completed", data={
            "text": transcription,
            "translated_text": translated_text,
            "stt": stt_metrics,
        })

    # Update app context silently
    if transcription.strip():
        try:
            from agentic.memory.app_context import AppContextManager, get_active_window_info
            from agentic.memory.session_state import get_session
            info = get_active_window_info()
            if info["active_app"]:
                AppContextManager.set_context(
                    active_app=info["active_app"],
                    window_handle=info["window_handle"],
                    last_command=transcription,
                )
                get_session().set_context(app=info["active_app"])
        except Exception:
            pass

    # ── Silent-audio fast-path ────────────────────────────────────────
    if not transcription.strip():
        no_speech_response = "I didn't catch that. Could you try again?"
        yield _sse("response", "completed", data={"text": no_speech_response})
        yield _sse("done", "no_speech", data={
            "transcription": "",
            "translated_text": "",
            "stt": stt_metrics,
            "intent": {"name": "unknown", "confidence": 0},
            "entities": {},
            "planner": {"thought": "", "steps": []},
            "execution": [],
            "speech": {"text": no_speech_response},
            "pipeline_time_ms": int((time.perf_counter() - pipeline_start) * 1000),
        })
        return

    # ── Step 2: Intent Classification ──────────────────────────
    yield _sse("intent", "processing", message="Classifying intent...")

    classifier = get_classifier()
    logger.info("[PIPELINE][INTENT] Stage START  input=%r", intent_input[:80])
    t_intent = time.perf_counter()
    command = classifier.classify(intent_input)
    intent_ms = int((time.perf_counter() - t_intent) * 1000)
    logger.info("[PIPELINE][INTENT] Stage DONE  intent=%s  confidence=%.1f%%  entities=%s  latency_ms=%d",
                command.intent, command.confidence * 100, command.entities, intent_ms)
    intent_data = {
        "name": command.intent,
        "confidence": round(command.confidence * 100, 1),
    }
    yield _sse("intent", "completed", data=intent_data)

    # ── Step 3: Entities (derived from classifier result) ────────────
    yield _sse("entities", "completed", data={"entities": command.entities})

    # ── Step 4: Discovery / System context (feeds the planner) ───────
    yield _sse("discovery", "processing", message="Indexing system resources…")

    from agentic.discovery.manager import get_system_context
    system_context = get_system_context()
    yield _sse("discovery", "completed", message="System context ready")

    # ── Step 5: Planning ─────────────────────────────────────
    yield _sse("planner", "processing", message="Building execution plan...")
    logger.info("[PIPELINE][PLANNER] Stage START  input=%r", intent_input[:80])
    t_plan = time.perf_counter()

    from agentic.llm.manager import get_planner_manager
    from agentic.llm.schemas import PlannerOutput
    from agentic.schemas import ExecutionPlan, ActionStep

    planner = get_planner_manager()
    planner_output: PlannerOutput = planner.plan(intent_input)
    plan_ms = int((time.perf_counter() - t_plan) * 1000)
    logger.info("[PIPELINE][PLANNER] Stage DONE  latency_ms=%d  steps=%d  intent=%s",
                plan_ms, len(planner_output.steps), planner_output.intent)
    for _si, _s in enumerate(planner_output.steps, 1):
        logger.info("[PIPELINE][PLANNER]   Step %d: tool=%s  args=%s", _si, _s.tool, _s.args)
    logger.debug("[PIPELINE][PLANNER] Full output: %s", json.dumps(planner_output.to_dict(), indent=2))

    # ── Step 5.5: Plan Validation ───────────────────────────────────
    validation_error = validate_execution_plan(planner_output)
    plan_dict_to_dict = planner_output.to_dict()
    steps_count = len(planner_output.steps)
    permissions = plan_dict_to_dict.get("permissions", [])
    proceed_enabled = (validation_error is None)

    logger.info("[BACKEND PLAN VALIDATION] Validated: %s | Steps: %d | Proceed: %s", proceed_enabled, steps_count, proceed_enabled)
    if validation_error:
        logger.warning("[BACKEND PLAN VALIDATION] Reason: %s", validation_error)

    if validation_error:
        yield _sse("planner", "failed", data={
            "success": False,
            "error": validation_error
        }, message=f"Failed to generate execution plan: {validation_error}")
        yield _sse("done", "error", data={
            "status": "error",
            "success": False,
            "error": validation_error,
            "message": f"Failed to generate execution plan. Reason: {validation_error}"
        }, message=f"Failed to generate execution plan: {validation_error}")
        return

    plan_steps = [
        ActionStep(tool=s.tool, args=s.args)
        for s in planner_output.steps
    ]
    plan = ExecutionPlan(thought=planner_output.reasoning, steps=plan_steps, response="")

    yield _sse("planner", "completed", data=planner_output.to_dict())

    # ── Step 5.9: Confirmation bypass for document search/open intents ────────
    # Document search and open are safe, user-initiated actions that should
    # execute immediately without requiring a "Proceed" confirmation click.
    _DOCUMENT_BYPASS_INTENTS = {
        "find_document_by_context",
        "open_selected_document",
    }
    _DOCUMENT_BYPASS_TOOLS = {
        "find_document_by_context",
        "open_document_result",
    }
    _is_document_action = (
        planner_output.intent in _DOCUMENT_BYPASS_INTENTS
        or (len(planner_output.steps) > 0 and all(s.tool in _DOCUMENT_BYPASS_TOOLS for s in planner_output.steps))
    )


    if _is_document_action and len(planner_output.steps) > 0:
        logger.info("[PIPELINE] Document intent detected — bypassing confirmation gate")

        from execution.executor import DesktopExecutor
        yield _sse("execution", "running", message="Searching and opening document…")

        try:
            _doc_executor = DesktopExecutor()
            _doc_executor.bypass_confirmation = True

            _doc_q: queue.Queue[str | None] = queue.Queue()
            _doc_results_holder: list[list[dict]] = []
            _doc_error_holder: list[Exception] = []

            def _doc_run():
                try:
                    _doc_results_holder.append(
                        _doc_executor.execute(plan, progress_callback=_doc_q.put)
                    )
                except Exception as _e:
                    _doc_error_holder.append(_e)
                finally:
                    _doc_q.put(None)

            _doc_thread = threading.Thread(target=_doc_run, daemon=True)
            _doc_thread.start()

            while True:
                try:
                    _msg = _doc_q.get(timeout=120)
                except queue.Empty:
                    break
                if _msg is None:
                    break
                yield _sse("execution", "running", message=_msg)

            _doc_thread.join(timeout=5)

            if _doc_error_holder:
                yield _sse("execution", "failed", message=str(_doc_error_holder[0]))
                yield _sse("done", "error", data={"error": str(_doc_error_holder[0])})
                return

            _doc_exec_results = _doc_results_holder[0] if _doc_results_holder else []
            yield _sse("execution", "completed", data={"steps": _doc_exec_results})

            # Check if any executed step requested step-level confirmation (e.g. verify_telegram_contact or type_telegram_message)
            req_step_res = next((r for r in _doc_exec_results if r.get("requires_confirmation")), None)
            if req_step_res:
                logger.info("[PIPELINE] Execution paused for step-level confirmation: tool=%s", req_step_res.get("tool"))
                executed_tools = [r.get("tool") for r in _doc_exec_results]
                remaining_steps = []
                found_pause = False
                for s in planner_output.steps:
                    if found_pause:
                        remaining_steps.append({"tool": s.tool, "args": s.args})
                    elif s.tool == req_step_res.get("tool"):
                        found_pause = True

                remaining_plan = {
                    "intent": planner_output.intent,
                    "thought": planner_output.reasoning,
                    "steps": remaining_steps,
                }

                from agentic.memory.pending_action import PendingActionManager
                confirmation_id = PendingActionManager.save(remaining_plan)

                req_data = req_step_res.get("data", {})
                confirm_type = req_data.get("confirmation_type", "telegram_confirmation")
                contact_val = req_data.get("contact", command.entities.get("contact", ""))
                msg_val = req_data.get("message", command.entities.get("message", ""))
                prompt_msg = req_data.get("message_prompt") or req_step_res.get("message") or f"Confirm action for {contact_val}"

                yield _sse("done", "requires_confirmation", data={
                    "status": "requires_confirmation",
                    "transcription": transcription,
                    "confirmation": {
                        "id": confirmation_id,
                        "confirmation_type": confirm_type,
                        "contact": contact_val,
                        "message": prompt_msg,
                        "message_text": msg_val,
                        "plan": planner_output.to_dict(),
                        "remaining_seconds": 60,
                    },
                    "intent": {"name": planner_output.intent, "confidence": round(planner_output.confidence * 100, 1)},
                    "entities": command.entities,
                    "planner": planner_output.to_dict(),
                    "pipeline_time_ms": int((time.perf_counter() - pipeline_start) * 1000),
                })
                return

            # Response generation
            yield _sse("response", "processing", message="Generating assistant response…")
            _doc_response_text = generate_response(_doc_exec_results)
            _doc_audio_path = _generate_tts_file(_doc_response_text)
            _doc_speech: dict[str, Any] = {"text": _doc_response_text}
            if _doc_audio_path:
                _doc_speech["audio_url"] = f"/static/audio/{os.path.basename(_doc_audio_path)}"
            yield _sse("response", "completed", data=_doc_speech)

            from agentic.memory.session_state import get_session as _doc_get_session
            _doc_get_session().add_history(
                transcript=transcription,
                intent=planner_output.intent,
                plan=planner_output.to_dict(),
                result=_doc_response_text,
            )
            _doc_result = {
                "transcription": transcription,
                "stt": stt_metrics,
                "intent": {"name": planner_output.intent, "confidence": round(planner_output.confidence * 100, 1)},
                "entities": command.entities,
                "planner": planner_output.to_dict(),
                "execution": _doc_exec_results,
                "speech": _doc_speech,
                "pipeline_time_ms": int((time.perf_counter() - pipeline_start) * 1000),
                "timestamp": datetime.now().isoformat(),
            }
            save_session(_doc_result)
            yield _sse("done", "success", data=_doc_result)
        except Exception as _doc_exc:
            logger.exception("Document bypass execution failed")
            yield _sse("done", "error", data={"error": str(_doc_exc)})
        return

    # ── Step 6: Full Plan Confirmation ───────────────────────────────────────
    if len(planner_output.steps) == 0:
        # Proceed directly to response generation for conversational intents
        yield _sse("response", "processing", message="Generating assistant response…")
        response_text = planner_output.reasoning or "No actions planned."
        speech_audio_path = _generate_tts_file(response_text)
        speech_data = {"text": response_text}
        if speech_audio_path:
            speech_data["audio_url"] = f"/static/audio/{os.path.basename(speech_audio_path)}"
        yield _sse("response", "completed", data=speech_data)
        if speech_audio_path:
            logger.info("Audio URL Sent")
        
        result = {
            "transcription": transcription,
            "stt": stt_metrics,
            "intent": {"name": planner_output.intent, "confidence": round(planner_output.confidence * 100, 1)},
            "entities": command.entities,
            "planner": planner_output.to_dict(),
            "execution": [],
            "speech": speech_data,
            "pipeline_time_ms": int((time.perf_counter() - pipeline_start) * 1000),
            "timestamp": datetime.now().isoformat(),
        }
        save_session(result)
        yield _sse("done", "success", data=result)
        return

    plan_dict = {
        "intent": planner_output.intent,
        "thought": planner_output.reasoning,
        "confirmation_type": "execution_plan",
        "phase": "execution_plan",
        "steps": [
            {"tool": s.tool, "args": s.args} for s in planner_output.steps
        ],
    }
    
    from agentic.memory.pending_action import PendingActionManager
    confirmation_id = PendingActionManager.save(plan_dict)
    
    # Infer permissions and estimated actions
    permissions = []
    estimated_actions = []
    
    for s in planner_output.steps:
        tool = s.tool
        args = s.args or {}
        
        # Map tools to permissions
        if tool in ("open_gmail", "open_spotify"):
            permissions.append("Network Access")
            permissions.append("System Control")
        elif tool in ("press_key", "type_text", "hotkey"):
            permissions.append("Keyboard Control")
        elif tool in ("click", "double_click", "right_click", "scroll", "drag"):
            permissions.append("Mouse Control")
        elif tool in ("launch_application", "open_application", "focus_window", "close_window", "is_app_running", "activate_window"):
            permissions.append("Foreground Window Control")
        elif tool in ("open_browser", "open_website", "open_whatsapp", "open_telegram_web"):
            permissions.append("Browser Automation")
        elif tool in ("search_inside_application", "perform_app_action"):
            permissions.append("Accessibility/UI Automation")
        elif tool in ("ocr", "locate_ui_element", "find_text", "take_screenshot"):
            permissions.append("Screen Capture")
        elif tool in ("create_file", "create_folder", "delete_file", "delete_folder", "read_directory", "list_files"):
            permissions.append("File System Access")
            
        # Human-friendly action descriptions
        if tool == "open_telegram_web":
            estimated_actions.append("Open Telegram Web")
        elif tool == "open_gmail":
            estimated_actions.append("Open Gmail Service")
        elif tool == "open_spotify":
            estimated_actions.append("Open Spotify Music Player")
        elif tool in ("launch_application", "open_application"):
            estimated_actions.append(f"Open {args.get('application', 'application')}")
            estimated_actions.append(f"Open {args.get('application', 'application')}")
        elif tool == "search_inside_application":
            estimated_actions.append(f"Search for '{args.get('query', '')}'")
        elif tool == "press_key":
            estimated_actions.append(f"Press {args.get('key', '').capitalize()}")
        elif tool == "type_text":
            estimated_actions.append(f"Type '{args.get('text', '')}'")
        elif tool == "open_browser":
            estimated_actions.append("Open web browser")
        elif tool == "open_website":
            estimated_actions.append(f"Navigate to {args.get('url', 'website')}")
        elif tool == "send_whatsapp_message":
            estimated_actions.append(f"Send message to {args.get('contact', 'contact')}")
        else:
            estimated_actions.append(f"Execute {tool.replace('_', ' ')}")
            
    # Deduplicate permissions
    permissions = sorted(list(set(permissions)))
    if not permissions:
        permissions = ["System Control"]
        
    yield _sse("done", "requires_confirmation", data={
        "status": "requires_confirmation",
        "transcription": transcription,
        "confirmation": {
            "id": confirmation_id,
            "confirmation_type": "execution_plan",
            "message": f"I will perform these actions to execute your request: '{transcription}'",
            "plan": planner_output.to_dict(),
            "steps": planner_output.to_dict().get("steps", []),
            "permissions": permissions,
            "estimated_actions": estimated_actions,
            "remaining_seconds": 60,
        },
        "intent": {"name": planner_output.intent, "confidence": round(planner_output.confidence * 100, 1)},
        "entities": command.entities,
        "planner": planner_output.to_dict(),
        "pipeline_time_ms": int((time.perf_counter() - pipeline_start) * 1000),
    })


def run_confirmation_stream(confirmation_id: str, edited_steps: list[dict] | None = None) -> Generator[str, None, None]:
    """Execute the pending action plan and stream the progress as SSE."""
    from agentic.memory.pending_action import PendingActionManager
    from agentic.memory.session_state import get_session
    from execution.executor import DesktopExecutor
    from agentic.schemas import ActionStep, ExecutionPlan
    import queue
    import threading
    
    session = get_session()
    pending_data = PendingActionManager.claim(confirmation_id)
    
    if not pending_data or pending_data.get("id") != confirmation_id:
        yield _sse("done", "error", message="Pending action timed out or not found.")
        return
        
    saved_plan = pending_data["plan"]
    
    # Use edited steps if provided, otherwise the saved steps
    steps_list = edited_steps if edited_steps is not None else saved_plan.get("steps", [])
    if not steps_list:
        PendingActionManager.clear()
        session.clear_pending_action()
        yield _sse("done", "error", message="Pending action plan is empty.")
        return

    # Validate edited plan steps if modified by user
    if edited_steps is not None:
        from agentic.llm.schemas import PlannerOutput, PlannerStep
        valid_steps = []
        for s in edited_steps:
            if not isinstance(s, dict) or "tool" not in s:
                PendingActionManager.clear()
                session.clear_pending_action()
                yield _sse("done", "error", message="Invalid step format in edited plan.")
                return
            valid_steps.append(PlannerStep(tool=s["tool"], args=s.get("args", {}), description=s.get("description")))
        temp_output = PlannerOutput(
            intent=saved_plan.get("intent", "custom"),
            confidence=1.0,
            reasoning="User-edited plan",
            steps=valid_steps
        )
        val_err = validate_execution_plan(temp_output)
        if val_err:
            PendingActionManager.clear()
            session.clear_pending_action()
            yield _sse("done", "error", message=f"Edited plan validation failed: {val_err}")
            return
        
    # The pending plan was atomically claimed above, preventing replay.
    session.clear_pending_action()
    
    plan_steps = [
        ActionStep(tool=s["tool"], args=s.get("args", {}))
        for s in steps_list
    ]
    plan = ExecutionPlan(
        thought=saved_plan.get("thought", "Executing approved plan"),
        steps=plan_steps,
        response=""
    )
    
    logger.info("[PIPELINE][EXEC] Stage START  steps=%d  confirmation_id=%s",
                len(plan_steps), confirmation_id)
    for _si, _s in enumerate(plan_steps, 1):
        logger.info("[PIPELINE][EXEC]   Step %d: tool=%s  args=%s", _si, _s.tool, _s.args)
    
    # Set Telegram state tokens from the explicit phase that was approved.
    # First-tool inference is retained only for legacy pending files.
    approved_confirmation_type = saved_plan.get("confirmation_type")
    if not approved_confirmation_type and plan_steps:
        if plan_steps[0].tool in ("open_telegram_chat", "open_chat"):
            approved_confirmation_type = "telegram_contact_confirmation"
        elif plan_steps[0].tool in ("send_telegram_message", "type_telegram_message"):
            approved_confirmation_type = "telegram_send_confirmation"

    if approved_confirmation_type == "telegram_contact_confirmation":
        from automation.telegram.telegram_automation import set_telegram_contact_confirmed
        set_telegram_contact_confirmed(True)
        logger.info("[TELEGRAM_CONFIRM] Contact confirmation approved — set contact_confirmed=True")
    elif approved_confirmation_type == "telegram_send_confirmation":
        from automation.telegram.telegram_automation import set_telegram_send_confirmed
        set_telegram_send_confirmed(True)
        logger.info("[TELEGRAM_CONFIRM] Send confirmation approved — set send_confirmed=True")

    yield _sse("execution", "running", message="Starting execution...")
    logger.info(f"Dispatching plan with {len(plan_steps)} steps to executor...")
    
    try:
        executor = DesktopExecutor()
        executor.bypass_confirmation = True
    except Exception as exc:

        logger.exception("Failed to initialize DesktopExecutor")
        yield _sse("execution", "failed", message=f"Executor init failed: {exc}")
        yield _sse("done", "error", data={"error": str(exc)})
        return
    
    progress_queue: queue.Queue[str | None] = queue.Queue()
    exec_results_holder: list[list[dict]] = []
    exec_error_holder: list[Exception] = []
    
    def _run_execution():
        try:
            full_results = executor.execute(plan, progress_callback=progress_queue.put)
            exec_results_holder.append(full_results)
        except Exception as e:
            exec_error_holder.append(e)
        finally:
            progress_queue.put(None)
            
    logger.info("Starting execution background thread...")
    logger.info("Execution Started")
    exec_thread = threading.Thread(target=_run_execution, daemon=True)
    exec_thread.start()
    
    while True:
        try:
            msg = progress_queue.get(timeout=120)
        except queue.Empty:
            logger.warning("Execution queue timed out after 120s")
            break
        if msg is None:
            break
        safe_msg = msg.encode("ascii", "replace").decode("ascii") if msg else ""
        logger.info(f"Execution progress: {safe_msg}")
        yield _sse("execution", "running", message=msg)
        
    logger.info("Waiting for execution thread to finish...")
    exec_thread.join(timeout=5)
    logger.info("Execution thread finished.")
    logger.info("Execution Finished")
    
    if exec_error_holder:
        yield _sse("execution", "failed", message=str(exec_error_holder[0]))
        yield _sse("done", "error", data={"error": str(exec_error_holder[0])})
        return
        
    exec_results = exec_results_holder[0] if exec_results_holder else []
    logger.debug("[SSE] Execution results holder: %d results, yielding %d steps", len(exec_results_holder), len(exec_results))
    yield _sse("execution", "completed", data={"steps": exec_results})

    # Check if any step in resumed execution requested a step-level confirmation (e.g. type_telegram_message for Phase 2)
    req_step_res = next((r for r in exec_results if r.get("requires_confirmation")), None)
    if req_step_res:
        logger.info("[PIPELINE] Execution paused during resume for step confirmation: tool=%s", req_step_res.get("tool"))
        remaining_steps = []
        found_pause = False
        for s in plan_steps:
            if found_pause:
                remaining_steps.append({"tool": s.tool, "args": s.args})
            elif s.tool == req_step_res.get("tool"):
                found_pause = True

        req_data = req_step_res.get("data", {})
        confirm_type = req_data.get("confirmation_type", "telegram_send_confirmation")
        contact_val = req_data.get("contact", "")
        msg_val = req_data.get("message", "")
        remaining_plan = {
            "intent": saved_plan.get("intent", "send_telegram_message"),
            "thought": saved_plan.get("thought", "Executing Telegram flow"),
            "confirmation_type": confirm_type,
            "phase": confirm_type,
            "steps": remaining_steps,
        }
        new_conf_id = PendingActionManager.save(remaining_plan)

        yield _sse("done", "requires_confirmation", data={
            "status": "requires_confirmation",
            "transcription": saved_plan.get("thought", ""),
            "confirmation": {
                "id": new_conf_id,
                "confirmation_type": confirm_type,
                "contact": contact_val,
                "message": req_data.get("message_prompt") or req_step_res.get("message") or f"Send '{msg_val}' to {contact_val}?",
                "message_text": msg_val,
                "plan": saved_plan,
                "remaining_seconds": 60,
            },
            "intent": {"name": saved_plan.get("intent", "send_telegram_message"), "confidence": 100},
            "entities": {},
            "planner": saved_plan,
            "pipeline_time_ms": 0,
        })
        return

    if not exec_results and plan_steps:
        failure_message = "Approved plan produced no execution results."
        yield _sse("execution", "failed", message=failure_message)
        yield _sse("done", "error", data={"error": failure_message})
        return

    failed_step = next((result for result in exec_results if not result.get("success", False)), None)
    if failed_step:
        failure_message = failed_step.get("message") or f"Execution failed at {failed_step.get('tool', 'unknown step')}."
        yield _sse("execution", "failed", data={"step": failed_step}, message=failure_message)
        yield _sse("done", "error", data={
            "error": failure_message,
            "intent": saved_plan.get("intent", "execute_confirmed"),
            "execution": exec_results,
        })
        return
    
    # Step 7: Response Generation + TTS
    yield _sse("response", "processing", message="Generating assistant response…")
    
    response_text = generate_response(exec_results)
    speech_audio_path = _generate_tts_file(response_text)
    
    speech_data: dict[str, Any] = {"text": response_text}
    if speech_audio_path:
        speech_data["audio_url"] = f"/static/audio/{os.path.basename(speech_audio_path)}"
        
    yield _sse("response", "completed", data=speech_data)
    if speech_audio_path:
        logger.info("Audio URL Sent")
    
    # Add to session history
    session.add_history(
        transcript=f"[Confirmed] {saved_plan.get('thought', 'User approved execution plan')}",
        intent="execute_confirmed",
        plan=saved_plan,
        result=response_text,
    )
    
    # Save session
    result = {
        "transcription": saved_plan.get('thought', 'User approved execution plan'),
        "stt": {"model": "", "device": "", "compute_type": "", "language": "", "confidence": 100, "processing_time_ms": 0},
        "intent": {"name": saved_plan.get("intent", "execute_confirmed"), "confidence": 100},
        "entities": {},
        "planner": saved_plan,
        "execution": exec_results,
        "speech": speech_data,
        "pipeline_time_ms": 0,
        "timestamp": datetime.now().isoformat(),
    }
    save_session(result)
    yield _sse("done", "success", data=result)
