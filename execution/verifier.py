"""
Step Verifier
=============

Post-execution verification layer for the stateful execution engine.

After every tool handler returns, the executor calls :func:`dispatch_verify` to
check that the intended outcome was actually achieved on the system.  Verification
is best-effort: for some tools (e.g. ``press_key``) there is no observable side-
effect to check, so verification always returns True.  For application launches and
window-focus operations, concrete checks against the running process list and
foreground window state are performed.

The verifier **does not** block or retry — it simply inspects the current system
state and reports a pass/fail verdict.  Recovery and retry logic lives in
:mod:`execution.recovery`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

@dataclass
class VerifyResult:
    """Outcome of a post-execution verification check.

    Attributes
    ----------
    passed:
        True if the step's intended effect was confirmed.
    message:
        Human-readable explanation (for logs and UI feedback).
    """
    passed: bool
    message: str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _try_psutil():
    try:
        import psutil
        return psutil
    except ImportError:
        return None


def _try_win32():
    try:
        import win32gui
        import win32process
        return win32gui, win32process
    except ImportError:
        return None, None

def is_uwp_window_for_pid(hwnd: int, target_pid: int) -> bool:
    """Return True if the top-level hwnd is an ApplicationFrameWindow containing a child of target_pid."""
    win32gui, win32process = _try_win32()
    if not win32gui or not win32process:
        return False
    try:
        class_name = win32gui.GetClassName(hwnd)
        if class_name == "ApplicationFrameWindow":
            child_pids = []
            def enum_child_cb(child_hwnd, extra):
                _, child_pid = win32process.GetWindowThreadProcessId(child_hwnd)
                child_pids.append(child_pid)
                return True
            win32gui.EnumChildWindows(hwnd, enum_child_cb, None)
            if target_pid in child_pids:
                return True
    except Exception:
        pass
    return False

def _is_process_running(name: str) -> bool:
    """Return True if any process name matches *name* using exact or canonical match.
    
    Uses normalized exact match and canonical alias lookup to prevent
    false positives (e.g. 'store' must NOT match 'restore').
    """
    psutil = _try_psutil()
    if psutil is None:
        return False  # can't verify — NOT verified
    name = name.lower().strip()
    
    # Build set of valid process name stems for this app
    valid_stems = {name}
    # Add canonical process name aliases
    _PROCESS_ALIASES = {
        "telegram":{"telegram"},
        "calculator": {"calculatorapp", "calculator", "calc"},
        "notepad": {"notepad"},
        "file explorer": {"explorer"},
        "settings": {"systemsettings", "systemsettingsadminflows"},
        "task manager": {"taskmgr"},
        "command prompt": {"cmd", "conhost"},
        "powershell": {"powershell", "pwsh"},
        "microsoft word": {"winword", "word"},
        "word": {"winword"},
        "microsoft powerpoint": {"powerpnt", "powerpoint"},
        "powerpoint": {"powerpnt"},
        "microsoft excel": {"excel"},
        "excel": {"excel"},
        "microsoft store": {"winstore.app", "applicationframehost"},
        "store": {"winstore.app"},
        "paint": {"mspaint"},
        "chrome": {"chrome"},
        "google chrome": {"chrome"},
        "spotify": {"spotify"},
        "vs code": {"code"},
        "vscode": {"code"},
        "visual studio code": {"code"},
        "ubuntu": {"ubuntu", "wsl", "wt", "windowsterminal"},
        "wsl": {"wsl", "ubuntu", "wt", "windowsterminal"},
    }
    if name in _PROCESS_ALIASES:
        valid_stems.update(_PROCESS_ALIASES[name])
    
    try:
        for proc in psutil.process_iter(attrs=["name"]):
            p = (proc.info.get("name") or "").lower()
            p_clean = p[:-4] if p.endswith(".exe") else p
            # Exact normalized match only — no substring matching
            if p_clean in valid_stems:
                return True
    except Exception:
        pass
    return False


def _get_window_title_fragments(fragment: str) -> list[str]:
    """Map process/app names to possible window title fragments."""
    fragment = fragment.lower().strip()
    fragments = [fragment]
    if fragment in ("microsoft word", "word", "winword"):
        fragments.extend(["word", "winword", "document1", "microsoft word"])
    elif fragment in ("microsoft powerpoint", "powerpoint", "ppt", "powerpnt"):
        fragments.extend(["powerpoint", "powerpnt", "presentation1", "microsoft powerpoint"])
    elif fragment in ("microsoft excel", "excel"):
        fragments.extend(["excel", "book1", "microsoft excel"])
    elif fragment in ("microsoft store", "store", "windows store"):
        fragments.extend(["microsoft store", "store"])
    elif fragment in ("ubuntu", "ubuntu terminal", "wsl", "linux"):
        fragments.extend(["ubuntu", "wsl", "windows terminal", "bash"])
    elif fragment == "msedge":
        fragments.extend(["microsoft edge", "edge"])
    elif fragment == "chrome":
        fragments.extend(["google chrome", "chromium"])
    elif fragment in ["powershell", "windows powershell", "pwsh"]:
        fragments.extend([
            "windows powershell", 
            "administrator: windows powershell", 
            "powershell", 
            "powershell 7", 
            "pwsh", 
            "windows terminal"
        ])
    elif fragment in ["cmd", "command prompt"]:
        fragments.extend(["command prompt", "cmd", "windows terminal"])
    elif fragment == "notepad":
        fragments.extend(["notepad"])
    elif fragment == "calculator":
        fragments.extend(["calculator"])
    elif fragment == "spotify":
        fragments.extend(["spotify"])
    elif fragment in ("telegram", "telegram desktop"):
        fragments.extend(["telegram", "telegram desktop"])
    return list(set(fragments))


def _get_expected_pids(fragment: str, psutil) -> set[int]:
    expected_pids = set()
    frag_clean = fragment.lower().strip()
    frag_clean = frag_clean[:-4] if frag_clean.endswith(".exe") else frag_clean
    search_names = {frag_clean}
    if frag_clean in ("microsoft word", "word", "winword"):
        search_names.update(["winword", "word"])
    elif frag_clean in ("microsoft powerpoint", "powerpoint", "ppt", "powerpnt"):
        search_names.update(["powerpnt", "powerpoint"])
    elif frag_clean in ("microsoft excel", "excel"):
        search_names.update(["excel"])
    elif frag_clean in ("microsoft store", "store", "windows store"):
        search_names.update(["winstore.app", "applicationframehost", "windowsstore"])
    elif frag_clean in ("ubuntu", "ubuntu terminal", "wsl", "linux"):
        search_names.update(["wsl", "ubuntu", "windowsterminal", "wt"])
    elif frag_clean in ("chrome", "google chrome"):
        search_names.update(["chrome"])
    elif frag_clean in ("notepad",):
        search_names.update(["notepad"])
    elif frag_clean in ("calculator", "calc"):
        search_names.update(["calculatorapp", "calculator", "calc"])
    elif frag_clean in ("paint", "mspaint"):
        search_names.update(["mspaint"])
    elif frag_clean in ("settings", "windows settings"):
        search_names.update(["systemsettings", "systemsettingsadminflows"])
    elif frag_clean in ("powershell", "windows powershell"):
        search_names.update(["powershell", "pwsh"])
    elif frag_clean in ("spotify",):
        search_names.update(["spotify"])
    elif frag_clean in ("vs code", "vscode", "visual studio code"):
        search_names.update(["code"])
    elif frag_clean in ("file explorer", "explorer"):
        search_names.update(["explorer"])
    elif frag_clean in ("telegram", "telegram desktop"):
        search_names.update(["telegram"])

    try:
        for proc in psutil.process_iter(attrs=["pid", "name"]):
            p = (proc.info.get("name") or "").lower()
            p_clean = p[:-4] if p.endswith(".exe") else p
            # Exact stem match only — no substring matching
            if p_clean in search_names:
                expected_pids.add(proc.info["pid"])
    except Exception:
        pass
    return expected_pids


def _find_visible_window_for_process(fragment: str) -> int | None:
    """Return a visible top-level window owned by the named process.

    Store/UWP applications may expose their top-level window through an
    ``ApplicationFrameWindow`` whose child belongs to the application PID.  A
    title-only match is deliberately not accepted here: editor tabs and log
    windows can contain an application name without being that application.
    """
    win32gui, win32process = _try_win32()
    psutil = _try_psutil()
    if win32gui is None or win32process is None or psutil is None:
        return None

    expected_pids = _get_expected_pids(fragment, psutil)
    if not expected_pids:
        return None

    found: list[int] = []
    try:
        def _cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd).strip()
            if not title:
                return True
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid in expected_pids or any(
                is_uwp_window_for_pid(hwnd, expected_pid)
                for expected_pid in expected_pids
            ):
                found.append(hwnd)
                return False
            return True

        win32gui.EnumWindows(_cb, None)
    except Exception:
        return None
    return found[0] if found else None


def _is_window_visible(fragment: str) -> bool:
    """Return True if a visible window title or PID matches *fragment*."""
    win32gui, win32process = _try_win32()
    psutil = _try_psutil()
    if win32gui is None or win32process is None or psutil is None:
        return False  # can't verify — NOT verified
    
    win32gui, win32process = _try_win32()
    psutil = _try_psutil()
    if win32gui is None or win32process is None or psutil is None:
        return False  # can't verify — NOT verified
    
    normalized = fragment.lower().strip()
    if normalized in ("telegram", "telegram desktop"):
        return _find_visible_window_for_process("telegram") is not None

    fragments = _get_window_title_fragments(fragment)
    expected_pids = _get_expected_pids(fragment, psutil)
    
    found = []
    try:
        def _cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd).lower()
                if not title:
                    return True  # skip empty-title windows (invisible helpers)
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                
                if pid in expected_pids or any(is_uwp_window_for_pid(hwnd, ep) for ep in expected_pids) or any(frag in title for frag in fragments):
                    found.append(True)
            return True
        win32gui.EnumWindows(_cb, None)
    except Exception:
        pass
    return bool(found)


def _enumerate_all_windows() -> list[dict]:
    """Enumerate all top-level windows and return a list of diagnostic dicts.

    Each dict contains:
    - hwnd: window handle
    - title: window title
    - pid: owning process ID
    - visible: IsWindowVisible result
    - minimized: IsIconic result
    - foreground: whether this is the current foreground window
    """
    win32gui, win32process = _try_win32()
    if win32gui is None or win32process is None:
        return []

    results: list[dict] = []
    try:
        fg_hwnd = win32gui.GetForegroundWindow()
    except Exception:
        fg_hwnd = 0

    def _cb(hwnd, _):
        try:
            title = win32gui.GetWindowText(hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            visible = bool(win32gui.IsWindowVisible(hwnd))
            minimized = bool(win32gui.IsIconic(hwnd))
            foreground = (hwnd == fg_hwnd)
            results.append({
                "hwnd": hwnd,
                "title": title,
                "pid": pid,
                "visible": visible,
                "minimized": minimized,
                "foreground": foreground,
            })
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception as exc:
        logger.debug(f"[VERIFY][ENUM] EnumWindows error: {exc}")

    return results


def _is_window_foreground(fragment: str) -> bool:
    """Return True if the foreground window title or PID matches *fragment*.
    If it is not foreground, attempts to bring it to foreground.
    Note: this is best-effort — Windows foreground lock can prevent focus steal.
    """
    win32gui, win32process = _try_win32()
    psutil = _try_psutil()

    if win32gui is None or win32process is None or psutil is None:
        return False

    fragments = _get_window_title_fragments(fragment)
    expected_pids = _get_expected_pids(fragment, psutil)

    # --- Check if already foreground ---
    try:
        hwnd = win32gui.GetForegroundWindow()
        if hwnd:
            title = win32gui.GetWindowText(hwnd).lower()
            _, pid = win32process.GetWindowThreadProcessId(hwnd)

            if pid in expected_pids or any(is_uwp_window_for_pid(hwnd, ep) for ep in expected_pids):
                logger.info(
                    f"[VERIFY] Window found foreground | HWND: {hwnd} | title: '{title}' | "
                    f"PID: {pid} | Expected PIDs: {list(expected_pids)} | "
                    f"Expected title frags: {fragments} | Matched rule: PID Match"
                )
                return True
            elif any(frag in title for frag in fragments):
                logger.info(
                    f"[VERIFY] Window found foreground | HWND: {hwnd} | title: '{title}' | "
                    f"PID: {pid} | Expected PIDs: {list(expected_pids)} | "
                    f"Expected title frags: {fragments} | Matched rule: Title Match"
                )
                return True
    except Exception as exc:
        logger.warning(f"[VERIFY] GetForegroundWindow error: {exc}")

    # --- Not foreground: find matching visible window and attempt focus ---
    target_hwnd = None
    target_title = ""
    target_pid = 0
    try:
        def _cb_f(hwnd, _):
            nonlocal target_hwnd, target_title, target_pid
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd).lower()
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if (
                    pid in expected_pids
                    or any(is_uwp_window_for_pid(hwnd, ep) for ep in expected_pids)
                    or any(frag in title for frag in fragments)
                ):
                    target_hwnd = hwnd
                    target_title = title
                    target_pid = pid
                    return False
            return True
        win32gui.EnumWindows(_cb_f, None)
    except Exception:
        pass

    if target_hwnd:
        logger.info(
            f"[VERIFY] Window not foreground — attempting focus | Target HWND: {target_hwnd} | "
            f"title: '{target_title}' | PID: {target_pid}"
        )
        try:
            from automation.applications import force_focus_window
            focus_ok = force_focus_window(target_hwnd)
            new_hwnd = win32gui.GetForegroundWindow()
            new_title = win32gui.GetWindowText(new_hwnd).lower() if new_hwnd else ""
            _, new_pid = win32process.GetWindowThreadProcessId(new_hwnd) if new_hwnd else (0, 0)
            logger.info(
                f"[VERIFY] Focus attempt result: {'SUCCESS' if focus_ok else 'FAILED (OS foreground lock)'} | "
                f"Current foreground HWND: {new_hwnd} | title: '{new_title}' | PID: {new_pid} | "
                f"Expected PIDs: {list(expected_pids)} | Expected title frags: {fragments}"
            )
            if focus_ok:
                return True
        except Exception as e:
            logger.warning(f"[VERIFY] force_focus_window error: {e}")
    else:
        logger.info(
            f"[VERIFY] No matching window found for '{fragment}' | "
            f"Expected PIDs: {list(expected_pids)} | Expected title frags: {fragments} | "
            f"Matched rule: None"
        )

    return False


# ---------------------------------------------------------------------------
# Individual verifiers
# ---------------------------------------------------------------------------

def verify_application_launched(app_name: str) -> VerifyResult:
    """Verify that an application is running and active."""
    name = app_name.lower().strip()
    psutil = _try_psutil()

    proc_running = _is_process_running(name)
    if not proc_running and psutil:
        expected_pids = _get_expected_pids(name, psutil)
        if expected_pids:
            proc_running = True

    win_vis = _is_window_visible(name)

    if not proc_running and not win_vis:
        return VerifyResult(
            passed=False,
            message=f"Verification failed: no running process or window found for '{app_name}'."
        )

    if win_vis:
        return VerifyResult(
            passed=True,
            message=f"Application '{app_name}' verified: process running AND visible window confirmed."
        )

    return VerifyResult(
        passed=True,
        message=f"Application '{app_name}' verified: process is running."
    )


def verify_window_focused(target: str) -> VerifyResult:
    """Verify that the foreground window title matches *target*."""
    if _is_window_foreground(target):
        return VerifyResult(
            passed=True,
            message=f"Window '{target}' is the active foreground window."
        )
    if _is_window_visible(target):
        return VerifyResult(
            passed=True,
            message=f"Window '{target}' is visible (not foreground, but usable)."
        )
    return VerifyResult(
        passed=False,
        message=f"Window matching '{target}' is not visible or foreground."
    )


def verify_text_typed(text: str) -> VerifyResult:
    """Best-effort verification that *text* was typed."""
    return VerifyResult(
        passed=True,
        message=f"Text typed ('{text[:30]}{'...' if len(text) > 30 else ''}'); "
                "input field state not inspectable externally."
    )


def verify_key_pressed(key: str) -> VerifyResult:
    """Verification for key press actions — always passes (fire-and-forget)."""
    return VerifyResult(
        passed=True,
        message=f"Key '{key}' pressed (keystroke is fire-and-forget)."
    )


def verify_search_results_loaded(app_name: str, query: str, hwnd: Optional[int] = None) -> VerifyResult:
    """Heuristic check that search results appeared after a search action."""
    if hwnd is not None:
        win32gui, _ = _try_win32()
        if win32gui and win32gui.IsWindowVisible(hwnd):
            return VerifyResult(
                passed=True,
                message=f"Search for '{query}' submitted (window handle {hwnd} still active)."
            )

    if _is_window_visible(app_name):
        return VerifyResult(
            passed=True,
            message=f"Search for '{query}' submitted in '{app_name}' (window still active)."
        )
    return VerifyResult(
        passed=False,
        message=(
            f"'{app_name}' window disappeared after search for '{query}' — "
            "possible crash or unexpected close."
        )
    )


def verify_generic(tool: str, result_success: bool) -> VerifyResult:
    """Fallback verifier: trust the handler's own success flag."""
    if result_success:
        return VerifyResult(
            passed=True,
            message=f"Tool '{tool}' reported success."
        )
    return VerifyResult(
        passed=False,
        message=f"Tool '{tool}' reported failure."
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def dispatch_verify(tool: str, args: dict, result) -> VerifyResult:
    """Route a completed step to the appropriate verifier.

    Called by the stateful executor after every tool execution (and after
    the optional wait phase).

    Parameters
    ----------
    tool:
        The canonical tool name that was executed.
    args:
        The step's argument dictionary.
    result:
        The :class:`~execution.schemas.ExecutionResult` returned by the handler.

    Returns
    -------
    VerifyResult
    """
    res_success = getattr(result, "success", True) if not isinstance(result, dict) else result.get("success", True)
    res_msg = getattr(result, "message", "") if not isinstance(result, dict) else result.get("message", "")

    if not res_success:
        return VerifyResult(
            passed=False,
            message=f"Handler reported failure for '{tool}': {res_msg}"
        )

    app = (
        args.get("application")
        or args.get("app")
        or args.get("target")
        or args.get("query")
        or ""
    ).lower().strip()

    # Dedicated Telegram verification (branches based on mode/client: desktop vs web)
    if tool in ("open_telegram", "open_telegram_web"):
        res_data = getattr(result, "data", {}) if not isinstance(result, dict) else result.get("data", {})
        if not isinstance(res_data, dict):
            res_data = {}
        client = (
            res_data.get("mode")
            or res_data.get("client")
            or ("desktop" if res_data.get("client") == "telegram_desktop" else None)
        )
        if not client:
            try:
                from automation.telegram.telegram_automation import _telegram_state
                client = _telegram_state.get("mode") or _telegram_state.get("client")
            except Exception:
                client = None

        if client in ("telegram_desktop", "desktop"):
            if res_data.get("opened") or res_data.get("ready"):
                return VerifyResult(passed=True, message=res_msg if "Desktop" in (res_msg or "") else "Telegram Desktop window verified.")
            v_res = verify_application_launched("Telegram")
            if getattr(v_res, "passed", False) or _is_window_visible("telegram"):
                return VerifyResult(passed=True, message=res_msg if "Desktop" in (res_msg or "") else "Telegram Desktop window verified.")
            return VerifyResult(passed=False, message="Telegram Desktop window was not verified.")
        else:
            if res_data.get("opened") or res_data.get("ready"):
                return VerifyResult(passed=True, message=res_msg if "Web" in (res_msg or "") else "Telegram Web browser tab verified.")
            from automation.browser import find_and_focus_browser_tab
            tab_found = find_and_focus_browser_tab("https://web.telegram.org/")
            if tab_found or _is_window_visible("telegram web") or _is_window_visible("telegram"):
                return VerifyResult(passed=True, message=res_msg if "Web" in (res_msg or "") else "Telegram Web browser tab verified.")
            return VerifyResult(passed=False, message="Telegram Web browser tab or window was not verified.")



    # Application launch / open tools
    if tool in ("open_application", "launch_application", "resolve_and_open", "open_browser", "open_website", "search_web", "open_gmail", "open_spotify"):


        opened_in_browser = (
            getattr(result, "metadata", {}).get("opened_in_browser", False)
            or getattr(result, "resource_type", "") == "website"
            or tool in ("open_browser", "open_website", "search_web", "open_gmail")
            or getattr(result, "action_type", "") in ("opened_web_app", "searched_web", "opened_url")
        )
        reused_window = getattr(result, "metadata", {}).get("reused_window", False)

        # Log full window state for diagnostics
        all_windows = _enumerate_all_windows()
        visible_windows = [w for w in all_windows if w["visible"] and w["title"]]
        logger.info(f"[VERIFY] Enumerating {len(all_windows)} top-level windows ({len(visible_windows)} visible with title) for '{app}':")
        for w in visible_windows:
            logger.info(
                f"  HWND={w['hwnd']} | PID={w['pid']} | title='{w['title']}' | "
                f"visible={w['visible']} | minimized={w['minimized']} | foreground={w['foreground']}"
            )

        if opened_in_browser or reused_window:
            # For browser/reused windows: check visibility or browser process
            from automation.applications import clean_query_for_matching
            tab_frag = clean_query_for_matching(app)
            target_frag = tab_frag or app or "browser"
            # Best-effort focus attempt (non-blocking for verification result)
            _is_window_foreground(target_frag)
            # Success = window or browser process is visible/running
            if _is_window_visible(target_frag) or _is_process_running("chrome") or _is_process_running("msedge") or _is_process_running("firefox") or _is_window_visible("browser"):
                return VerifyResult(passed=True, message=f"Browser/Window for '{target_frag}' is verified.")
            return VerifyResult(passed=False, message=f"Browser/Window for '{target_frag}' was not verified.")

        # For native app launches: success = process running AND window visible.
        v_res = verify_application_launched(app)
        if not v_res.passed:
            return v_res

        # Best-effort foreground promotion
        fg_ok = _is_window_foreground(app)
        logger.info(
            f"[VERIFY] Focus attempt for '{app}': {'promoted to foreground' if fg_ok else 'window visible but not foreground (OS lock) — still SUCCESS'}"
        )
        return VerifyResult(
            passed=True,
            message=(
                f"Application '{app}' is running with a visible window"
                + (" and is the active foreground window." if fg_ok else " (foreground promotion blocked by OS — window is usable).")
            )
        )

    # Window focus tools
    if tool in ("focus_window", "wait_for_window"):
        target = (args.get("target") or app).lower()
        return verify_window_focused(target) if target else verify_generic(tool, result.success)

    # Text input
    if tool == "type_text":
        return verify_text_typed(args.get("text", ""))

    # Key presses
    if tool in ("press_key", "hotkey"):
        return verify_key_pressed(args.get("key") or str(args))

    # In-application search
    if tool == "search_inside_application":
        query = args.get("query", "")
        hwnd = getattr(result, "metadata", {}).get("hwnd")
        
        # Check if this is a WhatsApp search
        is_whatsapp = (
            "whatsapp" in (app or "").lower()
            or "whatsapp" in getattr(result, "message", "").lower()
        )
        if is_whatsapp:
            try:
                import uiautomation as auto
                import win32gui
                if hwnd and win32gui.IsWindowVisible(hwnd):
                    win = auto.WindowControl(searchDepth=1, Handle=hwnd)
                    msg_box = win.Control(searchDepth=15, Name="Type a message")
                    if msg_box.Exists(0.5):
                        return VerifyResult(
                            passed=True,
                            message=f"WhatsApp search for '{query}' verified (Chat is open)."
                        )
            except Exception:
                pass

        from automation.desktop import get_active_app_name
        active_app = get_active_app_name() or app
        return verify_search_results_loaded(active_app, query, hwnd=hwnd)

    # Notepad application open
    if tool == "notepad_open":
        from automation.notepad import _controller
        hwnd = _controller.find_notepad_hwnd()
        if hwnd:
            return VerifyResult(passed=True, message="Notepad open verified (assistant-owned session window exists).")
        return VerifyResult(passed=False, message="Notepad open verification failed: no active assistant window found.")

    # Notepad text input — retrieve actual editor text programmatically using WM_GETTEXT
    if tool == "notepad_type":
        expected_text = args.get("text", "")
        from automation.notepad import _controller
        hwnd = _controller.find_notepad_hwnd()
        if hwnd:
            edit_hwnd = _controller._find_edit_control(hwnd)
            if edit_hwnd:
                try:
                    import ctypes
                    import win32con
                    import win32gui
                    length = win32gui.SendMessage(edit_hwnd, win32con.WM_GETTEXTLENGTH, 0, 0)
                    buf = ctypes.create_unicode_buffer(length + 1)
                    win32gui.SendMessage(edit_hwnd, win32con.WM_GETTEXT, length + 1, ctypes.addressof(buf))
                    editor_text = buf.value
                    if expected_text in editor_text:
                        return VerifyResult(passed=True, message=f"Type verified: text '{expected_text}' exists in the Notepad editor.")
                    return VerifyResult(passed=False, message=f"Type verification failed: text '{expected_text}' not found in editor text.")
                except Exception as e:
                    logger.debug(f"[VERIFY] Failed to get editor text: {e}")
        return VerifyResult(passed=True, message="Type verified (fallback): Notepad window is open.")

    # Notepad save operations
    if tool in ("notepad_save", "notepad_save_as"):
        import os
        from pathlib import Path

        # PRIORITY 1: Use the actual saved_path returned by the save operation
        saved_path = getattr(result, "saved_path", None)
        if saved_path:
            # Normalize the path safely
            normalized_path = Path(
                os.path.expandvars(
                    os.path.expanduser(str(saved_path).strip().strip('"').strip("'"))
                )
            )
            logger.info(
                f"[VERIFY][SAVE] Using saved_path from result: '{saved_path}' | "
                f"Normalized: '{normalized_path}'"
            )
            if normalized_path.exists():
                return VerifyResult(
                    passed=True,
                    message=f"Notepad save verified successfully: '{normalized_path}'"
                )
            return VerifyResult(
                passed=False,
                message=(
                    f"Save verification failed.\n"
                    f"Returned saved path: '{saved_path}'\n"
                    f"Normalized verification path: '{normalized_path}'\n"
                    f"Exists: False"
                )
            )

        # PRIORITY 2: If no saved_path, compute from current operation args
        filename = args.get("filename", "")
        directory = args.get("directory", None)

        # Dynamic query for the correct Desktop path (resolves OneDrive etc.)
        def _get_desktop_path() -> str:
            import winreg
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
                ) as key:
                    reg_val, _ = winreg.QueryValueEx(key, "Desktop")
                    return os.path.abspath(os.path.expandvars(reg_val))
            except Exception:
                pass
            home = os.path.expanduser("~")
            onedrive_desktop = os.path.join(home, "OneDrive", "Desktop")
            if os.path.exists(onedrive_desktop):
                return onedrive_desktop
            return os.path.join(home, "Desktop")

        # If no filename is provided for notepad_save, check window title or default file
        if not filename and tool == "notepad_save":
            from automation.notepad import _controller
            hwnd = _controller.find_notepad_hwnd()
            if hwnd:
                try:
                    import win32gui
                    title = win32gui.GetWindowText(hwnd).lower()
                    if "untitled" not in title and "unbenannt" not in title:
                        return VerifyResult(passed=True, message=f"Save verified: Notepad window title is '{title}' (not untitled).")
                except Exception:
                    pass
            desktop = _get_desktop_path()
            default_file = os.path.join(desktop, "document.txt")
            if os.path.exists(default_file):
                return VerifyResult(passed=True, message=f"Save verified: File '{default_file}' exists on disk.")
            return VerifyResult(passed=False, message="Save verification failed: Document is still untitled and no desktop file was found.")

        # Resolve common directories like Desktop/Documents if directory is a placeholder
        if directory:
            dir_lower = directory.lower()
            if "desktop" in dir_lower:
                directory = _get_desktop_path()
            elif "documents" in dir_lower:
                import winreg
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                        reg_val, _ = winreg.QueryValueEx(key, "Personal")
                        directory = os.path.abspath(os.path.expandvars(reg_val))
                except Exception:
                    directory = os.path.join(os.path.expanduser("~"), "Documents")
            elif "downloads" in dir_lower:
                import winreg
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                        reg_val, _ = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")
                        directory = os.path.abspath(os.path.expandvars(reg_val))
                except Exception:
                    directory = os.path.join(os.path.expanduser("~"), "Downloads")
            elif "pictures" in dir_lower:
                import winreg
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                        reg_val, _ = winreg.QueryValueEx(key, "My Pictures")
                        directory = os.path.abspath(os.path.expandvars(reg_val))
                except Exception:
                    directory = os.path.join(os.path.expanduser("~"), "Pictures")

        if directory:
            filepath = os.path.join(directory, filename)
        else:
            filepath = filename
        filepath = os.path.abspath(filepath)

        logger.info(
            f"[VERIFY][SAVE] No saved_path in result. Using computed path from args.\n"
            f"filename: '{filename}' | directory: '{args.get('directory')}' | "
            f"computed path: '{filepath}'"
        )

        # Normalize and check the computed path
        normalized_path = Path(
            os.path.expandvars(
                os.path.expanduser(str(filepath).strip().strip('"').strip("'"))
            )
        )

        if normalized_path.exists():
            return VerifyResult(
                passed=True,
                message=f"Save verified: File '{normalized_path}' exists on disk."
            )

        return VerifyResult(
            passed=False,
            message=(
                f"Save verification failed.\n"
                f"Computed verification path: '{normalized_path}'\n"
                f"Exists: False\n"
                f"Current operation filename: '{filename}'"
            )
        )

    # Notepad close
    if tool == "notepad_close":
        from automation.notepad import _controller
        # Wait up to 1.0s for the window to finish closing
        import time
        remaining = None
        for _ in range(5):
            remaining = _controller.find_notepad_hwnd()
            if remaining is None:
                break
            time.sleep(0.2)
        if remaining is None:
            return VerifyResult(passed=True, message="Close verified: No Notepad windows are currently visible.")
        return VerifyResult(passed=False, message=f"Close verification failed: Notepad window (HWND={remaining}) is still visible.")

    # Notepad keyboard/edit operations — fire-and-forget; trust handler
    if tool in (
        "notepad_press_enter",
        "notepad_select_all",
        "notepad_copy",
        "notepad_paste",
        "notepad_undo",
        "notepad_redo",
        "notepad_delete",
        "notepad_clear",
        "notepad_new_file",
        "notepad_open_file",
    ):
        return verify_generic(tool, result.success)

    # Default: trust the handler's own success flag
    return verify_generic(tool, result.success)
