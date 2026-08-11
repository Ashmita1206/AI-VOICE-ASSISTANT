"""
Recovery Engine
===============

Structured, per-strategy recovery system for the stateful execution engine.

When a step's verification fails, the executor calls :func:`recover_step`, which
analyses the failure context and applies the most appropriate recovery strategy.
Recovery strategies are tried in priority order; the first that succeeds stops the
chain.

Key design principles
---------------------
* **No infinite loops** — each strategy is attempted at most once per recovery call.
  The ``max_retries`` field on :class:`~execution.step_state.StepRecord` controls
  how many recovery-retry cycles are allowed in total.
* **Graceful degradation** — if a strategy fails or is unavailable (e.g. win32 not
  installed), the engine logs a warning and falls through to the next strategy.
* **Debug artefacts** — a screenshot is captured on every recovery call so the
  developer can inspect what the screen looked like when the failure occurred.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from execution.step_state import StepRecord, ExecutionContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

@dataclass
class RecoveryResult:
    """Outcome of a recovery attempt.

    Attributes
    ----------
    succeeded:
        True if the recovery action successfully resolved the problem.
    strategy_used:
        Human-readable name of the strategy that was applied.
    message:
        Details of what happened during recovery.
    """
    succeeded: bool
    strategy_used: str = "none"
    message: str = ""


# ---------------------------------------------------------------------------
# Individual recovery strategies
# ---------------------------------------------------------------------------

def capture_recovery_screenshot(step_index: int) -> str | None:
    """Take a debug screenshot and return the saved file path.

    Parameters
    ----------
    step_index:
        Zero-based index of the failing step (embedded in the filename).

    Returns
    -------
    str or None
        Path to the saved screenshot, or None if capture failed.
    """
    try:
        import pyautogui
        os.makedirs("data", exist_ok=True)
        path = os.path.join("data", f"recovery_step{step_index}_{int(time.time())}.png")
        pyautogui.screenshot(path)
        logger.info(f"[RECOVERY] Debug screenshot saved: {path}")
        return path
    except Exception as exc:
        logger.debug(f"[RECOVERY] Screenshot capture failed: {exc}")
        return None


def bring_to_foreground(app_name: str) -> RecoveryResult:
    """Bring an existing application window to the foreground.

    Parameters
    ----------
    app_name:
        Application name fragment to search for among visible windows.

    Returns
    -------
    RecoveryResult
    """
    try:
        import win32gui
        import win32con
        import win32process
        import psutil
    except ImportError:
        return RecoveryResult(
            succeeded=False,
            strategy_used="bring_to_foreground",
            message="win32 or psutil not available."
        )

    # Enumerate visible windows matching the app name
    found_hwnds: list[int] = []
    fragment = app_name.lower().strip()

    def _enum_cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd).lower()
            if fragment in title:
                found_hwnds.append(hwnd)
        return True

    try:
        win32gui.EnumWindows(_enum_cb, None)
    except Exception as exc:
        logger.debug(f"[RECOVERY] EnumWindows error: {exc}")

    if not found_hwnds:
        # Try process-based foreground raise
        try:
            for proc in psutil.process_iter(attrs=["pid", "name"]):
                p_name = (proc.info.get("name") or "").lower()
                p_clean = p_name[:-4] if p_name.endswith(".exe") else p_name
                if fragment in p_clean or p_clean in fragment:
                    from automation.applications import bring_process_to_foreground
                    ok = bring_process_to_foreground(proc.info["pid"])
                    if ok:
                        return RecoveryResult(
                            succeeded=True,
                            strategy_used="bring_to_foreground",
                            message=f"Brought process '{p_name}' to foreground."
                        )
        except Exception as exc:
            logger.debug(f"[RECOVERY] Process foreground raise failed: {exc}")

        return RecoveryResult(
            succeeded=False,
            strategy_used="bring_to_foreground",
            message=f"No visible window found for '{app_name}'."
        )

    hwnd = found_hwnds[0]
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        else:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.SetForegroundWindow(hwnd)
        logger.info(f"[RECOVERY] Brought '{app_name}' window to foreground.")
        return RecoveryResult(
            succeeded=True,
            strategy_used="bring_to_foreground",
            message=f"Brought '{app_name}' to foreground."
        )
    except Exception as exc:
        return RecoveryResult(
            succeeded=False,
            strategy_used="bring_to_foreground",
            message=f"SetForegroundWindow failed for '{app_name}': {exc}"
        )


def restore_minimized_window(app_name: str) -> RecoveryResult:
    """Restore a minimized window for *app_name*.

    Parameters
    ----------
    app_name:
        Application name fragment.

    Returns
    -------
    RecoveryResult
    """
    try:
        import win32gui
        import win32con
    except ImportError:
        return RecoveryResult(
            succeeded=False,
            strategy_used="restore_minimized_window",
            message="win32gui not available."
        )

    fragment = app_name.lower().strip()
    restored = False

    def _enum_cb(hwnd, _):
        nonlocal restored
        if win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
            title = win32gui.GetWindowText(hwnd).lower()
            if fragment in title and win32gui.IsIconic(hwnd):
                try:
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    win32gui.SetForegroundWindow(hwnd)
                    restored = True
                except Exception:
                    pass
        return True

    try:
        win32gui.EnumWindows(_enum_cb, None)
    except Exception as exc:
        logger.debug(f"[RECOVERY] restore_minimized EnumWindows error: {exc}")

    if restored:
        logger.info(f"[RECOVERY] Restored minimized window for '{app_name}'.")
        return RecoveryResult(
            succeeded=True,
            strategy_used="restore_minimized_window",
            message=f"Restored minimized window for '{app_name}'."
        )
    return RecoveryResult(
        succeeded=False,
        strategy_used="restore_minimized_window",
        message=f"No minimized window found for '{app_name}'."
    )


def relaunch_application(app_name: str) -> RecoveryResult:
    """Attempt to re-launch an application that failed to start.

    Parameters
    ----------
    app_name:
        Application name to re-launch.

    Returns
    -------
    RecoveryResult
    """
    try:
        from automation.applications import launch_application
        from execution.schemas import ExecutionResult

        res: ExecutionResult = launch_application({"application": app_name})
        if res.success:
            logger.info(f"[RECOVERY] Re-launched '{app_name}' successfully.")
            return RecoveryResult(
                succeeded=True,
                strategy_used="relaunch_application",
                message=f"Re-launched '{app_name}': {res.message}"
            )
        return RecoveryResult(
            succeeded=False,
            strategy_used="relaunch_application",
            message=f"Re-launch of '{app_name}' failed: {res.message}"
        )
    except Exception as exc:
        return RecoveryResult(
            succeeded=False,
            strategy_used="relaunch_application",
            message=f"Exception during re-launch of '{app_name}': {exc}"
        )


def retry_automation(step_record: "StepRecord") -> RecoveryResult:
    """Re-execute the automation tool from a step record without re-entering the full lifecycle.

    This is a last-resort retry for non-launch tools (e.g. ``type_text``, ``click``)
    that failed transiently.

    Parameters
    ----------
    step_record:
        The failing :class:`~execution.step_state.StepRecord`.

    Returns
    -------
    RecoveryResult
    """
    from execution.registry import get_handler

    handler = get_handler(step_record.tool)
    if handler is None:
        return RecoveryResult(
            succeeded=False,
            strategy_used="retry_automation",
            message=f"No handler registered for '{step_record.tool}'; cannot retry."
        )

    try:
        result = handler(step_record.args)
        if result.success:
            return RecoveryResult(
                succeeded=True,
                strategy_used="retry_automation",
                message=f"Retry of '{step_record.tool}' succeeded."
            )
        return RecoveryResult(
            succeeded=False,
            strategy_used="retry_automation",
            message=f"Retry of '{step_record.tool}' still failed: {result.message}"
        )
    except Exception as exc:
        return RecoveryResult(
            succeeded=False,
            strategy_used="retry_automation",
            message=f"Exception during retry of '{step_record.tool}': {exc}"
        )


# ---------------------------------------------------------------------------
# Main recovery dispatcher
# ---------------------------------------------------------------------------

def recover_step(
    step_record: "StepRecord",
    context: "ExecutionContext",
) -> RecoveryResult:
    """Select and apply the most appropriate recovery strategy for a failing step.

    Strategy selection is based on the tool name and failure context:

    1. **capture_recovery_screenshot** — always first (debug artefact).
    2. **restore_minimized_window** — if the app window is minimized.
    3. **bring_to_foreground** — if the window exists but isn't active.
    4. **relaunch_application** — if the process isn't running at all.
    5. **retry_automation** — for non-launch transient failures.

    Parameters
    ----------
    step_record:
        The :class:`~execution.step_state.StepRecord` that failed verification.
    context:
        The plan-level :class:`~execution.step_state.ExecutionContext`.

    Returns
    -------
    RecoveryResult
        The outcome of the best-matching recovery strategy.
    """
    tool = step_record.tool
    args = step_record.args

    # Resolve the target app name from common arg keys
    app_name = (
        args.get("application")
        or args.get("app")
        or args.get("target")
        or ""
    ).lower().strip()

    # If no app name in current step, look backwards through context for the
    # most recent step that launched an application.
    if not app_name:
        for prev in reversed(context.records[:step_record.step_index]):
            prev_app = (
                prev.args.get("application")
                or prev.args.get("app")
                or prev.args.get("target")
                or ""
            ).strip()
            if prev_app:
                app_name = prev_app.lower()
                logger.debug(f"[RECOVERY] Inferred app_name='{app_name}' from step {prev.step_index}.")
                break

    logger.info(
        f"[RECOVERY] Starting recovery for step {step_record.step_index} "
        f"(tool='{tool}', app='{app_name}', attempt={step_record.attempts})."
    )

    # 1. Always capture a screenshot for debugging
    screenshot_path = capture_recovery_screenshot(step_record.step_index)
    if screenshot_path:
        step_record.metadata["recovery_screenshot"] = screenshot_path

    # 2. For application-launch steps, try focus/restore first, then relaunch only if
    #    the process is genuinely not running (prevents duplicate-instance spawning).
    if tool in ("open_application", "launch_application", "resolve_and_open") and app_name:
        # 2a. Try to restore a minimized window first
        result = restore_minimized_window(app_name)
        if result.succeeded:
            return result

        # 2b. Try to bring the window to foreground
        result = bring_to_foreground(app_name)
        if result.succeeded:
            time.sleep(0.3)
            return result

        # 2c. Only relaunch if the process is confirmed NOT running
        process_running = False
        try:
            import psutil
            from automation.applications import clean_query_for_matching, resolve_canonical_app, CANONICAL_ALIASES
            cleaned = clean_query_for_matching(app_name)
            canonical = resolve_canonical_app(cleaned)
            search_terms = {app_name.lower(), cleaned.lower()}
            if canonical:
                search_terms.add(canonical.lower())
            if canonical in CANONICAL_ALIASES:
                for alias in CANONICAL_ALIASES[canonical]:
                    search_terms.add(alias.lower())

            for proc in psutil.process_iter(attrs=["name"]):
                p_name = (proc.info.get("name") or "").lower()
                p_clean = p_name[:-4] if p_name.endswith(".exe") else p_name
                if p_clean:
                    for st in search_terms:
                        if st in p_clean or p_clean in st:
                            process_running = True
                            break
                if process_running:
                    break
        except Exception:
            pass

        if not process_running:
            logger.info(f"[RECOVERY] Process '{app_name}' not found; relaunching.")
            result = relaunch_application(app_name)
            if result.succeeded:
                from execution.wait_utils import wait_until_process_running
                wait_until_process_running(app_name, timeout=10.0)
                return result
        else:
            logger.info(
                f"[RECOVERY] Process '{app_name}' IS running — skipping relaunch to prevent duplicate instance. "
                "Focus strategies already attempted above."
            )
            # Return a partial success so the verifier can re-check visibility
            return RecoveryResult(
                succeeded=True,
                strategy_used="process_already_running",
                message=f"Process '{app_name}' is already running; window focus was attempted."
            )

        return RecoveryResult(
            succeeded=False,
            strategy_used="all_launch_strategies_exhausted",
            message=f"Could not focus or relaunch '{app_name}'."
        )

    # 3. For non-launch tools: try to restore minimized window
    if app_name:
        result = restore_minimized_window(app_name)
        if result.succeeded:
            return result

    # 4. Try to bring window to foreground
    if app_name:
        result = bring_to_foreground(app_name)
        if result.succeeded:
            # Give focus action a moment to register
            time.sleep(0.3)
            return result

    # 5. Fallback: retry the automation directly
    if tool not in ("open_application", "launch_application", "resolve_and_open"):
        result = retry_automation(step_record)
        if result.succeeded:
            return result

    return RecoveryResult(
        succeeded=False,
        strategy_used="all_strategies_exhausted",
        message=(
            f"All recovery strategies failed for step {step_record.step_index} "
            f"(tool='{tool}', app='{app_name}')."
        )
    )
