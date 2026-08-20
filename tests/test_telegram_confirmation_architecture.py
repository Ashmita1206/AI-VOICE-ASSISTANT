"""
Tests for Telegram Confirmation Architecture & UI State Separation
===================================================================
Tests that generic application opening ('Open Telegram') uses the generic
execution-plan confirmation, while contact disambiguation and final send
safety confirmations remain strictly scoped to their respective messaging states.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from agent.intent_classifier import IntentClassifier
from agentic.llm.fallback import apply_heuristic_fallback
from agentic.llm.schemas import PlannerOutput, PlannerStep
from web.stream_service import validate_execution_plan, run_confirmation_stream, run_pipeline_stream
from agentic.memory.pending_action import PendingActionManager


class TestTelegramConfirmationArchitecture:

    # -------------------------------------------------------------------------
    # TEST 1: Open Telegram uses Generic Plan Confirmation
    # -------------------------------------------------------------------------
    def test_open_telegram_generic_confirmation_payload(self):
        """'Open Telegram' emits generic execution_plan confirmation, never contact confirmation."""
        # Simulate stream transcription event generation
        with patch("web.stream_service.get_classifier") as mock_clf_fn, \
             patch("agentic.llm.manager.get_planner_manager") as mock_plan_fn, \
             patch("agentic.discovery.manager.get_system_context", return_value={}):
            
            mock_clf = MagicMock()
            mock_cmd = MagicMock()
            mock_cmd.intent = "open_application"
            mock_cmd.confidence = 0.95
            mock_cmd.entities = {"application": "telegram"}
            mock_clf.classify.return_value = mock_cmd
            mock_clf_fn.return_value = mock_clf

            mock_planner = MagicMock()
            mock_planner_out = PlannerOutput(
                intent="launch_application",
                confidence=0.95,
                reasoning="Matched Telegram application launch.",
                steps=[PlannerStep(tool="launch_application", args={"application": "Telegram"}, description="Open Telegram")]
            )
            mock_planner.plan.return_value = mock_planner_out
            mock_plan_fn.return_value = mock_planner

            events = list(run_pipeline_stream(text="Open Telegram"))
            
            # Find the done event with requires_confirmation
            done_event = next((e for e in events if '"status": "requires_confirmation"' in e), None)
            assert done_event is not None
            
            # Parse payload
            data_line = next(line for line in done_event.split("\n") if line.startswith("data:"))
            payload = json.loads(data_line[5:].strip())
            
            conf = payload.get("data", {}).get("confirmation", {})
            assert conf.get("confirmation_type") == "execution_plan"
            assert conf.get("confirmation_type") != "telegram_contact_confirmation"
            assert conf.get("confirmation_type") != "telegram_send_confirmation"
            assert "Open Telegram" in conf.get("message", "")
            
            steps = conf.get("steps", [])
            assert len(steps) == 1
            assert steps[0].get("tool") == "launch_application"
            assert steps[0].get("args", {}).get("application") == "Telegram"

    # -------------------------------------------------------------------------
    # TEST 2: Plan Validation for Edited Steps
    # -------------------------------------------------------------------------
    def test_edited_plan_valid_steps_allowed(self):
        """Valid edited plan steps pass validation."""
        steps = [
            PlannerStep(tool="launch_application", args={"application": "Telegram"}, description="Launch Telegram")
        ]
        out = PlannerOutput(intent="launch_application", confidence=1.0, reasoning="User edited", steps=steps)
        err = validate_execution_plan(out)
        assert err is None

    def test_edited_plan_invalid_tool_rejected(self):
        """Invalid tool in edited plan fails validation safely."""
        steps = [
            PlannerStep(tool="malicious_or_unknown_tool", args={}, description="Unknown tool")
        ]
        out = PlannerOutput(intent="custom", confidence=1.0, reasoning="User edited", steps=steps)
        err = validate_execution_plan(out)
        assert err is not None
        assert "malicious_or_unknown_tool" in err or "Unknown tool" in err

    # -------------------------------------------------------------------------
    # TEST 3: Confirmation Stream with Edited Steps
    # -------------------------------------------------------------------------
    def test_confirmation_stream_executes_edited_plan(self):
        """Streaming confirmation handler validates and executes edited steps."""
        plan_dict = {
            "intent": "launch_application",
            "thought": "Open Telegram",
            "steps": [{"tool": "launch_application", "args": {"application": "Telegram"}}]
        }
        conf_id = PendingActionManager.save(plan_dict)

        edited_steps = [
            {"tool": "launch_application", "args": {"application": "Notepad"}, "description": "Open Notepad instead"}
        ]

        with patch("execution.executor.DesktopExecutor.execute") as mock_exec, \
             patch("web.stream_service.generate_response", return_value="Opened Notepad"), \
             patch("web.stream_service._generate_tts_file", return_value=None):
            
            mock_exec.return_value = [{"tool": "launch_application", "success": True, "message": "Opened Notepad"}]
            events = list(run_confirmation_stream(conf_id, edited_steps=edited_steps))
            
            completed_event = next((e for e in events if 'execution' in e and 'completed' in e), None)
            assert completed_event is not None
            mock_exec.assert_called_once()
            called_plan = mock_exec.call_args[0][0]
            assert called_plan.steps[0].tool == "launch_application"
            assert called_plan.steps[0].args == {"application": "Notepad"}

    # -------------------------------------------------------------------------
    # TEST 4: Telegram Messaging Safety Tokens Intact
    # -------------------------------------------------------------------------
    def test_send_telegram_message_cannot_bypass_confirmation(self):
        """send_telegram_message fails if send confirmation token is false."""
        from automation.telegram.telegram_automation import handle_send_telegram_message, set_telegram_send_confirmed, set_telegram_contact_confirmed
        set_telegram_contact_confirmed(True)
        set_telegram_send_confirmed(False)

        res = handle_send_telegram_message({"contact": "Harshita", "message": "Hello"})
        assert res.success is False
        assert "security violation" in res.message.lower() or "confirmation" in res.message.lower()

    # -------------------------------------------------------------------------
    # TEST 5: Telegram Heuristic Fallback Produces open_application
    # -------------------------------------------------------------------------
    def test_open_telegram_heuristic_fallback_plan(self):
        """'Open Telegram' fallback heuristic returns open_application tool with telegram entity."""
        po = apply_heuristic_fallback("open telegram")
        assert po.intent == "open_application"
        assert len(po.steps) == 1
        assert po.steps[0].tool == "open_application"
        assert po.steps[0].args == {"application": "telegram"}

    # -------------------------------------------------------------------------
    # TEST 7: Telegram Desktop verification never invokes Web verifier
    # -------------------------------------------------------------------------
    def test_telegram_desktop_verification_does_not_invoke_web_verifier(self):
        """When launcher returns mode='desktop' and Desktop window is verified, Web verifier is never called."""
        from execution.verifier import dispatch_verify
        from execution.schemas import ExecutionResult

        res = ExecutionResult(
            success=True,
            tool="open_telegram",
            message="Opened Telegram Desktop.",
            data={"success": True, "opened": True, "client": "telegram_desktop", "mode": "desktop", "ready": True}
        )

        with patch("execution.verifier._is_window_visible", return_value=True), \
             patch("execution.verifier.verify_application_launched", return_value=MagicMock(passed=True)), \
             patch("automation.browser.find_and_focus_browser_tab") as mock_web_focus:

            vr = dispatch_verify("open_telegram", {}, res)
            assert vr.passed is True
            # The Web verifier must NEVER be called for mode="desktop"
            mock_web_focus.assert_not_called()

    # -------------------------------------------------------------------------
    # TEST 8: Full sequential desktop trace proceeds directly to search_telegram_contact
    # -------------------------------------------------------------------------
    def test_telegram_desktop_execution_trace_proceeds_to_search(self):
        """Telegram Desktop launch success allows search_telegram_contact to execute immediately."""
        from execution.executor import DesktopExecutor
        from agentic.schemas import ActionStep, ExecutionPlan
        from automation.telegram.models import TelegramContact
        from automation.telegram.telegram_automation import _telegram_state

        _telegram_state["ready"] = True
        _telegram_state["client"] = "telegram_desktop"
        _telegram_state["mode"] = "desktop"

        plan = ExecutionPlan(
            thought="Test desktop trace",
            steps=[
                ActionStep(tool="open_telegram", args={}),
                ActionStep(tool="search_telegram_contact", args={"contact": "Harshita"}),
            ]
        )

        executor = DesktopExecutor()
        executor.bypass_confirmation = True

        with patch("automation.telegram.telegram_automation.find_telegram_desktop", return_value="C:\\Telegram\\Telegram.exe"), \
             patch("subprocess.Popen") as mock_popen, \
             patch("execution.verifier.verify_application_launched", return_value=MagicMock(passed=True)), \
             patch("execution.verifier._is_window_visible", return_value=True), \
             patch("automation.telegram.telegram_automation._collect_desktop_search_candidates", return_value=[
                 (TelegramContact(id=1, name="Harshita"), "Harshita, Pinned")
             ]), \
             patch("pyautogui.write") as mock_write:

            results = executor.execute(plan)
            assert len(results) >= 2
            assert results[0]["tool"] == "open_telegram"
            assert results[0]["success"] is True
            assert results[1]["tool"] == "search_telegram_contact"
            assert results[1]["success"] is True
