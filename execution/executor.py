"""
Stateful Execution Engine
=========================

Reads ``ActionStep`` objects from an ``ExecutionPlan``, runs them through the
safety layer, dispatches them to the registered handler, and returns a list of
``ExecutionResult`` dicts.

Key difference from the previous implementation
------------------------------------------------
Every step now follows a full lifecycle::

    PENDING → EXECUTING → WAITING → VERIFYING → SUCCESS

On verification failure::

    VERIFYING → RECOVERY → RETRY → VERIFYING → SUCCESS | FAILURE

*Recovery* is capped at ``step.max_retries`` attempts (default: 2) to avoid
infinite loops.  All waiting is done via configurable condition-polling from
:mod:`execution.wait_utils` — no bare ``time.sleep()`` in the main execution
path.

Backward compatibility
----------------------
* ``SystemExecutor`` alias is preserved.
* ``ExecutionResult.to_dict()`` output is a strict superset of the previous
  format: three new fields (``state``, ``attempts``, ``recovery_used``) are
  added, all with sensible defaults.
* Plans produced by the old planner (without ``wait_for`` / ``timeout``) still
  work because those fields default to ``None``.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any, Callable, Optional

from agentic.schemas import ExecutionPlan, ActionStep
from execution.schemas import ExecutionResult, ExecutionTimer
from execution.registry import get_handler, load_all_tools
from execution.step_state import StepStatus, StepRecord, ExecutionContext
from execution.wait_utils import dispatch_wait, WaitResult
from execution.verifier import dispatch_verify, VerifyResult
from execution.recovery import recover_step, RecoveryResult

logger = logging.getLogger(__name__)

# Load all tool handlers so their @register_tool decorators fire at import time
load_all_tools()

from agentic.permissions import PermissionManager


# ---------------------------------------------------------------------------
# Stateful Executor
# ---------------------------------------------------------------------------

class DesktopExecutor:
    """Executes a parsed ExecutionPlan against the local system.

    Uses a state-aware step lifecycle (PENDING → EXECUTING → WAITING →
    VERIFYING → SUCCESS | FAILURE) with configurable wait primitives and a
    structured recovery engine.

    Attributes
    ----------
    pending_steps:
        Steps awaiting user confirmation (populated when a confirmation gate
        fires and execution is paused).
    """

    def __init__(self) -> None:
        # Populated when a safety-gate confirmation is triggered
        self.pending_steps: list[ActionStep] = []

    # ── Public API ──────────────────────────────────────────────────────────

    def execute(
        self,
        plan: ExecutionPlan,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> list[dict[str, Any]]:
        """Execute all steps in *plan* sequentially with stateful lifecycle management.

        Parameters
        ----------
        plan:
            An :class:`~agentic.schemas.ExecutionPlan` produced by the planner.
        progress_callback:
            Optional callable that receives human-readable progress strings for
            real-time UI streaming (e.g. to the web socket).

        Returns
        -------
        list[dict]
            One dictionary per step, each being the result of
            :meth:`~execution.schemas.ExecutionResult.to_dict` augmented with
            ``state``, ``attempts``, and ``recovery_used`` fields.
        """
        self._prepare_cursor()

        ctx = ExecutionContext.from_plan(plan)

        def _emit(msg: str) -> None:
            if progress_callback:
                progress_callback(msg)

        results: list[dict[str, Any]] = []

        for record in ctx.records:
            ctx.current_index = record.step_index
            step = plan.steps[record.step_index]

            # ── Log prerequisite label for UX ───────────────────────────
            if record.requires:
                _emit(f"⏳ Requires: {record.requires}")
                logger.debug(f"[EXECUTOR] Step {record.step_index}: requires '{record.requires}'")

            _emit(f"▶ Running: {step.tool}")

            # ── Run the full step lifecycle ─────────────────────────────
            result = self._run_step_lifecycle(record, step, ctx, _emit)

            # ── Handle confirmation gate ────────────────────────────────
            if result.requires_confirmation:
                logger.info("[EXECUTOR] Confirmation gate triggered for %s: %s", step.tool, result.message)
                _emit(f"🔒 Confirmation required: {result.message}")
                remaining_steps = plan.steps[record.step_index:]
                remaining_plan_dict = {
                    "intent": getattr(plan, "intent", "open_resource"),
                    "steps": [{"tool": s.tool, "args": s.args} for s in remaining_steps],
                }
                from agentic.memory.pending_action import PendingActionManager
                confirmation_id = PendingActionManager.save(remaining_plan_dict)
                result.confirmation_id = confirmation_id

                from agentic.memory.session_state import get_session
                session = get_session()
                if session.pending_action:
                    session.pending_action["id"] = confirmation_id

                results.append(result.to_dict())
                logger.info("[EXECUTOR] Pausing execution for confirmation (id=%s)", confirmation_id)
                break  # pause execution; resume after user confirms

            # ── Handle interactive wait gate ──────────────────────────────
            if result.requires_interaction:
                logger.info("[EXECUTOR] Interaction gate triggered for %s: %s", step.tool, result.message)
                _emit(f"⏸ Pending Interactive Action: {result.message}")
                results.append(result.to_dict())
                logger.info("[EXECUTOR] Pausing execution for user interaction")
                break  # pause execution; wait for follow-up user command

            # ── Emit outcome message ────────────────────────────────────
            if record.status == StepStatus.SUCCESS:
                _emit(f"✓ {step.tool} completed")
            elif record.status == StepStatus.FAILURE:
                _emit(f"✗ {step.tool} failed: {record.error_message}")

            results.append(result.to_dict())

            # ── Halt remaining steps on failure ─────────────────────────
            if record.status == StepStatus.FAILURE:
                logger.warning(
                    f"[EXECUTOR] Plan halted at step {record.step_index} ({step.tool}): "
                    f"{record.error_message}"
                )
                break

        return results

    def execute_step(
        self,
        step: ActionStep,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> ExecutionResult:
        """Execute a single step outside of the full plan lifecycle.

        This method is preserved for backward compatibility with callers that
        run individual steps (e.g. the confirmation-resume flow, tests).  It
        does **not** go through the WAITING / VERIFYING phases.

        Parameters
        ----------
        step:
            The :class:`~agentic.schemas.ActionStep` to execute.
        progress_callback:
            Optional progress callback.

        Returns
        -------
        ExecutionResult
        """
        logger.debug("[EXECUTOR] Executing single step: %s with args %s", step.tool, step.args)

        def _cb(msg: str) -> None:
            if progress_callback:
                progress_callback(msg)

        handler = get_handler(step.tool)
        tool_found = handler is not None
        _cb(f"Dispatching {step.tool}")

        # 1. Permission check
        if not getattr(self, "bypass_confirmation", False) and PermissionManager.requires_confirmation(step.tool, step.args):
            logger.warning(f"Confirmation required for tool {step.tool}")
            message = PermissionManager.build_confirmation_message(step.tool, step.args)
            _cb(f"Confirmation required for {step.tool}")

            from agentic.memory.session_state import get_session
            confirmation_id = get_session().set_pending_action(step.tool, step.args, message)

            return ExecutionResult(
                success=False,
                tool=step.tool,
                message=message,
                requires_confirmation=True,
                confirmation_id=confirmation_id,
                state="pending_confirmation",
            )

        # 2. Registry lookup
        if not tool_found:
            return ExecutionResult(
                success=False,
                tool=step.tool,
                message=f"Tool '{step.tool}' is not supported or unregistered.",
                state="failure",
            )

        # 3. Execute
        try:
            logger.info("[PIPELINE][DISPATCH] Calling handler: tool=%s  args=%s", step.tool, step.args)
            with ExecutionTimer() as timer:
                result = handler(step.args)
            if not result.tool:
                result.tool = step.tool
            result.execution_time_ms = timer.elapsed_ms
            result_str = "success" if result.success else "failure"
            logger.info("[PIPELINE][DISPATCH] Result: tool=%s  status=%s  elapsed_ms=%d  msg=%r",
                        step.tool, result_str, timer.elapsed_ms, result.message)
            if result.message:
                _cb(result.message)
            return result
        except Exception as exc:
            logger.exception(f"Unhandled exception in handler for {step.tool}")
            _cb(f"Handler error: {exc}")
            return ExecutionResult(
                success=False,
                tool=step.tool,
                message=f"Internal handler error: {exc}",
                state="failure",
            )

    # ── Private lifecycle helpers ───────────────────────────────────────────

    def _run_step_lifecycle(
        self,
        record: StepRecord,
        step: ActionStep,
        ctx: ExecutionContext,
        emit: Callable[[str], None],
    ) -> ExecutionResult:
        """Drive a single step through its full lifecycle.

        Covers: EXECUTING → WAITING → VERIFYING → SUCCESS | (RECOVERY → RETRY) × N → FAILURE

        Parameters
        ----------
        record:
            The mutable :class:`~execution.step_state.StepRecord` for this step.
        step:
            The immutable :class:`~agentic.schemas.ActionStep` definition.
        ctx:
            The plan-level :class:`~execution.step_state.ExecutionContext`.
        emit:
            Progress callback wrapper.

        Returns
        -------
        ExecutionResult
            The final result (with lifecycle fields populated).
        """
        # ── Phase 1: EXECUTING ──────────────────────────────────────────
        record.mark_executing()
        emit(f"  → Executing {step.tool}…")
        result = self.execute_step(step, progress_callback=emit)
        record.result = result

        # Bubble up confirmation requests immediately
        if result.requires_confirmation:
            return result

        # ── Phase 2: WAITING ────────────────────────────────────────────
        if record.wait_for and result.success:
            record.mark_waiting()
            emit(f"  ⏳ Waiting: {record.wait_for} (timeout={record.timeout or 'default'}s)…")
            wait_result: WaitResult = dispatch_wait(
                record.wait_for, step.args, result, record.timeout
            )
            record.metadata["wait_result"] = {
                "success": wait_result.success,
                "elapsed_ms": wait_result.elapsed_ms,
                "message": wait_result.message,
            }
            if not wait_result.success:
                emit(f"  ⚠ Wait failed: {wait_result.message}")
                logger.warning(f"[EXECUTOR] Wait failed for step {record.step_index}: {wait_result.message}")
                # Treat wait failure the same as execution failure → recovery
                result = ExecutionResult(
                    success=False,
                    tool=step.tool,
                    message=f"Wait failed: {wait_result.message}",
                    state="waiting_failed",
                )
                record.result = result
            else:
                emit(f"  ✓ Wait satisfied ({wait_result.elapsed_ms} ms)")

        # ── Phase 3: VERIFYING + optional RECOVERY loop ─────────────────
        return self._verify_and_recover(record, step, ctx, emit, result)

    def _verify_and_recover(
        self,
        record: StepRecord,
        step: ActionStep,
        ctx: ExecutionContext,
        emit: Callable[[str], None],
        result: ExecutionResult,
    ) -> ExecutionResult:
        """Verify the step outcome; attempt recovery and retry on failure.

        Parameters
        ----------
        record, step, ctx, emit:
            Passed through from :meth:`_run_step_lifecycle`.
        result:
            The result from the execution (or the failing wait result).

        Returns
        -------
        ExecutionResult
            Final result after verification (and any recovery attempts).
        """
        while True:
            # ── VERIFYING ───────────────────────────────────────────────
            record.mark_verifying()
            emit(f"  ⏳ Verifying {step.tool}…")
            verify_result: VerifyResult = dispatch_verify(step.tool, step.args, result)
            record.metadata["verify_result"] = {
                "passed": verify_result.passed,
                "message": verify_result.message,
            }

            if verify_result.passed:
                # SUCCESS path
                result.state = StepStatus.SUCCESS.value
                result.attempts = record.attempts
                record.mark_success(result)
                emit(f"  ✓ Verified: {verify_result.message}")
                return result

            # Verification failed
            emit(f"  ✗ Verification failed: {verify_result.message}")
            logger.info(
                f"[EXECUTOR] Step {record.step_index} verification failed "
                f"(attempt {record.attempts}): {verify_result.message}"
            )

            # Check if we can still retry
            if not record.can_retry:
                msg = (
                    f"Step '{step.tool}' failed after {record.attempts} attempt(s). "
                    f"Verification: {verify_result.message}"
                )
                record.mark_failure(msg)
                result.success = False
                result.state = StepStatus.FAILURE.value
                result.attempts = record.attempts
                result.message = msg
                emit(f"  ✗ Max retries reached. Giving up.")
                return result

            # ── RECOVERY ────────────────────────────────────────────────
            record.mark_recovery()
            emit(f"  🔧 Attempting recovery (attempt {record.attempts}/{record.max_retries})…")
            recovery_result: RecoveryResult = recover_step(record, ctx)
            record.metadata.setdefault("recovery_attempts", []).append({
                "strategy": recovery_result.strategy_used,
                "succeeded": recovery_result.succeeded,
                "message": recovery_result.message,
            })

            if not recovery_result.succeeded:
                emit(f"  ✗ Recovery failed: {recovery_result.message}")
                # Don't give up yet if we still have retry budget from a different strategy
                # — fall through to increment attempts and try the full execute again

            else:
                emit(f"  ✓ Recovery: {recovery_result.strategy_used}")

            # ── RETRY ────────────────────────────────────────────────────
            record.mark_retry()
            emit(f"  ↺ Retrying {step.tool} (attempt {record.attempts})…")
            result = self.execute_step(step, progress_callback=emit)
            record.result = result
            result.recovery_used = True

            # Run wait phase again for the retry if wait_for is set
            if record.wait_for and result.success:
                record.mark_waiting()
                emit(f"  ⏳ Re-waiting: {record.wait_for}…")
                wait_result = dispatch_wait(record.wait_for, step.args, result, record.timeout)
                if not wait_result.success:
                    emit(f"  ⚠ Wait failed on retry: {wait_result.message}")
                    result = ExecutionResult(
                        success=False,
                        tool=step.tool,
                        message=f"Wait failed on retry: {wait_result.message}",
                        state="waiting_failed",
                        recovery_used=True,
                    )
                    record.result = result

            # Loop back to VERIFYING for the retry result

    # ── Cursor / environment preparation ───────────────────────────────────

    @staticmethod
    def _prepare_cursor() -> None:
        """Move the mouse cursor to a safe position and disable pyautogui fail-safe.

        Prevents the (0, 0) corner fail-safe from triggering when the executor
        runs in headless or remote-desktop environments.
        """
        try:
            import pyautogui
            pyautogui.FAILSAFE = False
        except Exception:
            pass

        try:
            if sys.platform.startswith("win"):
                import ctypes
                ctypes.windll.user32.SetCursorPos(500, 500)
            else:
                import pyautogui
                if pyautogui:
                    x, y = pyautogui.position()
                    if x == 0 and y == 0:
                        pyautogui.moveTo(500, 500)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Backward-compatibility alias
# ---------------------------------------------------------------------------

#: Alias so existing code that imports ``SystemExecutor`` continues to work.
SystemExecutor = DesktopExecutor
