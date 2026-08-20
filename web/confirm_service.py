"""
Confirmation Service
====================

Handles button-driven confirmations (proceed / cancel) for pending actions.
This module is called by the /confirm endpoint and operates independently
of the main voice pipeline.
"""

import os
import time
import logging
from typing import Any

from agentic.memory.session_state import get_session
from execution.registry import get_handler, load_all_tools
from tts.response_generator import generate_response
from storage.history_manager import save_session
from datetime import datetime
from agentic.permissions import PermissionManager

logger = logging.getLogger(__name__)

# Ensure all tool handlers are registered
load_all_tools()


def handle_confirm(confirmation_id: str, decision: str, edited_steps: list[dict] | None = None) -> dict[str, Any]:
    """Process a user's confirmation decision (proceed or cancel)."""
    session = get_session()

    from agentic.memory.pending_action import PendingActionManager
    pending_data = PendingActionManager.get_pending_action()

    if not pending_data or pending_data.get("id") != confirmation_id:
        # Check session as fallback
        if session.pending_action and session.pending_action.get("id") == confirmation_id:
            # Check timeout (60 seconds)
            if time.time() - session.pending_action.get("timestamp", 0) > 60:
                return {
                    "success": False,
                    "message": "Confirmation request timed out.",
                }
            pending_data = {
                "id": confirmation_id,
                "plan": {
                    "intent": "execute_action",
                    "steps": [
                        {
                            "tool": session.pending_action["tool"],
                            "args": session.pending_action["args"]
                        }
                    ]
                }
            }
        else:
            return {
                "success": False,
                "message": "No matching pending action found. It may have already been resolved or timed out.",
            }

    # Extract first step details for confirmation logging
    saved_plan = pending_data["plan"]
    steps_list = edited_steps if edited_steps is not None else saved_plan.get("steps", [])
    if not steps_list:
        PendingActionManager.clear()
        session.clear_pending_action()
        return {
            "success": False,
            "message": "Pending action contains an empty plan.",
        }

    first_step_dict = steps_list[0]
    tool_name = first_step_dict["tool"]
    tool_args = first_step_dict["args"]
    confirm_msg = PermissionManager.build_confirmation_message(tool_name, tool_args)

    if decision == "cancel":
        # Clear state
        PendingActionManager.clear()
        session.clear_pending_action()

        # Add to short-term history
        session.add_history(
            transcript=f"[Cancelled] {confirm_msg}",
            intent="cancel_confirmation",
            plan={"tool": tool_name, "args": tool_args},
            result="Action cancelled.",
        )

        return {
            "success": True,
            "message": "Action cancelled.",
        }

    if decision == "proceed":
        # Clear pending BEFORE execution to avoid stale/duplicate triggers
        PendingActionManager.clear()
        session.clear_pending_action()

        # Reconstruct remaining execution plan steps
        from agentic.schemas import ActionStep, ExecutionPlan
        plan_steps = [
            ActionStep(tool=s["tool"], args=s["args"])
            for s in steps_list
        ]

        from execution.executor import DesktopExecutor
        executor = DesktopExecutor()
        executor.bypass_confirmation = True

        # 1. Execute the first step directly (bypassing confirmation)
        first_step = plan_steps[0]
        try:
            first_res = executor.execute_step(first_step)
            exec_results = [first_res.to_dict()]

            # Update session application and directory context if applicable
            if first_step.tool == "open_application":
                session.set_context(app=first_step.args.get("application"))
            elif first_step.tool in ("open_folder", "list_files"):
                session.set_context(directory=first_step.args.get("path") or first_step.args.get("directory"))

            # 2. If the first step succeeded and there are remaining steps, run them through DesktopExecutor
            if first_res.success and len(plan_steps) > 1:
                remaining_plan = ExecutionPlan(
                    thought="Executing remaining steps after confirmation",
                    steps=plan_steps[1:],
                    response=""
                )
                rem_results = executor.execute(remaining_plan)
                exec_results.extend(rem_results)

            # Generate natural language response text
            response_text = generate_response(exec_results)

            # Generate TTS audio file
            audio_url = None
            try:
                from web.services import _generate_tts_file
                audio_path = _generate_tts_file(response_text)
                if audio_path:
                    audio_url = f"/static/audio/{os.path.basename(audio_path)}"
            except Exception as tts_err:
                logger.warning(f"TTS generation failed after confirmation: {tts_err}")

            # Add to short-term history
            session.add_history(
                transcript=f"[Confirmed] {confirm_msg}",
                intent="execute_confirmed",
                plan=saved_plan,
                result=response_text,
            )

            # Save to persistent SQLite storage
            save_session({
                "transcription": f"[Confirmed] {confirm_msg}",
                "stt": {"model": "", "device": "", "compute_type": "",
                        "language": "", "confidence": 0, "processing_time_ms": 0},
                "intent": {"name": "execute_confirmed", "confidence": 100.0},
                "entities": {},
                "planner": {"thought": "User confirmed pending action", "steps": steps_list},
                "execution": exec_results,
                "speech": {"text": response_text, "audio_url": audio_url},
                "pipeline_time_ms": 0,
                "timestamp": datetime.now().isoformat(),
            })

            return {
                "success": all(r.get("success", False) for r in exec_results),
                "message": response_text,
                "execution": exec_results,
                "speech": {
                    "text": response_text,
                    "audio_url": audio_url,
                },
            }

        except Exception as e:
            logger.exception(f"Error executing confirmed action {tool_name}")
            return {
                "success": False,
                "message": f"Execution failed: {e}",
            }

    return {
        "success": False,
        "message": f"Unknown decision: '{decision}'. Expected 'proceed' or 'cancel'.",
    }


