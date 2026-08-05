"""
Stateful Executor Tests
=======================

Comprehensive test suite for the stateful execution engine.

Covers:
- WaitResult dataclass and dispatch_wait routing
- wait_until_process_running timeout behaviour
- StepStatus lifecycle transitions
- StepRecord state tracking helpers
- ExecutionContext.from_plan() construction
- dispatch_verify routing per tool type
- recover_step strategy selection
- DesktopExecutor full sequential plan execution (happy path)
- DesktopExecutor failure → recovery → retry cycle
- DesktopExecutor max_retries cap (no infinite loops)
- ActionStep.from_dict() parsing of wait_for / timeout / requires / max_retries
- ExecutionResult new fields: state, attempts, recovery_used
- PermissionManager recognises new wait tools as SAFE

All external I/O (psutil, win32gui, tool handlers) is mocked so these tests
run without requiring a desktop environment or real applications.
"""

from __future__ import annotations

import time
import sys
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch, call
import pytest


# ---------------------------------------------------------------------------
# Helpers / minimal fakes
# ---------------------------------------------------------------------------

def _make_result(success: bool = True, tool: str = "noop", message: str = "") :
    from execution.schemas import ExecutionResult
    return ExecutionResult(success=success, tool=tool, message=message)


def _make_step(tool: str, args: dict | None = None, *, wait_for=None, timeout=None, max_retries=2):
    from agentic.schemas import ActionStep
    return ActionStep(
        tool=tool,
        args=args or {},
        wait_for=wait_for,
        timeout=timeout,
        max_retries=max_retries,
    )


def _make_plan(*steps):
    from agentic.schemas import ExecutionPlan
    return ExecutionPlan(thought="test", steps=list(steps))


# ===========================================================================
# 1. WaitResult dataclass
# ===========================================================================

class TestWaitResult:
    def test_default_fields(self):
        from execution.wait_utils import WaitResult
        wr = WaitResult(success=True)
        assert wr.success is True
        assert wr.elapsed_ms == 0
        assert wr.message == ""

    def test_failure_fields(self):
        from execution.wait_utils import WaitResult
        wr = WaitResult(success=False, elapsed_ms=5000, message="Timeout")
        assert wr.success is False
        assert wr.elapsed_ms == 5000
        assert "Timeout" in wr.message


# ===========================================================================
# 2. wait_until_process_running (mocked psutil)
# ===========================================================================

class TestWaitUntilProcessRunning:
    def test_finds_process_immediately(self):
        from execution.wait_utils import wait_until_process_running

        mock_proc = MagicMock()
        mock_proc.info = {"pid": 1234, "name": "Spotify.exe"}

        with patch("execution.wait_utils._try_import_psutil") as m_psutil:
            psutil_mock = MagicMock()
            psutil_mock.process_iter.return_value = [mock_proc]
            m_psutil.return_value = psutil_mock

            result = wait_until_process_running("spotify", timeout=5.0)

        assert result.success is True
        assert "spotify" in result.message.lower() or "running" in result.message.lower()

    def test_times_out_when_process_absent(self):
        from execution.wait_utils import wait_until_process_running

        with patch("execution.wait_utils._try_import_psutil") as m_psutil:
            psutil_mock = MagicMock()
            psutil_mock.process_iter.return_value = []   # nothing running
            m_psutil.return_value = psutil_mock

            result = wait_until_process_running("nonexistent_app", timeout=0.2, poll_interval=0.05)

        assert result.success is False
        assert "timeout" in result.message.lower()

    def test_returns_failure_when_psutil_unavailable(self):
        from execution.wait_utils import wait_until_process_running

        with patch("execution.wait_utils._try_import_psutil", return_value=None):
            result = wait_until_process_running("spotify", timeout=5.0)

        assert result.success is False
        assert "psutil" in result.message.lower()


# ===========================================================================
# 3. dispatch_wait routing
# ===========================================================================

class TestDispatchWait:
    def _patch_all_waits(self, success=True):
        """Return a context that mocks every wait primitive to return success/failure."""
        from execution.wait_utils import WaitResult
        ok = WaitResult(success=success, elapsed_ms=10, message="mocked")
        targets = [
            "execution.wait_utils.wait_until_application_ready",
            "execution.wait_utils.wait_until_process_running",
            "execution.wait_utils.wait_until_window_exists",
            "execution.wait_utils.wait_until_window_active",
            "execution.wait_utils.wait_until_element_ready",
            "execution.wait_utils.wait_until_browser_loaded",
        ]
        return [patch(t, return_value=ok) for t in targets]

    def test_window_ready_routes_to_application_ready(self):
        from execution.wait_utils import dispatch_wait, WaitResult
        ok = WaitResult(success=True, message="ok")
        with patch("execution.wait_utils.wait_until_application_ready", return_value=ok) as m:
            result = dispatch_wait("window_ready", {"application": "spotify"}, timeout=20)
        m.assert_called_once()
        assert result.success is True

    def test_process_running_routes_correctly(self):
        from execution.wait_utils import dispatch_wait, WaitResult
        ok = WaitResult(success=True, message="ok")
        with patch("execution.wait_utils.wait_until_process_running", return_value=ok) as m:
            result = dispatch_wait("process_running", {"application": "chrome"}, timeout=15)
        m.assert_called_once()
        assert result.success is True

    def test_unknown_wait_for_is_skipped(self):
        from execution.wait_utils import dispatch_wait
        result = dispatch_wait("completely_unknown_condition", {}, timeout=5)
        # Unknown condition should succeed (pass-through / no-op)
        assert result.success is True


# ===========================================================================
# 4. StepStatus enum
# ===========================================================================

class TestStepStatus:
    def test_all_statuses_present(self):
        from execution.step_state import StepStatus
        required = {"PENDING", "EXECUTING", "WAITING", "VERIFYING", "RECOVERY", "RETRY", "SUCCESS", "FAILURE"}
        actual = {s.name for s in StepStatus}
        assert required.issubset(actual)

    def test_terminal_statuses(self):
        from execution.step_state import StepStatus, StepRecord
        record = StepRecord(step_index=0, tool="noop")
        assert not record.is_terminal

        record.mark_success(_make_result())
        assert record.is_terminal
        assert record.status == StepStatus.SUCCESS

    def test_failure_is_terminal(self):
        from execution.step_state import StepRecord
        record = StepRecord(step_index=0, tool="noop")
        record.mark_failure("something broke")
        assert record.is_terminal


# ===========================================================================
# 5. StepRecord lifecycle transitions
# ===========================================================================

class TestStepRecord:
    def test_initial_state(self):
        from execution.step_state import StepStatus, StepRecord
        r = StepRecord(step_index=0, tool="open_application", args={"application": "spotify"})
        assert r.status == StepStatus.PENDING
        assert r.attempts == 0
        assert r.can_retry  # 0 retries used; max_retries=2

    def test_mark_executing_increments_attempts(self):
        from execution.step_state import StepRecord
        r = StepRecord(step_index=0, tool="noop")
        r.mark_executing()
        assert r.attempts == 1
        assert r.started_at > 0

    def test_can_retry_after_first_failure(self):
        from execution.step_state import StepRecord
        r = StepRecord(step_index=0, tool="noop", max_retries=2)
        r.mark_executing()   # attempts=1
        # 0 retries used; can retry
        assert r.can_retry

    def test_cannot_retry_after_max_retries(self):
        from execution.step_state import StepRecord
        r = StepRecord(step_index=0, tool="noop", max_retries=2)
        r.mark_executing()   # attempts=1 (first try)
        r.mark_retry()       # attempts=2 (retry 1)
        r.mark_retry()       # attempts=3 (retry 2 = max)
        assert not r.can_retry

    def test_to_dict_shape(self):
        from execution.step_state import StepRecord
        r = StepRecord(step_index=2, tool="check_time")
        r.mark_executing()
        r.mark_success(_make_result())
        d = r.to_dict()
        assert d["step_index"] == 2
        assert d["tool"] == "check_time"
        assert d["status"] == "success"
        assert d["attempts"] == 1