def get_pending_confirmation() -> dict[str, Any] | None:
    """Return the current pending confirmation for the frontend.

    Called by GET /pending to restore the confirmation card after page refresh.
    Returns None if no pending action exists.
    """
    from agentic.memory.pending_action import PendingActionManager
    pending_data = PendingActionManager.get_pending_action()
    if pending_data:
        plan_dict = pending_data["plan"]
        steps = plan_dict.get("steps", [])
        
        permissions = []
        estimated_actions = []
        for s in steps:
            tool = s.get("tool", "")
            args = s.get("args", {})
            if tool in ("press_key", "type_text", "hotkey"):
                permissions.append("Keyboard Control")
            elif tool in ("click", "double_click", "right_click", "scroll", "drag"):
                permissions.append("Mouse Control")
            elif tool in ("launch_application", "focus_window", "close_window", "is_app_running", "activate_window"):
                permissions.append("Foreground Window Control")
            elif tool in ("open_browser", "open_website", "open_whatsapp"):
                permissions.append("Browser Automation")
            elif tool in ("search_inside_application", "perform_app_action"):
                permissions.append("Accessibility/UI Automation")
            elif tool in ("ocr", "locate_ui_element", "find_text", "take_screenshot"):
                permissions.append("Screen Capture")
            elif tool in ("create_file", "create_folder", "delete_file", "delete_folder", "read_directory", "list_files"):
                permissions.append("File System Access")
                
            if tool == "launch_application":
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
                
        permissions = sorted(list(set(permissions)))
        if not permissions:
            permissions = ["System Control"]
            
        elapsed = time.time() - pending_data.get("created_at", time.time())
        return {
            "id": pending_data["id"],
            "confirmation_type": "execution_plan",
            "message": "I will perform these actions to execute your request",
            "plan": plan_dict,
            "steps": steps,
            "permissions": permissions,
            "estimated_actions": estimated_actions,
            "remaining_seconds": max(0, int(60 - elapsed)),
        }

    session = get_session()
    return session.get_pending_confirmation()