# ===========================================================================
# 6. ExecutionContext.from_plan()
# ===========================================================================

class TestExecutionContext:
    def test_builds_records_from_plan(self):
        from execution.step_state import ExecutionContext, StepStatus
        plan = _make_plan(
            _make_step("check_time"),
            _make_step("take_screenshot"),
        )
        ctx = ExecutionContext.from_plan(plan)
        assert len(ctx.records) == 2
        assert ctx.records[0].tool == "check_time"
        assert ctx.records[1].tool == "take_screenshot"
        assert all(r.status == StepStatus.PENDING for r in ctx.records)

    def test_wait_for_propagated(self):
        from execution.step_state import ExecutionContext
        plan = _make_plan(
            _make_step("launch_application", {"application": "spotify"}, wait_for="window_ready", timeout=20),
        )
        ctx = ExecutionContext.from_plan(plan)
        assert ctx.records[0].wait_for == "window_ready"
        assert ctx.records[0].timeout == 20

    def test_all_succeeded_property(self):
        from execution.step_state import ExecutionContext
        plan = _make_plan(_make_step("check_time"))
        ctx = ExecutionContext.from_plan(plan)
        assert not ctx.all_succeeded
        ctx.records[0].mark_success(_make_result())
        assert ctx.all_succeeded


# ===========================================================================
# 7. dispatch_verify routing
# ===========================================================================

class TestDispatchVerify:
    def test_launch_tool_routes_to_application_verifier(self):
        from execution.verifier import dispatch_verify
        result = _make_result(success=True)
        with patch("execution.verifier.verify_application_launched") as m, \
             patch("execution.verifier._is_window_foreground", return_value=True):
            m.return_value = MagicMock(passed=True, message="ok")
            vr = dispatch_verify("launch_application", {"application": "spotify"}, result)
        m.assert_called_once_with("spotify")
        assert vr.passed

    def test_type_text_routes_to_text_verifier(self):
        from execution.verifier import dispatch_verify
        result = _make_result(success=True)
        vr = dispatch_verify("type_text", {"text": "Believer"}, result)
        assert vr.passed  # text_typed always passes

    def test_failed_handler_result_skips_deep_verification(self):
        from execution.verifier import dispatch_verify
        result = _make_result(success=False, message="handler failed")
        vr = dispatch_verify("launch_application", {"application": "spotify"}, result)
        assert not vr.passed

    def test_press_key_always_passes(self):
        from execution.verifier import dispatch_verify
        result = _make_result(success=True)
        vr = dispatch_verify("press_key", {"key": "enter"}, result)
        assert vr.passed

    def test_generic_fallback_trusts_handler_success(self):
        from execution.verifier import dispatch_verify
        result = _make_result(success=True)
        vr = dispatch_verify("check_time", {}, result)
        assert vr.passed

    def test_generic_fallback_propagates_handler_failure(self):
        from execution.verifier import dispatch_verify
        result = _make_result(success=False)
        vr = dispatch_verify("check_time", {}, result)
        assert not vr.passed


# ===========================================================================
# 8. RecoveryResult and recover_step
# ===========================================================================

class TestRecoveryResult:
    def test_dataclass_fields(self):
        from execution.recovery import RecoveryResult
        rr = RecoveryResult(succeeded=True, strategy_used="bring_to_foreground", message="ok")
        assert rr.succeeded
        assert rr.strategy_used == "bring_to_foreground"

class TestRecoverStep:
    def _make_record(self, tool: str, app: str = "spotify"):
        from execution.step_state import StepRecord
        return StepRecord(step_index=0, tool=tool, args={"application": app})

    def test_recover_step_calls_screenshot(self):
        from execution.recovery import recover_step
        from execution.step_state import ExecutionContext
        from agentic.schemas import ExecutionPlan

        plan = _make_plan(_make_step("launch_application", {"application": "spotify"}))
        ctx = ExecutionContext.from_plan(plan)
        record = ctx.records[0]
        record.mark_executing()

        with patch("execution.recovery.capture_recovery_screenshot", return_value=None) as sc, \
             patch("execution.recovery.relaunch_application") as rl:
            from execution.recovery import RecoveryResult
            rl.return_value = RecoveryResult(succeeded=True, strategy_used="relaunch_application", message="ok")
            with patch("execution.wait_utils.wait_until_process_running") as wpr:
                from execution.wait_utils import WaitResult
                wpr.return_value = WaitResult(success=True, message="ok")
                result = recover_step(record, ctx)

        sc.assert_called_once_with(0)
        assert result.succeeded

    def test_all_strategies_exhausted_returns_failure(self):
        from execution.recovery import recover_step, RecoveryResult
        from execution.step_state import ExecutionContext

        plan = _make_plan(_make_step("launch_application", {"application": "nonexistent_app_12345"}))

        ctx = ExecutionContext.from_plan(plan)
        record = ctx.records[0]
        record.mark_executing()

        fail = RecoveryResult(succeeded=False, strategy_used="x", message="fail")
        with patch("execution.recovery.capture_recovery_screenshot", return_value=None), \
             patch("execution.recovery.relaunch_application", return_value=fail), \
             patch("execution.recovery.restore_minimized_window", return_value=fail), \
             patch("execution.recovery.bring_to_foreground", return_value=fail):
            result = recover_step(record, ctx)

        assert not result.succeeded


# ===========================================================================
# 9. DesktopExecutor — full sequential plan (happy path)
# ===========================================================================

class TestDesktopExecutorHappyPath:
    def test_sequential_steps_all_succeed(self):
        """All steps succeed on first attempt; no recovery needed."""
        from execution.executor import DesktopExecutor
        from execution.step_state import StepStatus

        executor = DesktopExecutor()
        plan = _make_plan(
            _make_step("check_time"),
            _make_step("take_screenshot"),
        )

        ok_result = _make_result(success=True)
        ok_verify = MagicMock(passed=True, message="ok")

        with patch.object(executor, "execute_step", return_value=ok_result) as ex_step, \
             patch("execution.executor.dispatch_verify", return_value=ok_verify), \
             patch("execution.executor.dispatch_wait") as dw:

            results = executor.execute(plan)

        assert len(results) == 2
        assert all(r["success"] for r in results)
        assert ex_step.call_count == 2

    def test_wait_for_dispatched_when_set(self):
        """Steps with wait_for trigger dispatch_wait."""
        from execution.executor import DesktopExecutor
        from execution.wait_utils import WaitResult

        executor = DesktopExecutor()
        plan = _make_plan(
            _make_step("launch_application", {"application": "spotify"},
                       wait_for="window_ready", timeout=20)
        )

        ok_result = _make_result(success=True)
        ok_verify = MagicMock(passed=True, message="ok")
        ok_wait = WaitResult(success=True, elapsed_ms=500, message="ok")

        with patch.object(executor, "execute_step", return_value=ok_result), \
             patch("execution.executor.dispatch_verify", return_value=ok_verify), \
             patch("execution.executor.dispatch_wait", return_value=ok_wait) as dw:

            results = executor.execute(plan)

        dw.assert_called_once_with("window_ready", {"application": "spotify"}, ok_result, 20)
        assert results[0]["success"] is True


# ===========================================================================
# 10. DesktopExecutor — failure → recovery → retry
# ===========================================================================

class TestDesktopExecutorRecovery:
    def test_recovery_invoked_on_verify_failure(self):
        """If verification fails, recovery is attempted and retry succeeds."""
        from execution.executor import DesktopExecutor
        from execution.verifier import VerifyResult
        from execution.recovery import RecoveryResult
        from execution.wait_utils import WaitResult

        executor = DesktopExecutor()
        plan = _make_plan(_make_step("launch_application", {"application": "spotify"}, max_retries=1))

        ok_result = _make_result(success=True)
        fail_verify = VerifyResult(passed=False, message="not found")
        ok_verify = VerifyResult(passed=True, message="ok")
        ok_recovery = RecoveryResult(succeeded=True, strategy_used="bring_to_foreground", message="ok")

        verify_side_effects = [fail_verify, ok_verify]

        with patch.object(executor, "execute_step", return_value=ok_result), \
             patch("execution.executor.dispatch_verify", side_effect=verify_side_effects), \
             patch("execution.executor.recover_step", return_value=ok_recovery), \
             patch("execution.executor.dispatch_wait", return_value=WaitResult(success=True)):

            results = executor.execute(plan)

        assert results[0]["success"] is True
        assert results[0]["recovery_used"] is True

    def test_max_retries_cap_prevents_infinite_loop(self):
        """Verification always fails → engine gives up after max_retries."""
        from execution.executor import DesktopExecutor
        from execution.verifier import VerifyResult
        from execution.recovery import RecoveryResult

        executor = DesktopExecutor()
        plan = _make_plan(_make_step("launch_application", {"application": "spotify"}, max_retries=2))

        ok_result = _make_result(success=True)
        fail_verify = VerifyResult(passed=False, message="never verified")
        ok_recovery = RecoveryResult(succeeded=True, strategy_used="bring_to_foreground", message="ok")

        with patch.object(executor, "execute_step", return_value=ok_result), \
             patch("execution.executor.dispatch_verify", return_value=fail_verify), \
             patch("execution.executor.recover_step", return_value=ok_recovery), \
             patch("execution.executor.dispatch_wait"):

            results = executor.execute(plan)

        # Should fail, not loop forever
        assert results[0]["success"] is False
        assert results[0]["state"] == "failure"
        # Attempts = 1 (initial) + 2 (retries) = 3 max
        assert results[0]["attempts"] <= 3

    def test_plan_halts_after_step_failure(self):
        """Remaining steps are not executed after a FAILURE step."""
        from execution.executor import DesktopExecutor
        from execution.verifier import VerifyResult
        from execution.recovery import RecoveryResult

        executor = DesktopExecutor()
        plan = _make_plan(
            _make_step("launch_application", {"application": "spotify"}, max_retries=0),
            _make_step("search_inside_application", {"query": "Believer"}),
        )

        ok_result = _make_result(success=True)
        fail_verify = VerifyResult(passed=False, message="failed")

        with patch.object(executor, "execute_step", return_value=ok_result), \
             patch("execution.executor.dispatch_verify", return_value=fail_verify), \
             patch("execution.executor.dispatch_wait"):

            results = executor.execute(plan)

        # Only 1 result because plan halted
        assert len(results) == 1
        assert results[0]["success"] is False


# ===========================================================================
# 11. ActionStep.from_dict() parses new metadata fields
# ===========================================================================

class TestActionStepFromDict:
    def test_parses_wait_for_and_timeout(self):
        from agentic.schemas import ExecutionPlan
        data = {
            "thought": "test",
            "steps": [
                {
                    "tool": "launch_application",
                    "args": {"application": "spotify"},
                    "wait_for": "window_ready",
                    "timeout": 25,
                    "requires": "Spotify Ready",
                    "max_retries": 3,
                }
            ],
            "response": "ok"
        }
        plan = ExecutionPlan.from_dict(data)
        step = plan.steps[0]
        assert step.wait_for == "window_ready"
        assert step.timeout == 25
        assert step.requires == "Spotify Ready"
        assert step.max_retries == 3

    def test_old_format_still_works(self):
        """Plans without the new fields should parse without errors."""
        from agentic.schemas import ExecutionPlan
        data = {
            "thought": "old plan",
            "steps": [
                {"tool": "check_time", "args": {}}
            ],
            "response": ""
        }
        plan = ExecutionPlan.from_dict(data)
        step = plan.steps[0]
        assert step.wait_for is None
        assert step.timeout is None
        assert step.max_retries == 2  # default


# ===========================================================================
# 12. ExecutionResult new fields
# ===========================================================================

class TestExecutionResultNewFields:
    def test_default_field_values(self):
        from execution.schemas import ExecutionResult
        r = ExecutionResult(success=True, tool="check_time")
        assert r.state == ""
        assert r.attempts == 1
        assert r.recovery_used is False

    def test_to_dict_includes_new_fields(self):
        from execution.schemas import ExecutionResult
        r = ExecutionResult(
            success=True, tool="check_time",
            state="success", attempts=2, recovery_used=True
        )
        d = r.to_dict()
        assert d["state"] == "success"
        assert d["attempts"] == 2
        assert d["recovery_used"] is True

    def test_to_dict_state_falls_back_to_success(self):
        from execution.schemas import ExecutionResult
        r = ExecutionResult(success=True, tool="check_time")
        d = r.to_dict()
        assert d["state"] == "success"

    def test_to_dict_state_falls_back_to_failure(self):
        from execution.schemas import ExecutionResult
        r = ExecutionResult(success=False, tool="check_time")
        d = r.to_dict()
        assert d["state"] == "failure"


# ===========================================================================
# 13. PermissionManager — new wait tools are SAFE
# ===========================================================================

class TestPermissionManagerWaitTools:
    @pytest.mark.parametrize("tool", [
        "wait_until_process_running",
        "wait_until_window_exists",
        "wait_until_window_active",
        "wait_until_application_ready",
        "wait_until_element_ready",
        "wait_until_browser_loaded",
    ])
    def test_wait_tools_are_safe(self, tool):
        from agentic.permissions import PermissionManager
        assert PermissionManager.is_safe(tool), (
            f"'{tool}' should be in SAFE_TOOLS but is not."
        )

    @pytest.mark.parametrize("tool", [
        "wait_until_process_running",
        "wait_until_window_active",
    ])
    def test_wait_tools_do_not_require_confirmation(self, tool):
        from agentic.permissions import PermissionManager
        assert not PermissionManager.requires_confirmation(tool, {}), (
            f"'{tool}' should NOT require confirmation."
        )

def test_delayed_browser_load():
    """Verify that search_inside_application is not executed if ui_ready times out,
    and verify that it waits properly when ui_ready polls successfully after a delay."""
    from agentic.schemas import ExecutionPlan, ActionStep
    from execution.executor import DesktopExecutor
    from execution.schemas import ExecutionResult

    plan = ExecutionPlan(
        thought="test_ui_ready",
        steps=[
            ActionStep(
                tool="launch_application",
                args={"application": "whatsapp"},
                wait_for="ui_ready",
                timeout=0.3
            ),
            ActionStep(
                tool="search_inside_application",
                args={"query": "test"}
            )
        ]
    )

    executor = DesktopExecutor()
    
    # Mock dispatch_wait to simulate a delayed DOM load
    from execution.verifier import VerifyResult
    with patch("execution.executor.dispatch_wait") as mock_wait:
        from execution.wait_utils import WaitResult
        # 1. Simulate timeout (DOM never renders)
        mock_wait.return_value = WaitResult(success=False, elapsed_ms=300, message="Timeout")
        
        with patch.object(executor, "execute_step", return_value=ExecutionResult(success=True, tool="launch_application")) as mock_exec:
            results = executor.execute(plan)
            # Should halt after launch_application because wait failed
            assert len(results) == 1
            assert results[0]["tool"] == "launch_application"
            # execute_step is called 3 times due to 2 retries on wait failure
            assert mock_exec.call_count == 3
            
        # 2. Simulate delayed success
        mock_wait.return_value = WaitResult(success=True, elapsed_ms=200, message="UI ready")
        
        with patch("execution.executor.dispatch_verify", return_value=VerifyResult(passed=True, message="")), \
             patch.object(executor, "execute_step", return_value=ExecutionResult(success=True, tool="mock")) as mock_exec:
            results = executor.execute(plan)
            # Should execute both steps
            assert len(results) == 2
            assert mock_exec.call_count == 2
