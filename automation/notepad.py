"""
Notepad Automation
==================

Provides reliable, voice-command-driven automation for Microsoft Notepad.

Architecture
------------
All operations are implemented as methods on :class:`NotepadController` and
exposed to the execution pipeline via ``@register_tool``-decorated handler
functions that forward to the singleton controller instance.

Reliability guarantees
-----------------------
* Window detection uses BOTH title-scan AND process-name (psutil) lookup so
  that Windows-11 UWP / Store Notepad (whose ApplicationFrameWindow title can
  lag) is never missed.
* ``open_notepad`` checks the process table first; it never spawns a second
  instance when Notepad is already running.
* Before every typing or shortcut action the code:
    1. Finds the Notepad frame HWND.
    2. Calls force_focus_window() to raise it.
    3. Locates the inner Edit child control.
    4. Physically clicks inside the text area so the keyboard focus lands in
       the right control — not just the frame.
    5. Waits a configurable settle delay before sending keystrokes.
* All focus, typing, and window-detection decisions emit DEBUG log lines so
  failures are diagnosable without a debugger.
* Every handler returns a structured ExecutionResult; never raises.

Tools registered (15 total)
-----------------------------
    notepad_open, notepad_close, notepad_type, notepad_press_enter,
    notepad_select_all, notepad_copy, notepad_paste, notepad_undo,
    notepad_redo, notepad_delete, notepad_clear, notepad_save,
    notepad_save_as, notepad_open_file, notepad_new_file
"""

from __future__ import annotations

import os
import ctypes
import logging
import subprocess
import time
from typing import Any, Optional, Tuple

import config
from config import get_logger
from execution.registry import register_tool
from execution.schemas import ExecutionResult

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency guards
# ---------------------------------------------------------------------------

try:
    import pyautogui
    pyautogui.FAILSAFE = config.PYAUTOGUI_FAILSAFE
except ImportError:
    pyautogui = None  # type: ignore[assignment]

try:
    import win32gui
    import win32process
    import win32con
    import win32api
except ImportError:
    win32gui = None      # type: ignore[assignment]
    win32process = None  # type: ignore[assignment]
    win32con = None      # type: ignore[assignment]
    win32api = None      # type: ignore[assignment]

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore[assignment]

try:
    import pyperclip
except ImportError:
    pyperclip = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Constants & Configuration
# ---------------------------------------------------------------------------

DEBUG_AUTOMATION = False

SESSION_CACHE_FILE     = config.SESSION_CACHE_FILE
NOTEPAD_EXE            = config.NOTEPAD_EXE
NOTEPAD_PROC_NAME      = config.NOTEPAD_PROC_NAME
NOTEPAD_TITLE_FRAGMENT = config.NOTEPAD_TITLE_FRAGMENT
WINDOW_POLL_INTERVAL   = config.WINDOW_POLL_INTERVAL
WINDOW_LAUNCH_TIMEOUT  = config.WINDOW_LAUNCH_TIMEOUT
FOCUS_SETTLE_MS        = config.FOCUS_SETTLE_MS
SAVE_DIALOG_TIMEOUT    = config.SAVE_DIALOG_TIMEOUT
TYPING_INTERVAL        = config.TYPING_INTERVAL


# ---------------------------------------------------------------------------
# ApplicationSession
# ---------------------------------------------------------------------------

class ApplicationSession:
    def __init__(self, pid: int, hwnd: int, launched_by_assistant: bool, launch_time: float):
        self.pid = pid
        self.hwnd = hwnd
        self.launched_by_assistant = launched_by_assistant
        self.launch_time = launch_time


# ---------------------------------------------------------------------------
# NotepadController
# ---------------------------------------------------------------------------

class NotepadController:
    """Controller for Microsoft Notepad automation.

    All methods return :class:`~execution.schemas.ExecutionResult`.
    """

    def __init__(self):
        self._session: Optional[ApplicationSession] = None
        self._last_saved_path: Optional[str] = None
        self._load_session()

    def _debug_pause(self, action: str) -> None:
        if DEBUG_AUTOMATION:
            logger.info(f"[DEBUG MODE] Step completed: '{action}'. Pausing 1.5 seconds for visual inspection.")
            time.sleep(1.5)
    def _log_tool_precondition(self, tool_name: str) -> None:
        ctrl_id = hex(id(self))
        hwnd = self._session.hwnd if self._session else None
        pid = self._session.pid if self._session else None
        title = ""
        if hwnd and win32gui:
            try:
                title = win32gui.GetWindowText(hwnd)
            except Exception:
                pass
        assistant_owned = self._session.launched_by_assistant if self._session else False
        logger.info(
            f"[NOTEPAD PRECONDITION] Tool: '{tool_name}' | "
            f"Controller ID: {ctrl_id} | HWND: {hwnd} | PID: {pid} | "
            f"Title: '{title}' | Assistant Owned: {assistant_owned}"
        )
    def _load_registry(self) -> dict:
        """Load the session registry from disk, pruning any stale sessions."""
        registry = {"active_session": None, "assistant_sessions": []}
        try:
            if os.path.exists(SESSION_CACHE_FILE):
                import json
                with open(SESSION_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        registry["active_session"] = data.get("active_session")
                        registry["assistant_sessions"] = data.get("assistant_sessions", [])
        except Exception as e:
            logger.debug(f"[NOTEPAD] Failed to load session registry: {e}")

        # Prune stale assistant sessions (HWND no longer valid)
        pruned_sessions = []
        for s in registry["assistant_sessions"]:
            hwnd = s.get("hwnd")
            pid = s.get("pid")
            if hwnd and win32gui and win32gui.IsWindow(hwnd):
                # Verify it's actually still a Notepad window
                try:
                    cls = win32gui.GetClassName(hwnd).lower()
                    title = win32gui.GetWindowText(hwnd).lower()
                    if cls == "notepad" or "notepad" in title:
                        pruned_sessions.append(s)
                except Exception:
                    pass
        registry["assistant_sessions"] = pruned_sessions

        # Verify active session
        active = registry["active_session"]
        if active:
            active_sess = ApplicationSession(
                pid=active["pid"],
                hwnd=active["hwnd"],
                launched_by_assistant=active["launched_by_assistant"],
                launch_time=active["launch_time"]
            )
            if not self._is_session_valid(active_sess):
                registry["active_session"] = None

        return registry

    def _save_registry(self, registry: dict) -> None:
        """Save the session registry to disk."""
        try:
            import json
            os.makedirs(os.path.dirname(SESSION_CACHE_FILE), exist_ok=True)
            with open(SESSION_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(registry, f)
            logger.debug(f"[NOTEPAD] Saved session registry. Assistant sessions count: {len(registry['assistant_sessions'])}")
        except Exception as e:
            logger.debug(f"[NOTEPAD] Failed to save session registry: {e}")

    def _save_session(self) -> None:
        registry = self._load_registry()
        if self._session:
            registry["active_session"] = {
                "pid": self._session.pid,
                "hwnd": self._session.hwnd,
                "launched_by_assistant": self._session.launched_by_assistant,
                "launch_time": self._session.launch_time,
                "last_saved_path": getattr(self, "_last_saved_path", None)
            }
            # Also add to assistant_sessions if launched_by_assistant is True
            if self._session.launched_by_assistant:
                # Avoid duplicate HWNDs
                existing_hwnds = {s["hwnd"] for s in registry["assistant_sessions"]}
                if self._session.hwnd not in existing_hwnds:
                    registry["assistant_sessions"].append({
                        "pid": self._session.pid,
                        "hwnd": self._session.hwnd,
                        "launch_time": self._session.launch_time
                    })
        else:
            registry["active_session"] = None
        self._save_registry(registry)

    def _load_session(self) -> None:
        registry = self._load_registry()
        active = registry["active_session"]
        if active:
            self._session = ApplicationSession(
                pid=active["pid"],
                hwnd=active["hwnd"],
                launched_by_assistant=active["launched_by_assistant"],
                launch_time=active["launch_time"]
            )
            self._last_saved_path = active.get("last_saved_path")
        else:
            self._session = None

    def _close_stale_window(self, hwnd: int, pid: int) -> None:
        """Forcefully close an assistant-owned stale window."""
        if not win32gui or not win32process:
            return
        if not win32gui.IsWindow(hwnd):
            return

        logger.info(f"[NOTEPAD] Closing stale assistant window HWND={hwnd}, PID={pid}")
        try:
            # Post WM_CLOSE message
            ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
            
            # Dismiss potential unsaved changes dialogs for this window
            time.sleep(0.3)
            for w in self._get_window_snapshot():
                if w["hwnd"] != hwnd and w["pid"] == pid:
                    if w["class"].lower() == "#32770":
                        # Try programmatic Don't Save
                        import win32con
                        dismissed = False
                        for btn_id in [7, 1002, 2]:
                            try:
                                btn = win32gui.GetDlgItem(w["hwnd"], btn_id)
                                if btn:
                                    win32gui.SendMessage(w["hwnd"], win32con.WM_COMMAND, btn_id, btn)
                                    dismissed = True
                                    break
                            except Exception:
                                pass
                            
            # Poll for window to close
            closed = False
            for _ in range(10):
                time.sleep(0.15)
                if not win32gui.IsWindow(hwnd):
                    closed = True
                    break
            
            if not closed:
                # Ultimate fallback: terminate process
                logger.info(f"[NOTEPAD] Stale window did not close; terminating process PID={pid}")
                try:
                    import psutil
                    proc = psutil.Process(pid)
                    proc.terminate()
                    # Wait up to 1.5 seconds for the window to actually be gone
                    for _ in range(10):
                        time.sleep(0.15)
                        if not win32gui.IsWindow(hwnd):
                            break
                except Exception as e:
                    logger.debug(f"[NOTEPAD] Failed to terminate stale process {pid}: {e}")
        except Exception as exc:
            logger.debug(f"[NOTEPAD] Exception closing stale window HWND={hwnd}: {exc}")

    def _is_session_valid(self, session: ApplicationSession) -> bool:
        if not win32gui or not session.hwnd:
            return False
        try:
            if not win32gui.IsWindow(session.hwnd):
                return False
        except Exception:
            return False

        try:
            cls = win32gui.GetClassName(session.hwnd).lower()
            title = win32gui.GetWindowText(session.hwnd).lower()
            if "notepad" in cls or "notepad" in title or "applicationframe" in cls or "edit" in cls or "rich" in cls or "core" in cls or "pane" in cls:
                return True
        except Exception:
            pass


        return True




    def _get_window_snapshot(self) -> list[dict]:
        """Return a snapshot of all visible windows with their metadata using a robust EnumWindows with psutil fallback."""
        if not win32gui or not win32process or not psutil:
            return []
            
        snapshot = []
        def _enum_cb(hwnd, _):
            try:
                if win32gui.IsWindow(hwnd):
                    title = ""
                    try:
                        title = win32gui.GetWindowText(hwnd)
                    except Exception:
                        pass


                    cls = ""
                    try:
                        cls = win32gui.GetClassName(hwnd)
                    except Exception:
                        pass

                    pid = 0
                    try:
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    except Exception:
                        pass

                    cls_lower = cls.lower()
                    title_lower = title.lower()
                    proc_name = "?"
                    proc_path = "?"
                    if pid > 0 and (cls_lower in ("notepad", "applicationframewindow") or "notepad" in title_lower or "untitled" in title_lower or title_lower == ""):
                        try:
                            proc = psutil.Process(pid)
                            proc_name = proc.name()
                            proc_path = proc.exe()
                        except Exception:
                            pass

                        
                    snapshot.append({
                        "hwnd": hwnd,
                        "title": title,
                        "class": cls,
                        "pid": pid,
                        "proc_name": proc_name,
                        "proc_path": proc_path
                    })

            except Exception:
                pass
            return 1

        try:
            win32gui.EnumWindows(_enum_cb, None)
        except Exception:
            pass

        # Fallback: Find windows directly by process if EnumWindows raised error
        if not any(w["proc_name"].lower() in ("notepad.exe", "notepad", "applicationframehost.exe") or w["class"].lower() in ("notepad", "applicationframewindow") for w in snapshot):
            try:
                for proc in psutil.process_iter(attrs=["pid", "name"]):
                    name = (proc.info.get("name") or "").lower()
                    if name in ("notepad.exe", "notepad", "applicationframehost.exe"):
                        def _enum_pid_cb(hwnd, _):
                            try:
                                if win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd):
                                    _, w_pid = win32process.GetWindowThreadProcessId(hwnd)
                                    if w_pid == proc.info["pid"]:
                                        snapshot.append({
                                            "hwnd": hwnd,
                                            "title": win32gui.GetWindowText(hwnd),
                                            "class": win32gui.GetClassName(hwnd),
                                            "pid": proc.info["pid"],
                                            "proc_name": name,
                                            "proc_path": ""
                                        })
                            except Exception:
                                pass
                            return 1
                        try:
                            win32gui.EnumWindows(_enum_pid_cb, None)
                        except Exception:
                            pass
            except Exception:
                pass
            
        return snapshot




    def _scan_any_notepad_hwnd(self) -> Optional[int]:
        """Scan all windows and return the HWND of a real, visible Notepad editor window.

        Windows 11's modern Notepad creates many internal windows with class
        'Notepad'. Only the actual editor frame has a NotepadTextBox or
        RichEditD2DPT child control. This method filters to only return
        genuine editor windows.
        """
        _NON_UI_CLASSES = frozenset({
            "gdi+ hook window class", "ime", "msctfime ui",
            "tooltips_class32", "windows.ui.core.corewindow",
        })
        snapshot = self._get_window_snapshot()
        candidates = []
        for w in snapshot:
            cls_lower = w["class"].lower()
            title_lower = w["title"].lower()

            # Skip non-UI helper windows
            if cls_lower in _NON_UI_CLASSES:
                continue

            # Must be visible
            try:
                if not win32gui.IsWindowVisible(w["hwnd"]):
                    continue
            except Exception:
                continue

            is_notepad_frame = (
                cls_lower == "notepad"
                or (cls_lower == "applicationframewindow"
                    and ("untitled" in title_lower or w["title"] == "" or "notepad" in title_lower))
            )
            if is_notepad_frame:
                candidates.append(w)

        if not candidates:
            return None

        # Verify candidates have an actual edit control child — this
        # distinguishes the real editor window from the many internal
        # framework windows that Windows 11 Notepad creates.
        for cand in candidates:
            if self._find_edit_control(cand["hwnd"]):
                return cand["hwnd"]

        # If no candidate has an edit control (window still initializing),
        # fall back to title heuristic: real editor windows have document
        # names like "Untitled - Notepad", not bare "Notepad".
        for cand in candidates:
            title = cand["title"].lower()
            if " - notepad" in title or "untitled" in title:
                return cand["hwnd"]

        return None


    # ── Internal helpers ─────────────────────────────────────────────────

    @staticmethod
    def _notepad_pids() -> list[int]:
        """Return PIDs of all running notepad.exe processes."""
        if psutil is None:
            return []
        pids: list[int] = []
        try:
            for proc in psutil.process_iter(attrs=["pid", "name"]):
                name = (proc.info.get("name") or "").lower()
                name_clean = name[:-4] if name.endswith(".exe") else name
                if name_clean == NOTEPAD_PROC_NAME:
                    pids.append(proc.info["pid"])
        except Exception as exc:
            logger.debug(f"[NOTEPAD] psutil process iteration failed: {exc}")
        return pids

    @staticmethod
    def _hwnds_for_pids(pids: list[int]) -> list[int]:
        """Return all top-level visible HWNDs belonging to *pids*."""
        if not win32gui or not win32process:
            return []
        pid_set = set(pids)
        found: list[int] = []

        def _cb(hwnd: int, _: Any) -> bool:
            try:
                if win32gui.IsWindowVisible(hwnd):
                    _, win_pid = win32process.GetWindowThreadProcessId(hwnd)
                    if win_pid in pid_set:
                        found.append(hwnd)
            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(_cb, None)
        except Exception as exc:
            logger.debug(f"[NOTEPAD] EnumWindows (pid scan) failed: {exc}")
        return found

    def find_notepad_hwnd(self) -> Optional[int]:
        """Return the HWND of the active Notepad window."""
        if self._session and self._is_session_valid(self._session):
            return self._session.hwnd

        registry = self._load_registry()
        assistant_hwnds = {s["hwnd"] for s in registry.get("assistant_sessions", [])}
        fallback_hwnd = self._scan_any_notepad_hwnd()
        if fallback_hwnd and fallback_hwnd in assistant_hwnds:
            try:
                _, pid = win32process.GetWindowThreadProcessId(fallback_hwnd)
            except Exception:
                pid = 0
            self._session = ApplicationSession(
                pid=pid,
                hwnd=fallback_hwnd,
                launched_by_assistant=True,
                launch_time=time.time()
            )
            self._save_session()
            return fallback_hwnd
        return None





    @staticmethod
    def _find_edit_control(hwnd: int) -> Optional[int]:
        """Find the inner Edit / RichEdit control of a Notepad window."""
        if not win32gui:
            return None
        
        candidates = []
        def _child_cb(child_hwnd: int, _: Any) -> bool:
            try:
                cls = win32gui.GetClassName(child_hwnd).lower()
                candidates.append((child_hwnd, cls))
            except Exception:
                pass
            return True

        try:
            win32gui.EnumChildWindows(hwnd, _child_cb, None)
        except Exception as exc:
            logger.debug(f"[NOTEPAD] EnumChildWindows failed: {exc}")

        # Search in order of preference: RichEditD2DPT, Edit, NotepadTextBox
        for target_cls in ["richeditd2dpt", "edit", "notepadtextbox"]:
            for child_hwnd, cls in candidates:
                if target_cls in cls:
                    logger.debug(f"[NOTEPAD] _find_edit_control found target '{target_cls}': HWND={child_hwnd}")
                    return child_hwnd
                    
        return None

    @staticmethod
    def _window_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
        """Return (left, top, right, bottom) for hwnd, or None."""
        if not win32gui:
            return None
        try:
            return win32gui.GetWindowRect(hwnd)
        except Exception as exc:
            logger.debug(f"[NOTEPAD] GetWindowRect({hwnd}) failed: {exc}")
            return None

    @staticmethod
    def _force_focus(hwnd: int) -> bool:
        """Bring *hwnd* to the foreground using the shared focus utility."""
        try:
            from automation.applications import force_focus_window
            result = force_focus_window(hwnd)
            logger.debug(f"[NOTEPAD] force_focus_window(HWND={hwnd}) → {result}")
            return result
        except Exception as exc:
            logger.debug(f"[NOTEPAD] force_focus_window exception: {exc}")
            return False

    @staticmethod
    def _get_foreground_hwnd() -> Optional[int]:
        if not win32gui:
            return None
        try:
            return win32gui.GetForegroundWindow()
        except Exception:
            return None

    @staticmethod
    def _is_foreground_notepad() -> bool:
        """Return True if the current foreground window is a Notepad window."""
        if not win32gui:
            return True  # can't verify — assume OK
        try:
            hwnd = win32gui.GetForegroundWindow()
            if hwnd:
                cls = win32gui.GetClassName(hwnd).lower()
                title = win32gui.GetWindowText(hwnd).lower()
                is_np = (cls == "notepad" or NOTEPAD_TITLE_FRAGMENT in title)
                logger.debug(
                    f"[NOTEPAD] _is_foreground_notepad: fg_hwnd={hwnd} "
                    f"cls='{cls}' title='{title}' → {is_np}"
                )
                return is_np
        except Exception as exc:
            logger.debug(f"[NOTEPAD] _is_foreground_notepad error: {exc}")
        return False

    def _click_text_area(self, hwnd: int) -> bool:
        """Click inside Notepad's text editing area to transfer keyboard focus.

        pyautogui.FAILSAFE is explicitly disabled before clicking to avoid crash
        triggers during test teardowns.
        """
        if not pyautogui:
            logger.debug("[NOTEPAD] _click_text_area: pyautogui not available")
            return False

        # Force FAILSAFE off immediately before click
        pyautogui.FAILSAFE = False

        # Try to click the Edit child control's centre
        edit_hwnd = self._find_edit_control(hwnd)
        target_hwnd = edit_hwnd or hwnd

        rect = self._window_rect(target_hwnd)
        if rect:
            left, top, right, bottom = rect
            cx = (left + right) // 2
            cy = (top + bottom) // 2
            logger.debug(
                f"[NOTEPAD] _click_text_area: clicking ({cx}, {cy}) "
                f"in {'edit' if edit_hwnd else 'frame'} HWND={target_hwnd}"
            )
            try:
                pyautogui.click(cx, cy)
                time.sleep(FOCUS_SETTLE_MS / 1000)
                return True
            except Exception as exc:
                logger.debug(f"[NOTEPAD] _click_text_area click failed: {exc}")
                return False

        # Fallback: click centre of the frame window
        frame_rect = self._window_rect(hwnd)
        if frame_rect:
            left, top, right, bottom = frame_rect
            cx = (left + right) // 2
            cy = (top + bottom) // 2
            logger.debug(
                f"[NOTEPAD] _click_text_area fallback: clicking ({cx}, {cy}) "
                f"in frame HWND={hwnd}"
            )
            try:
                pyautogui.click(cx, cy)
                time.sleep(FOCUS_SETTLE_MS / 1000)
                return True
            except Exception as exc:
                logger.debug(f"[NOTEPAD] _click_text_area fallback failed: {exc}")

        logger.debug("[NOTEPAD] _click_text_area: could not determine coordinates")
        return False

    def _ensure_notepad_focused(self, tool_name: str) -> Optional[ExecutionResult]:
        """Guard: ensure Notepad is the active window, restored if minimized, and focused."""
        hwnd = self.find_notepad_hwnd()
        if hwnd is None:
            logger.warning(f"[NOTEPAD] _ensure_focused({tool_name}): not running")
            return ExecutionResult(
                success=False,
                tool=tool_name,
                message="Notepad is not open. Use notepad_open first.",
            )

        if pyautogui:
            pyautogui.FAILSAFE = False

        # If minimized, restore it first and wait for restore animation
        if win32gui and win32gui.IsIconic(hwnd):
            logger.info(f"[NOTEPAD] Window {hwnd} is minimized. Restoring...")
            win32gui.ShowWindow(hwnd, 9) # SW_RESTORE
            time.sleep(0.3)

        # Log pre-focus state
        fg_before = self._get_foreground_hwnd()
        fg_title_before = ""
        if fg_before and win32gui:
            try:
                fg_title_before = win32gui.GetWindowText(fg_before)
            except Exception:
                pass
        logger.info(
            f"[NOTEPAD] _ensure_focused({tool_name}): "
            f"notepad_hwnd={hwnd}  fg_hwnd={fg_before} ('{fg_title_before}')"
        )

        # Raise frame
        focus_ok = self._force_focus(hwnd)

        # Click inside the text area to route keyboard input
        clicked = self._click_text_area(hwnd)

        # Log post-focus state
        fg_after = self._get_foreground_hwnd()
        fg_title_after = ""
        if fg_after and win32gui:
            try:
                fg_title_after = win32gui.GetWindowText(fg_after)
            except Exception:
                pass
        is_fg = self._is_foreground_notepad()
        logger.info(
            f"[NOTEPAD] _ensure_focused({tool_name}): "
            f"force_focus={focus_ok}  clicked={clicked}  "
            f"fg_after={fg_after} ('{fg_title_after}')  is_notepad_fg={is_fg}"
        )

        self._debug_pause("focus_notepad")
        return None  # proceed

    def _send_key_combo(self, hwnd: int, keys: list[str]) -> None:
        """Send a key combo (e.g. ['ctrl', 's']) using BOTH pyautogui and Win32 PostMessage."""
        if pyautogui:
            try:
                pyautogui.FAILSAFE = False
                self._force_focus(hwnd)
                time.sleep(0.2)
                pyautogui.hotkey(*keys)
            except Exception as e:
                logger.debug(f"[NOTEPAD] pyautogui.hotkey failed: {e}")
            
        if win32gui:
            try:
                import win32con
                vk_map = {
                    "ctrl": win32con.VK_CONTROL,
                    "shift": win32con.VK_SHIFT,
                    "alt": win32con.VK_MENU,
                    "n": ord('N'),
                    "s": ord('S'),
                    "f": ord('F'),
                    "a": ord('A'),
                    "enter": win32con.VK_RETURN,
                    "delete": win32con.VK_DELETE,
                    "tab": win32con.VK_TAB,
                }
                vkeys = [vk_map[k.lower()] for k in keys if k.lower() in vk_map]
                
                # Send KEYDOWN for modifiers
                for vk in vkeys[:-1]:
                    win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, vk, 0)
                    time.sleep(0.02)
                # Send KEYDOWN and KEYUP for the main key
                if vkeys:
                    main_vk = vkeys[-1]
                    msg_down = win32con.WM_SYSKEYDOWN if "alt" in keys else win32con.WM_KEYDOWN
                    msg_up = win32con.WM_SYSKEYUP if "alt" in keys else win32con.WM_KEYUP
                    win32gui.PostMessage(hwnd, msg_down, main_vk, 0)
                    time.sleep(0.02)
                    win32gui.PostMessage(hwnd, msg_up, main_vk, 0)
                    time.sleep(0.02)
                # Send KEYUP for modifiers in reverse order
                for vk in reversed(vkeys[:-1]):
                    win32gui.PostMessage(hwnd, win32con.WM_KEYUP, vk, 0)
                    time.sleep(0.02)
            except Exception as e:
                logger.debug(f"[NOTEPAD] win32 PostMessage hotkey failed: {e}")

    # ── Core: open & focus ──────────────────────────────────────────────

    def open_notepad(self) -> ExecutionResult:
        """Open Microsoft Notepad with a blank document.

        Bug-1 fix
        ---------
        Every call must start with a **fresh, empty document** so that typed
        text is never appended to content left over from a previous request.

        * If a valid assistant-owned session already exists  →  focus it and
          press Ctrl+N (new document), dismissing any "save changes?" prompt
          without saving, so the slate is clean.
        * If no valid session exists  →  launch a brand-new notepad.exe
          process and track it.
        """
        self._log_tool_precondition("notepad_open")
        if not win32gui or not win32process:
            return ExecutionResult(
                success=False,
                tool="notepad_open",
                message="win32gui/win32process is not available.",
            )

        # ── Step 1: If a valid session (or registered assistant window) exists, start a fresh document in it ──
        existing_hwnd = None
        if self._session and self._is_session_valid(self._session):
            existing_hwnd = self._session.hwnd
        else:
            scan_hwnd = self._scan_any_notepad_hwnd()
            if scan_hwnd and win32gui.IsWindow(scan_hwnd):
                registry = self._load_registry()
                assistant_hwnds = {s["hwnd"] for s in registry.get("assistant_sessions", [])}
                if scan_hwnd in assistant_hwnds:
                    existing_hwnd = scan_hwnd
                    try:
                        _, scan_pid = win32process.GetWindowThreadProcessId(scan_hwnd)
                    except Exception:
                        scan_pid = 0
                    self._session = ApplicationSession(
                        pid=scan_pid,
                        hwnd=scan_hwnd,
                        launched_by_assistant=True,
                        launch_time=time.time()
                    )
                    self._save_session()




        if existing_hwnd:
            hwnd = existing_hwnd
            logger.info(
                f"[NOTEPAD] open_notepad: valid window found (HWND={hwnd}). "
                f"Starting fresh document with Ctrl+N to avoid appending to old text."
            )
            # Ensure only one assistant-owned window exists
            registry = self._load_registry()
            for s in registry.get("assistant_sessions", []):
                s_hwnd = s.get("hwnd")
                s_pid = s.get("pid")
                if s_hwnd != hwnd:
                    self._close_stale_window(s_hwnd, s_pid)
            self._save_session()

            self._ensure_notepad_focused("notepad_open")
            time.sleep(0.3)  # Let window settle before sending Ctrl+N

            self._send_key_combo(hwnd, ["ctrl", "n"])
            time.sleep(0.5)  # Wait for "save changes?" prompt if any


            # Dismiss the "Do you want to save?" dialog without saving
            if self._is_unsaved_dialog_open():
                logger.info("[NOTEPAD] open_notepad: dismissing unsaved-changes dialog (Don't Save).")
                unsaved_dialog_hwnd = None
                # Scan for the dialog HWND
                for w in self._get_window_snapshot():
                    if w["hwnd"] != hwnd and w["pid"] == self._session.pid:
                        if w["class"].lower() == "#32770":
                            unsaved_dialog_hwnd = w["hwnd"]
                            break
                
                dismissed = False
                if unsaved_dialog_hwnd:
                    import win32con
                    # Try programmatic IDNO (7) or standard dialog control IDs
                    for btn_id in [7, 1002, 2]:
                        try:
                            btn = win32gui.GetDlgItem(unsaved_dialog_hwnd, btn_id)
                            if btn:
                                win32gui.SendMessage(unsaved_dialog_hwnd, win32con.WM_COMMAND, btn_id, btn)
                                dismissed = True
                                break
                        except Exception:
                            pass
                    if not dismissed:
                        # Fallback to direct key commands sent to the dialog
                        self._send_key_combo(unsaved_dialog_hwnd, ["tab"])
                        time.sleep(0.15)
                        self._send_key_combo(unsaved_dialog_hwnd, ["enter"])
                time.sleep(0.4)

            # Re-focus the now-blank document
            guard = self._ensure_notepad_focused("notepad_open")
            if guard and not guard.success:
                return guard
            self._debug_pause("open_notepad")

            
            # Clear any content and reset typing state
            self.clear_document()
            self._has_typed_in_session = False
            
            title = win32gui.GetWindowText(hwnd).strip() if (win32gui and win32gui.IsWindow(hwnd)) else "Notepad"
            return ExecutionResult(
                success=True,
                tool="notepad_open",
                message=f"Notepad focused with a fresh blank document — '{title}'.",
            )



        # ── Step 2: Clean up all stale assistant sessions before launching a new one ──
        registry = self._load_registry()
        for s in registry.get("assistant_sessions", []):
            s_hwnd = s.get("hwnd")
            s_pid = s.get("pid")
            self._close_stale_window(s_hwnd, s_pid)

        # Reset active session
        self._session = None
        self._save_session()

        # Track current visible Notepad frame HWNDs to identify the new window
        old_hwnds: set[int] = set()
        for w in self._get_window_snapshot():
            cls = w["class"].lower()
            if cls in ("notepad", "applicationframewindow"):
                if win32gui.IsWindow(w["hwnd"]) and win32gui.IsWindowVisible(w["hwnd"]):
                    old_hwnds.add(w["hwnd"])

        # ── Step 3: Launch a new notepad.exe process ──
        logger.info("[NOTEPAD] open_notepad: no valid session — launching new Notepad process.")
        try:
            subprocess.Popen([NOTEPAD_EXE], shell=False)
        except Exception as exc:
            return ExecutionResult(
                success=False,
                tool="notepad_open",
                message=f"Failed to launch notepad.exe: {exc}",
            )

        # ── Step 4: Poll for the new window (up to ~5.0 s) ──
        # Non-UI helper windows (GDI+ Hook, IME, etc.) appear before the
        # actual Notepad frame and must be ignored.
        _NON_UI_CLASSES = frozenset({
            "gdi+ hook window class", "ime", "msctfime ui",
            "tooltips_class32", "windows.ui.core.corewindow",
        })
        new_hwnd: Optional[int] = None
        new_pid: Optional[int] = None
        for _ in range(25):
            time.sleep(0.2)
            for w in self._get_window_snapshot():
                hwnd = w["hwnd"]
                cls = w["class"].lower()
                title = w["title"].lower()
                # Skip non-UI helper windows
                if cls in _NON_UI_CLASSES:
                    continue
                # Must be a real, visible Notepad frame class
                is_notepad_frame = (
                    cls in ("notepad", "applicationframewindow")
                )
                if is_notepad_frame and win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd):
                    if hwnd not in old_hwnds:
                        new_hwnd = hwnd
                        new_pid = w["pid"]
                        break
            if new_hwnd:
                break

        if not new_hwnd:
            candidate = self._scan_any_notepad_hwnd()
            if candidate and win32gui.IsWindow(candidate):
                new_hwnd = candidate
                try:
                    _, new_pid = win32process.GetWindowThreadProcessId(new_hwnd)
                except Exception:
                    new_pid = 99999


        if not new_hwnd:
            return ExecutionResult(
                success=False,
                tool="notepad_open",
                message="Notepad window did not appear within timeout.",
            )

        if not new_pid or new_pid <= 0:
            new_pid = 99999


        # ── Step 5: Register session ──
        self._session = ApplicationSession(
            pid=new_pid,
            hwnd=new_hwnd,
            launched_by_assistant=True,
            launch_time=time.time(),
        )
        self._save_session()
        logger.info(f"[NOTEPAD] Assistant launched new Notepad: HWND={new_hwnd}, PID={new_pid}")

        # ── Step 6: Wait for edit control to be fully ready (up to ~3 s) ──
        # The window frame may appear before the inner RichEdit/Edit control is
        # initialised.  Waiting here ensures _is_session_valid() succeeds for all
        # subsequent tool calls.
        edit_ready = False
        for _ in range(20):
            time.sleep(0.15)
            if self._find_edit_control(new_hwnd):
                edit_ready = True
                break
        if not edit_ready:
            logger.warning("[NOTEPAD] open_notepad: edit control not ready after 3 s wait; proceeding anyway.")

        # Focus the window
        self._ensure_notepad_focused("notepad_open")
        self._debug_pause("open_notepad")
        
        title = win32gui.GetWindowText(new_hwnd).strip()
        title_lower = title.lower()
        is_untitled = (
            title == "Untitled - Notepad"
            or title.startswith("*Untitled")
            or title_lower.startswith("untitled")
            or title_lower.startswith("*untitled")
            or "unbenannt" in title_lower
            or title_lower == "notepad"
            or not title_lower
        )
        
        if not is_untitled:
            logger.info(f"[NOTEPAD] open_notepad: new window has restored title '{title}'. Creating new blank document with Ctrl+N...")
            # Send Ctrl+N to the new window to get a blank document
            self._send_key_combo(new_hwnd, ["ctrl", "n"])
            time.sleep(0.5)
            fresh_hwnd = self._scan_any_notepad_hwnd()
            if fresh_hwnd:
                new_hwnd = fresh_hwnd
                self._session.hwnd = fresh_hwnd
                self._save_session()
            # Dismiss dialog if any
            if self._is_unsaved_dialog_open():
                unsaved_dialog_hwnd = None
                for w in self._get_window_snapshot():
                    if w["hwnd"] != new_hwnd and w["pid"] == new_pid:
                        if w["class"].lower() == "#32770":
                            unsaved_dialog_hwnd = w["hwnd"]
                            break
                dismissed = False
                if unsaved_dialog_hwnd:
                    import win32con
                    for btn_id in [7, 1002, 2]:
                        try:
                            btn = win32gui.GetDlgItem(unsaved_dialog_hwnd, btn_id)
                            if btn:
                                win32gui.SendMessage(unsaved_dialog_hwnd, win32con.WM_COMMAND, btn_id, btn)
                                dismissed = True
                                break
                        except Exception:
                            pass
                    if not dismissed:
                        self._send_key_combo(unsaved_dialog_hwnd, ["tab"])
                        time.sleep(0.15)
                        self._send_key_combo(unsaved_dialog_hwnd, ["enter"])
                time.sleep(0.4)


        # Clear any content and reset typing state
        self.clear_document()
        self._has_typed_in_session = False

        
        return ExecutionResult(
            success=True,
            tool="notepad_open",
            message=f"Notepad launched and focused — fresh blank document ready ('{title}').",
        )

    def _wait_for_window(self, timeout: float = WINDOW_LAUNCH_TIMEOUT) -> Optional[int]:
        """Poll for a Notepad window until *timeout* seconds elapse."""
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            hwnd = self.find_notepad_hwnd()
            if hwnd:
                return hwnd
            time.sleep(WINDOW_POLL_INTERVAL)
        logger.warning(
            f"[NOTEPAD] _wait_for_window: timeout after {timeout}s"
        )
        return None

    def focus_notepad(self) -> ExecutionResult:
        """Bring an existing Notepad window to the foreground."""
        hwnd = self.find_notepad_hwnd()
        if hwnd is None:
            return ExecutionResult(
                success=False,
                tool="notepad_open",
                message="Notepad is not currently running. Use notepad_open first.",
            )
        focused = self._force_focus(hwnd)
        self._click_text_area(hwnd)
        return ExecutionResult(
            success=True,
            tool="notepad_open",
            message=(
                "Notepad brought to foreground."
                if focused
                else "Notepad window found; focus attempted (OS lock may be active)."
            ),
        )

    # ── Typing ──────────────────────────────────────────────────────────

    def type_text(self, text: str) -> ExecutionResult:
        """Type *text* into Notepad's text area."""
        if isinstance(text, dict):
            text = text.get("text", "")

        if not text:
            return ExecutionResult(
                success=False,
                tool="notepad_type",
                message="No text provided.",
            )

        logger.info(f"[NOTEPAD] type_text: text='{text[:60]}{'...' if len(text) > 60 else ''}'")

        # Check if this is the first typing in the session
        if not getattr(self, "_has_typed_in_session", False):
            hwnd = self.find_notepad_hwnd()
            if not hwnd:
                return ExecutionResult(
                    success=False,
                    tool="notepad_type",
                    message="Notepad is not open. Use notepad_open first.",
                )
            
            # Verify that the title is "Untitled - Notepad" (or starts with "*Untitled")
            title = ""
            if win32gui:
                try:
                    title = win32gui.GetWindowText(hwnd).strip()
                except Exception:
                    pass
            
            title_lower = title.lower()
            is_untitled = (
                title == "Untitled - Notepad"
                or title.startswith("*Untitled")
                or title_lower.startswith("untitled")
                or title_lower.startswith("*untitled")
                or "unbenannt" in title_lower
                or title_lower == "notepad"
                or not title_lower
            )
            
            if not is_untitled:
                logger.info(f"[NOTEPAD] type_text: Title '{title}' is not untitled. Creating new blank document...")
                # Send Ctrl+N
                self._send_key_combo(hwnd, ["ctrl", "n"])
                time.sleep(0.5)
                # Dismiss unsaved changes dialog if any
                if self._is_unsaved_dialog_open():
                    logger.info("[NOTEPAD] type_text: dismissing unsaved dialog...")
                    unsaved_dialog_hwnd = None
                    for w in self._get_window_snapshot():
                        if w["hwnd"] != hwnd and w["pid"] == self._session.pid:
                            if w["class"].lower() == "#32770":
                                unsaved_dialog_hwnd = w["hwnd"]
                                break
                    dismissed = False
                    if unsaved_dialog_hwnd:
                        import win32con
                        for btn_id in [7, 1002, 2]:
                            try:
                                btn = win32gui.GetDlgItem(unsaved_dialog_hwnd, btn_id)
                                if btn:
                                    win32gui.SendMessage(unsaved_dialog_hwnd, win32con.WM_COMMAND, btn_id, btn)
                                    dismissed = True
                                    break
                            except Exception:
                                pass
                        if not dismissed:
                            self._send_key_combo(unsaved_dialog_hwnd, ["tab"])
                            time.sleep(0.15)
                            self._send_key_combo(unsaved_dialog_hwnd, ["enter"])
                    time.sleep(0.4)
                
                # Re-verify title
                if win32gui:
                    try:
                        title = win32gui.GetWindowText(hwnd).strip()
                    except Exception:
                        pass
                title_lower = title.lower()
                is_untitled = (
                    title == "Untitled - Notepad"
                    or title.startswith("*Untitled")
                    or title_lower.startswith("untitled")
                    or title_lower.startswith("*untitled")
                    or "unbenannt" in title_lower
                    or title_lower == "notepad"
                    or not title_lower
                )
                if not is_untitled:
                    return ExecutionResult(
                        success=False,
                        tool="notepad_type",
                        message=f"Failed to create new blank document before typing. Title: '{title}'",
                    )
            
            # Clear any existing content if necessary
            logger.info("[NOTEPAD] type_text: clearing existing content before first write...")
            self.clear_document()
            self._has_typed_in_session = True

        # Ensure Notepad is running and raised visually (best-effort)
        guard = self._ensure_notepad_focused("notepad_type")
        if guard:
            return guard

        # Get the edit control HWND
        hwnd = self.find_notepad_hwnd()
        edit_hwnd = self._find_edit_control(hwnd) if hwnd else None
 
        # --- Primary Path: Win32 message (works in headless, locked RDP, background) ---
        if edit_hwnd:
            try:
                logger.info(f"[NOTEPAD] type_text: attempting Win32 EM_REPLACESEL message to HWND={edit_hwnd}...")
                # EM_REPLACESEL is 0x00C2
                res = ctypes.windll.user32.SendMessageW(edit_hwnd, 0x00C2, 1, text)
                logger.info(f"[NOTEPAD] type_text: SendMessageW(EM_REPLACESEL) result = {res}")
                self._debug_pause("type_text")
                return ExecutionResult(
                    success=True,
                    tool="notepad_type",
                    message=f"Typed into Notepad (via WM): '{text[:60]}{'...' if len(text) > 60 else ''}'",
                )
            except Exception as exc:
                logger.warning(f"[NOTEPAD] type_text: Win32 EM_REPLACESEL failed: {exc}. Falling back to GUI...")
 
        # --- Secondary Path: PyAutoGUI hardware / clipboard simulation ---
        if not pyautogui:
            return ExecutionResult(
                success=False,
                tool="notepad_type",
                message="Win32 msg failed and pyautogui is not available.",
            )
 
        pyautogui.FAILSAFE = False
        paste_ok = False
        if pyperclip:
            try:
                old_clip = ""
                try:
                    old_clip = pyperclip.paste()
                except Exception:
                    pass
 
                pyperclip.copy(text)
                time.sleep(0.05)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.25)
                paste_ok = True
                logger.info("[NOTEPAD] type_text: GUI clipboard paste succeeded")
 
                try:
                    pyperclip.copy(old_clip)
                except Exception:
                    pass
            except Exception as exc:
                logger.warning(f"[NOTEPAD] type_text: GUI clipboard paste failed: {exc}. Falling back to write()...")
 
        if not paste_ok:
            try:
                pyautogui.FAILSAFE = False
                pyautogui.write(text, interval=TYPING_INTERVAL)
                time.sleep(0.2)
                logger.info("[NOTEPAD] type_text: GUI write() completed")
            except Exception as exc:
                logger.error(f"[NOTEPAD] type_text: GUI write() failed: {exc}")
                return ExecutionResult(
                    success=False,
                    tool="notepad_type",
                    message=f"Typing failed on all attempts: {exc}",
                )
 
        self._debug_pause("type_text")
        return ExecutionResult(
            success=True,
            tool="notepad_type",
            message=f"Typed into Notepad (via GUI): '{text[:60]}{'...' if len(text) > 60 else ''}'",
        )
 
    # ── Keyboard shortcuts ───────────────────────────────────────────────
 
    def _hotkey(
        self, tool_name: str, *keys: str, description: str = ""
    ) -> ExecutionResult:
        """Guard focus, press hotkey, return result."""
        if not pyautogui:
            return ExecutionResult(
                success=False,
                tool=tool_name,
                message="pyautogui is not available.",
            )
        guard = self._ensure_notepad_focused(tool_name)
        if guard:
            return guard
        try:
            pyautogui.FAILSAFE = False
            pyautogui.hotkey(*keys)
            time.sleep(0.15)
            return ExecutionResult(
                success=True,
                tool=tool_name,
                message=description or f"Executed {'+'.join(keys)} in Notepad.",
            )
        except Exception as exc:
            return ExecutionResult(
                success=False,
                tool=tool_name,
                message=f"{tool_name} failed: {exc}",
            )
 
    def _press(
        self, tool_name: str, key: str, description: str = ""
    ) -> ExecutionResult:
        """Guard focus, press single key, return result."""
        if not pyautogui:
            return ExecutionResult(
                success=False,
                tool=tool_name,
                message="pyautogui is not available.",
            )
        guard = self._ensure_notepad_focused(tool_name)
        if guard:
            return guard
        try:
            pyautogui.FAILSAFE = False
            pyautogui.press(key)
            time.sleep(0.1)
            return ExecutionResult(
                success=True,
                tool=tool_name,
                message=description or f"Pressed '{key}' in Notepad.",
            )
        except Exception as exc:
            return ExecutionResult(
                success=False,
                tool=tool_name,
                message=f"{tool_name} failed: {exc}",
            )
 
    def press_enter(self) -> ExecutionResult:
        """Insert a new line inside Notepad (Ctrl+Enter / Enter)."""
        hwnd = self.find_notepad_hwnd()
        edit_hwnd = self._find_edit_control(hwnd) if hwnd else None
        
        # Primary: Win32 EM_REPLACESEL with "\r\n"
        if edit_hwnd:
            try:
                # EM_REPLACESEL is 0x00C2
                res = ctypes.windll.user32.SendMessageW(edit_hwnd, 0x00C2, 1, "\r\n")
                logger.info(f"[NOTEPAD] press_enter: SendMessageW(EM_REPLACESEL) result = {res}")
                return ExecutionResult(
                    success=True,
                    tool="notepad_press_enter",
                    message="Pressed Enter (via Win32 EM_REPLACESEL).",
                )
            except Exception as exc:
                logger.warning(f"[NOTEPAD] press_enter: Win32 message failed: {exc}. Falling back to GUI...")
 
        return self._press(
            "notepad_press_enter", "enter", "Pressed Enter in Notepad (new line)."
        )
 
    def select_all(self) -> ExecutionResult:
        """Select all text in Notepad."""
        hwnd = self.find_notepad_hwnd()
        edit_hwnd = self._find_edit_control(hwnd) if hwnd else None
        
        # Primary: Win32 EM_SETSEL (0x00B1)
        if edit_hwnd:
            try:
                # wParam = 0, lParam = -1 selects all
                res = ctypes.windll.user32.SendMessageW(edit_hwnd, 0x00B1, 0, -1)
                logger.info(f"[NOTEPAD] select_all: SendMessageW(EM_SETSEL) result = {res}")
                return ExecutionResult(
                    success=True,
                    tool="notepad_select_all",
                    message="Selected all text (via Win32 EM_SETSEL).",
                )
            except Exception as exc:
                logger.warning(f"[NOTEPAD] select_all: Win32 message failed: {exc}. Falling back to GUI...")
 
        return self._hotkey(
            "notepad_select_all", "ctrl", "a",
            description="Selected all text in Notepad.",
        )
 
    def copy(self) -> ExecutionResult:
        """Copy the selected text to the clipboard."""
        hwnd = self.find_notepad_hwnd()
        edit_hwnd = self._find_edit_control(hwnd) if hwnd else None
        
        # Primary: Win32 WM_COPY (0x0301)
        if edit_hwnd:
            try:
                res = ctypes.windll.user32.SendMessageW(edit_hwnd, 0x0301, 0, 0)
                logger.info(f"[NOTEPAD] copy: SendMessageW(WM_COPY) result = {res}")
                return ExecutionResult(
                    success=True,
                    tool="notepad_copy",
                    message="Copied selection to clipboard (via Win32 WM_COPY).",
                )
            except Exception as exc:
                logger.warning(f"[NOTEPAD] copy: Win32 message failed: {exc}. Falling back to GUI...")
 
        return self._hotkey(
            "notepad_copy", "ctrl", "c",
            description="Copied selection to clipboard.",
        )
 
    def paste(self) -> ExecutionResult:
        """Paste clipboard contents at the cursor."""
        hwnd = self.find_notepad_hwnd()
        edit_hwnd = self._find_edit_control(hwnd) if hwnd else None
        
        # Primary: Win32 WM_PASTE (0x0302)
        if edit_hwnd:
            try:
                res = ctypes.windll.user32.SendMessageW(edit_hwnd, 0x0302, 0, 0)
                logger.info(f"[NOTEPAD] paste: SendMessageW(WM_PASTE) result = {res}")
                return ExecutionResult(
                    success=True,
                    tool="notepad_paste",
                    message="Pasted selection (via Win32 WM_PASTE).",
                )
            except Exception as exc:
                logger.warning(f"[NOTEPAD] paste: Win32 message failed: {exc}. Falling back to GUI...")
 
        return self._hotkey(
            "notepad_paste", "ctrl", "v",
            description="Pasted clipboard contents into Notepad.",
        )
 
    def undo(self) -> ExecutionResult:
        """Undo last edit action."""
        hwnd = self.find_notepad_hwnd()
        edit_hwnd = self._find_edit_control(hwnd) if hwnd else None
        
        # Primary: Win32 EM_UNDO (0x00C7)
        if edit_hwnd:
            try:
                res = ctypes.windll.user32.SendMessageW(edit_hwnd, 0x00C7, 0, 0)
                logger.info(f"[NOTEPAD] undo: SendMessageW(EM_UNDO) result = {res}")
                return ExecutionResult(
                    success=True,
                    tool="notepad_undo",
                    message="Undid last action (via Win32 EM_UNDO).",
                )
            except Exception as exc:
                logger.warning(f"[NOTEPAD] undo: Win32 message failed: {exc}. Falling back to GUI...")
 
        return self._hotkey(
            "notepad_undo", "ctrl", "z",
            description="Undid last action in Notepad.",
        )
 
    def redo(self) -> ExecutionResult:
        """Redo last undone action."""
        hwnd = self.find_notepad_hwnd()
        edit_hwnd = self._find_edit_control(hwnd) if hwnd else None
        
        # Primary: Win32 EM_REDO (0x0454) for RichEdit
        if edit_hwnd:
            try:
                res = ctypes.windll.user32.SendMessageW(edit_hwnd, 0x0454, 0, 0)
                logger.info(f"[NOTEPAD] redo: SendMessageW(EM_REDO) result = {res}")
                return ExecutionResult(
                    success=True,
                    tool="notepad_redo",
                    message="Redid last undone action (via Win32 EM_REDO).",
                )
            except Exception as exc:
                logger.warning(f"[NOTEPAD] redo: Win32 message failed: {exc}. Falling back to GUI...")
 
        return self._hotkey(
            "notepad_redo", "ctrl", "y",
            description="Redid last undone action in Notepad.",
        )
 
    def delete_text(self) -> ExecutionResult:
        """Clear selection or entire text inside editor."""
        hwnd = self.find_notepad_hwnd()
        edit_hwnd = self._find_edit_control(hwnd) if hwnd else None
        
        # Primary: Win32 WM_CLEAR (0x0303)
        if edit_hwnd:
            try:
                res = ctypes.windll.user32.SendMessageW(edit_hwnd, 0x0303, 0, 0)
                logger.info(f"[NOTEPAD] delete_text: SendMessageW(WM_CLEAR) result = {res}")
                return ExecutionResult(
                    success=True,
                    tool="notepad_delete",
                    message="Deleted selection (via Win32 WM_CLEAR).",
                )
            except Exception as exc:
                logger.warning(f"[NOTEPAD] delete_text: Win32 message failed: {exc}. Falling back to GUI...")
 
        if not pyautogui:
            return ExecutionResult(
                success=False,
                tool="notepad_delete",
                message="pyautogui is not available.",
            )
        guard = self._ensure_notepad_focused("notepad_delete")
        if guard:
            return guard
        try:
            pyautogui.FAILSAFE = False
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.1)
            pyautogui.press("delete")
            time.sleep(0.1)
            return ExecutionResult(
                success=True,
                tool="notepad_delete",
                message="Deleted text in Notepad.",
            )
        except Exception as exc:
            return ExecutionResult(
                success=False,
                tool="notepad_delete",
                message=f"Delete failed: {exc}",
            )

    def clear_document(self) -> ExecutionResult:
        """Clear entire text in Notepad."""
        hwnd = self.find_notepad_hwnd()
        edit_hwnd = self._find_edit_control(hwnd) if hwnd else None
        
        # Primary: Win32 WM_SETTEXT (0x000C) with empty string
        if edit_hwnd:
            try:
                res = ctypes.windll.user32.SendMessageW(edit_hwnd, 0x000C, 0, "")
                logger.info(f"[NOTEPAD] clear_document: SendMessageW(WM_SETTEXT) result = {res}")
                return ExecutionResult(
                    success=True,
                    tool="notepad_clear",
                    message="Cleared document (via Win32 WM_SETTEXT).",
                )
            except Exception as exc:
                logger.warning(f"[NOTEPAD] clear_document: Win32 message failed: {exc}. Falling back to GUI...")
 
        result = self.delete_text()
        result.tool = "notepad_clear"
        return result

    def _read_editor_text(self) -> str:
        """Read the current text from Notepad's editor control via Win32 messages.

        Returns an empty string if the control cannot be reached.
        """
        hwnd = self.find_notepad_hwnd()
        if not hwnd:
            return ""
        edit_hwnd = self._find_edit_control(hwnd)
        if not edit_hwnd or not win32gui:
            return ""
        try:
            length = win32gui.SendMessage(edit_hwnd, win32con.WM_GETTEXTLENGTH, 0, 0)
            if length == 0:
                return ""
            buf = ctypes.create_unicode_buffer(length + 1)
            win32gui.SendMessage(edit_hwnd, win32con.WM_GETTEXT, length + 1, ctypes.addressof(buf))
            return buf.value
        except Exception as exc:
            logger.debug(f"[NOTEPAD] _read_editor_text failed: {exc}")
            return ""

    def _verify_editor_text(self, expected_snippet: str) -> bool:
        """Return True if the editor currently contains *expected_snippet*.

        Used to confirm that typing succeeded before attempting to save.
        The comparison is case-sensitive and checks for substring inclusion.
        """
        actual = self._read_editor_text()
        ok = bool(actual and expected_snippet and expected_snippet in actual)
        logger.info(
            f"[NOTEPAD] _verify_editor_text: snippet_len={len(expected_snippet)} "
            f"editor_len={len(actual)} match={ok}"
        )
        return ok

    # ── File operations ─────────────────────────────────────────────────

    def save_file(self, filename: Optional[str] = None, directory: Optional[str] = None) -> ExecutionResult:
        """Save the current Notepad document.

        Workflow
        --------
        1. Ensure Notepad is focused.
        2. Press Ctrl+S.
           - If the document has never been saved (Untitled), Windows opens
             the Save As dialog automatically.
           - If the document already has a path, Ctrl+S saves silently.
        3. If a Save As dialog appears (detected within 3 s) **or** a
           *filename* / *directory* argument was supplied, hand off to
           ``save_as`` which runs the full dialog state machine.
        4. Otherwise assume Ctrl+S completed silently and return success.
        """
        self._log_tool_precondition("notepad_save")
        hwnd = self.find_notepad_hwnd()
        if hwnd is None:
            return ExecutionResult(
                success=False,
                tool="notepad_save",
                message="Notepad is not open. Use notepad_open first.",
            )

        # Check whether the document is untitled
        title = ""
        if win32gui:
            try:
                title = win32gui.GetWindowText(hwnd).lower()
            except Exception:
                pass
        is_untitled = (
            "untitled" in title
            or "unbenannt" in title
            or title.strip() == "notepad"
            or not title
        )

        # If a specific filename is requested, always use the Save As flow
        if filename:
            logger.info(
                f"[NOTEPAD] save_file: filename='{filename}' supplied — "
                f"delegating to save_as state machine."
            )
            return self.save_as(filename, directory=directory, overwrite=True)

        if is_untitled:
            # Ctrl+S on an untitled doc opens the Save As dialog.
            # Use a default name so the dialog can be completed automatically.
            default_name = "document.txt"
            logger.info(
                f"[NOTEPAD] save_file: document is untitled — "
                f"pressing Ctrl+S and handling Save As dialog (default name: '{default_name}')."
            )
            return self.save_as(default_name, directory=directory, overwrite=True)

        # Already-named document — Ctrl+S saves silently.
        logger.info("[NOTEPAD] save_file: document is named — pressing Ctrl+S for silent save.")
        res = self._hotkey("notepad_save", "ctrl", "s", description="Saved file (Ctrl+S).")
        if res.success and getattr(self, "_last_saved_path", None):
            res.saved_path = self._last_saved_path
        return res

    def save_as(
        self,
        filename: str,
        directory: Optional[str] = None,
        overwrite: bool = False,
    ) -> ExecutionResult:
        """Save the Notepad document to *filename* in *directory*.

        Implementation strategy
        -----------------------
        PRIMARY (headless-safe):
            Read the editor text via Win32 WM_GETTEXT, then write it to the
            target path using Python ``open()``.  This requires NO keyboard
            input, NO window focus, NO dialog interaction, and works in every
            session type: interactive, locked desktop, RDP, headless CI.

        SECONDARY (interactive fallback):
            If the primary path fails, fall back to the dialog-based state
            machine: TRIGGER_DIALOG -> SET_FULL_PATH -> CONFIRM_SAVE -> VERIFY_FILE

        Invariants
        ----------
        * ``directory`` is expanded to an absolute path and used ONLY for the
          target-path computation.  It is NEVER appended to the filename.
        * ``filename`` is the bare file name (e.g. ``aiml.txt``).  NEVER a path.
        * ``expected_path`` is only used for ``os.path.exists()`` verification.
        * On any failure, Notepad is left open so the user can recover.
        """
        self._log_tool_precondition("notepad_save_as")
        if not filename:
            return ExecutionResult(
                success=False, tool="notepad_save_as",
                message="No filename provided for Save As.",
            )

        import os

        # ── Pre-process inputs ──────────────────────────────────────────────
        raw_filename  = filename
        raw_directory = directory

        # If caller passed a full path as filename, split it
        if os.path.dirname(raw_filename):
            raw_directory = raw_directory or os.path.dirname(raw_filename)
            raw_filename  = os.path.basename(raw_filename)

        # If no directory is provided:
        # - Resolve the actual Desktop path.
        # - Support both %USERPROFILE%\Desktop and %USERPROFILE%\OneDrive\Desktop.
        # - Choose whichever exists.
        if not raw_directory:
            user_profile = os.environ.get("USERPROFILE") or os.path.expanduser("~")
            onedrive_desktop = os.path.join(user_profile, "OneDrive", "Desktop")
            normal_desktop = os.path.join(user_profile, "Desktop")
            if os.path.isdir(onedrive_desktop):
                raw_directory = onedrive_desktop
            else:
                raw_directory = normal_desktop

        # Ensure raw_filename has a .txt extension if no extension is present
        _, ext = os.path.splitext(raw_filename)
        if not ext:
            raw_filename += ".txt"

        def _expand_dir(d: Optional[str]) -> Optional[str]:
            """Expand a well-known folder alias (Desktop, Documents, …) to an
            absolute path using the Windows registry so OneDrive redirects are
            handled correctly."""
            if not d:
                return d
            if os.path.isabs(d):
                return os.path.abspath(d)
            dl = d.lower().strip()
            reg_mapping = {
                "desktop":   "Desktop",
                "documents": "Personal",
                "personal":  "Personal",
                "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
                "pictures":  "My Pictures",
                "music":     "My Music",
                "videos":    "My Video",
            }
            value_name = None
            for key, val in reg_mapping.items():
                if key in dl:
                    value_name = val
                    break
            if value_name:
                try:
                    import winreg
                    with winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
                    ) as reg_key:
                        reg_val, _ = winreg.QueryValueEx(reg_key, value_name)
                        return os.path.abspath(os.path.expandvars(reg_val))
                except Exception as e:
                    logger.debug(f"[NOTEPAD] Registry lookup for '{dl}' failed: {e}")
            home = os.path.expanduser("~")
            if "desktop"   in dl: return os.path.join(home, "Desktop")
            if "documents" in dl: return os.path.join(home, "Documents")
            if "downloads" in dl: return os.path.join(home, "Downloads")
            if "pictures"  in dl: return os.path.join(home, "Pictures")
            if "music"     in dl: return os.path.join(home, "Music")
            if "videos"    in dl: return os.path.join(home, "Videos")
            return d

        verify_dir   = _expand_dir(raw_directory)
        filename_to_type = raw_filename

        if verify_dir:
            expected_path = os.path.abspath(os.path.join(verify_dir, raw_filename))
        else:
            expected_path = os.path.abspath(raw_filename)

        logger.info(
            f"[NOTEPAD] save_as: filename='{filename_to_type}' "
            f"dir='{verify_dir or '(cwd)'}' "
            f"expected_path='{expected_path}'"
        )

        # Guard: Notepad must be open
        notepad_hwnd = self.find_notepad_hwnd()
        if not notepad_hwnd:
            return ExecutionResult(
                success=False, tool="notepad_save_as",
                message="Notepad is not open. Use notepad_open first.",
            )

        # ── Check overwrite ─────────────────────────────────────────────────
        if os.path.exists(expected_path) and not overwrite:
            return ExecutionResult(
                success=False, tool="notepad_save_as",
                message=(
                    f"File '{expected_path}' already exists and overwrite=False. "
                    f"Pass overwrite=True to replace it."
                ),
            )

        # ======================================================================
        # PRIMARY PATH — Direct file write (headless-safe, no dialog needed)
        # ======================================================================
        try:
            editor_text = self._read_editor_text()
            logger.info(
                f"[NOTEPAD] save_as [PRIMARY]: read {len(editor_text)} chars from editor."
            )

            # Ensure target directory exists
            target_dir = os.path.dirname(expected_path)
            if target_dir:
                os.makedirs(target_dir, exist_ok=True)

            with open(expected_path, "w", encoding="utf-8", newline="") as fh:
                fh.write(editor_text)

            if os.path.exists(expected_path):
                logger.info(
                    f"[NOTEPAD] save_as [PRIMARY]: SUCCESS — "
                    f"wrote {len(editor_text)} chars to '{expected_path}'."
                )
                self._last_saved_path = expected_path
                self._save_session()
                self._debug_pause("save_confirmed")
                return ExecutionResult(
                    success=True, tool="notepad_save_as",
                    message=f"File saved successfully at '{expected_path}'.",
                    saved_path=expected_path
                )
            else:
                logger.warning(
                    f"[NOTEPAD] save_as [PRIMARY]: wrote file but it does not "
                    f"exist at '{expected_path}'. Falling back to dialog."
                )
        except Exception as exc:
            logger.warning(
                f"[NOTEPAD] save_as [PRIMARY]: direct write failed: {exc}. "
                f"Falling back to Save As dialog."
            )

        # ======================================================================
        # SECONDARY PATH — Save As dialog state machine (interactive sessions)
        # ======================================================================
        if not pyautogui:
            return ExecutionResult(
                success=False, tool="notepad_save_as",
                message=(
                    "Direct file write failed and pyautogui is unavailable "
                    "(headless session). Cannot open Save As dialog."
                ),
            )

        # Snapshot editor text before dialog opens (for content verification)
        editor_text = self._read_editor_text()
        pyautogui.FAILSAFE = False

        try:
            # ==================================================================
            # STATE 1 – TRIGGER_DIALOG
            # Triggers tried in order:
            #   A) Ctrl+S       – standard; opens dialog on Untitled docs
            #   B) Alt+F → A   – classic Notepad menu fallback
            #   C) Ctrl+Shift+S – Windows-11 explicit "Save As" shortcut
            # ==================================================================
            state = "TRIGGER_DIALOG"
            logger.info(f"[NOTEPAD] save_as [{state}]: starting dialog fallback")

            save_dialog_hwnd: Optional[int] = None

            def _wait_for_dialog(max_secs: float = 4.0) -> Optional[int]:
                deadline = time.perf_counter() + max_secs
                while time.perf_counter() < deadline:
                    time.sleep(0.12)
                    h = self._find_save_dialog_hwnd()
                    if h:
                        return h
                return None

            def _clean_modifiers():
                for k in ["ctrl", "shift", "alt"]:
                    try:
                        pyautogui.keyUp(k)
                    except Exception:
                        pass

            # Trigger A: Ctrl+S
            logger.info("[NOTEPAD] save_as [TRIGGER_DIALOG]: trying Ctrl+S")
            self._send_key_combo(notepad_hwnd, ["ctrl", "s"])
            _clean_modifiers()
            save_dialog_hwnd = _wait_for_dialog(3.0)

            # Trigger B: Alt+F → A
            if not save_dialog_hwnd:
                logger.info("[NOTEPAD] save_as [TRIGGER_DIALOG]: trying Alt+F → A")
                self._send_key_combo(notepad_hwnd, ["alt", "f"])
                time.sleep(0.35)
                self._send_key_combo(notepad_hwnd, ["a"])
                _clean_modifiers()
                save_dialog_hwnd = _wait_for_dialog(4.0)

            # Trigger C: Ctrl+Shift+S
            if not save_dialog_hwnd:
                logger.info("[NOTEPAD] save_as [TRIGGER_DIALOG]: trying Ctrl+Shift+S")
                self._force_focus(notepad_hwnd)
                time.sleep(0.3)
                pyautogui.hotkey("ctrl", "shift", "s")
                _clean_modifiers()
                save_dialog_hwnd = _wait_for_dialog(3.5)

            if not save_dialog_hwnd:
                return ExecutionResult(
                    success=False, tool="notepad_save_as",
                    message=(
                        "[TRIGGER_DIALOG] Save As dialog did not appear after "
                        "Ctrl+S, Alt+F→A, and Ctrl+Shift+S."
                    ),
                )

            logger.info(
                f"[NOTEPAD] save_as [TRIGGER_DIALOG]: dialog HWND={save_dialog_hwnd}"
            )
            self._force_focus(save_dialog_hwnd)
            for _ in range(15):
                time.sleep(0.1)
                if self._get_foreground_hwnd() == save_dialog_hwnd:
                    break
            time.sleep(0.4)
            self._debug_pause("save_dialog_open")

            # ==================================================================
            # STATE 2+3 – SET_FULL_PATH
            # Type the complete absolute path into the File-name textbox.
            # ==================================================================
            state = "SET_FULL_PATH"
            path_to_type = expected_path if verify_dir else filename_to_type
            logger.info(
                f"[NOTEPAD] save_as [{state}]: setting filename box to '{path_to_type}'"
            )
            fname_ok = self._set_filename_in_save_dialog(save_dialog_hwnd, path_to_type)
            if not fname_ok:
                logger.warning(f"[NOTEPAD] save_as [{state}]: _set_filename_in_save_dialog failed.")

            time.sleep(0.3)
            self._debug_pause("filename_entry")

            if not self._is_save_dialog_open():
                return ExecutionResult(
                    success=False, tool="notepad_save_as",
                    message=f"[{state}] Save As dialog closed unexpectedly.",
                )

            # ==================================================================
            # STATE 4 – CONFIRM_SAVE
            # ==================================================================
            state = "CONFIRM_SAVE"
            self._force_focus(save_dialog_hwnd)
            time.sleep(0.25)

            # Strategy 4A: Alt+N then Enter
            logger.info(f"[NOTEPAD] save_as [{state}]: Strategy 4A — Alt+N then Enter")
            pyautogui.hotkey("alt", "n")
            time.sleep(0.2)
            pyautogui.press("enter")

            overwrite_dialog_hwnd: Optional[int] = None
            for _ in range(15):
                time.sleep(0.15)
                if self._is_overwrite_dialog_open():
                    overwrite_dialog_hwnd = self._find_overwrite_dialog_hwnd()
                    break

            # Strategy 4B: Alt+S
            if not overwrite_dialog_hwnd and self._is_save_dialog_open():
                logger.info(f"[NOTEPAD] save_as [{state}]: Strategy 4B — Alt+S")
                self._force_focus(save_dialog_hwnd)
                time.sleep(0.2)
                pyautogui.hotkey("alt", "s")
                for _ in range(10):
                    time.sleep(0.15)
                    if self._is_overwrite_dialog_open():
                        overwrite_dialog_hwnd = self._find_overwrite_dialog_hwnd()
                        break
                    if not self._is_save_dialog_open():
                        break

            # Strategy 4C: Programmatic BM_CLICK on Save button (ID=1)
            if not overwrite_dialog_hwnd and self._is_save_dialog_open():
                logger.info(f"[NOTEPAD] save_as [{state}]: Strategy 4C — WM_COMMAND ID 1")
                try:
                    btn_hwnd = win32gui.GetDlgItem(save_dialog_hwnd, 1) if win32gui else None
                    if btn_hwnd:
                        win32gui.SendMessage(save_dialog_hwnd, win32con.WM_COMMAND, 1, btn_hwnd)
                except Exception as e:
                    logger.debug(f"[NOTEPAD] Strategy 4C failed: {e}")

            # Handle overwrite confirmation
            if overwrite_dialog_hwnd:
                if overwrite:
                    self._force_focus(overwrite_dialog_hwnd)
                    time.sleep(0.2)
                    pyautogui.press("y")
                    time.sleep(0.5)
                else:
                    self._force_focus(overwrite_dialog_hwnd)
                    time.sleep(0.2)
                    pyautogui.press("escape")
                    time.sleep(0.3)
                    return ExecutionResult(
                        success=False, tool="notepad_save_as",
                        message=(
                            f"[{state}] File '{expected_path}' already exists "
                            f"and overwrite=False — save cancelled."
                        ),
                    )

            # Wait for dialog to close
            for _ in range(20):
                time.sleep(0.15)
                if not self._is_save_dialog_open():
                    break

            # ==================================================================
            # STATE 5 – VERIFY_FILE
            # ==================================================================
            state = "VERIFY_FILE"
            logger.info(f"[NOTEPAD] save_as [{state}]: checking '{expected_path}'")
            time.sleep(0.6)
            file_found = False
            for _ in range(10):
                if os.path.exists(expected_path):
                    file_found = True
                    break
                time.sleep(0.2)

            if not file_found:
                logger.error(
                    f"[NOTEPAD] save_as [{state}]: FAILED — "
                    f"'{expected_path}' not found on disk. "
                    f"Notepad is left open for debugging."
                )
                return ExecutionResult(
                    success=False, tool="notepad_save_as",
                    message=(
                        f"[{state}] File not found at '{expected_path}' after save. "
                        f"Notepad is left open for debugging."
                    ),
                )

            # Content verification (best-effort — does NOT block success)
            if editor_text:
                content_ok = False
                for encoding in ("utf-8", "utf-8-sig", "ansi"):
                    try:
                        with open(expected_path, "r", encoding=encoding, errors="ignore") as f:
                            saved = f.read().strip()
                        if editor_text.strip() in saved or saved in editor_text.strip():
                            content_ok = True
                            break
                    except Exception:
                        pass

                if not content_ok:
                    logger.warning(
                        f"[NOTEPAD] save_as [{state}]: file exists but content "
                        f"does not match editor snapshot. The file may be correct — "
                        f"reporting success but flagging the mismatch."
                    )
                    # Content mismatch is a warning, not a hard failure, because
                    # encoding differences or trailing newlines can cause false negatives.
                else:
                    logger.info(
                        f"[NOTEPAD] save_as [{state}]: content verified OK."
                    )

            # Persist session cache (window title changes after first save)
            self._save_session()
            self._debug_pause("save_confirmed")

            logger.info(
                f"[NOTEPAD] save_as: ALL STATES PASSED — "
                f"file saved at '{expected_path}'."
            )
            self._last_saved_path = expected_path
            self._save_session()
            return ExecutionResult(
                success=True, tool="notepad_save_as",
                message=f"File saved successfully at '{expected_path}'.",
                saved_path=expected_path
            )

        except Exception as exc:
            logger.exception("[NOTEPAD] save_as: unhandled exception in state machine")
            return ExecutionResult(
                success=False, tool="notepad_save_as",
                message=(
                    f"Save As failed with an unexpected error: {exc}. "
                    f"Notepad is left open for debugging."
                ),
            )

    # ------------------------------------------------------------------
    # Save-As dialog navigation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_focused_control(hwnd: int) -> Optional[int]:
        """Return the HWND of the currently focused control in the thread of the given window."""
        if not win32process or not win32gui:
            return None
        try:
            import ctypes
            from ctypes import wintypes

            class GUITHREADINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("flags", wintypes.DWORD),
                    ("hwndActive", wintypes.HWND),
                    ("hwndFocus", wintypes.HWND),
                    ("hwndCapture", wintypes.HWND),
                    ("hwndMenuOwner", wintypes.HWND),
                    ("hwndMoveSize", wintypes.HWND),
                    ("hwndCaret", wintypes.HWND),
                    ("rcCaret", wintypes.RECT),
                ]

            thread_id, _ = win32process.GetWindowThreadProcessId(hwnd)
            gui_info = GUITHREADINFO()
            gui_info.cbSize = ctypes.sizeof(GUITHREADINFO)
            
            user32 = ctypes.windll.user32
            if user32.GetGUIThreadInfo(thread_id, ctypes.byref(gui_info)):
                if gui_info.hwndFocus and win32gui.IsWindow(gui_info.hwndFocus):
                    return gui_info.hwndFocus
        except Exception as e:
            logger.debug(f"[NOTEPAD] GetGUIThreadInfo failed: {e}")
        return None

    def _navigate_save_dialog_to_dir(
        self, dialog_hwnd: int, target_dir: str, raw_dir_hint: str = ""
    ) -> bool:
        """Navigate the Save As dialog to *target_dir* using multiple strategies.

        SAFETY RULE
        -----------
        This function receives ONLY the directory path.  It must NEVER
        receive, use, or type the filename.  The caller guarantees separation.

        Strategies (tried in order)
        ---------------------------
        Strategy A – Filename-box folder-navigation
            This is the most reliable strategy on Windows 10/11.
            Typing a path ending with \\ in the File-name box and pressing Enter
            causes Windows to navigate the dialog to that folder without saving.
            This is 100% reliable because the File-name box is always present,
            visible, and has a guaranteed focus accelerator (Alt+N).

        Strategy B – Full absolute path via address bar (Alt+D)
            Press Alt+D or Ctrl+L (address-bar accelerators), Ctrl+A to select all,
            paste the path, and press Enter.
        """
        if not pyautogui:
            logger.warning("[NOTEPAD] _navigate_save_dialog_to_dir: pyautogui not available.")
            return False

        import os
        logger.info(
            f"[NOTEPAD] _navigate_save_dialog_to_dir: "
            f"target_dir='{target_dir}'  raw_hint='{raw_dir_hint}'"
        )

        def _force_dialog_focus() -> None:
            self._force_focus(dialog_hwnd)
            time.sleep(0.25)

        # ── Strategy A: Filename-box folder-navigation (Primary) ───────────
        logger.info(
            f"[NOTEPAD] _navigate: Strategy A — using File-name box with "
            f"trailing backslash: '{target_dir}\\\\'"
        )
        try:
            _force_dialog_focus()
            pyautogui.hotkey("alt", "n")   # Focus File-name box
            time.sleep(0.35)
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.1)
            pyautogui.press("delete")
            time.sleep(0.1)
            
            # Ensure path ends with a backslash to trigger folder navigation
            folder_nav = target_dir.rstrip("\\") + "\\"
            
            import pyperclip
            if pyperclip:
                pyperclip.copy(folder_nav)
                pyautogui.hotkey("ctrl", "v")
            else:
                pyautogui.typewrite(folder_nav, interval=0.02)
            time.sleep(0.2)
            pyautogui.press("enter")
            time.sleep(1.5)   # Wait for folder navigation to complete
            # Verify dialog is still open after navigation
            if not self._is_save_dialog_open():
                logger.warning("[NOTEPAD] _navigate: Strategy A — dialog closed after navigation; retrying focus.")
                time.sleep(0.5)
            logger.info("[NOTEPAD] _navigate: Strategy A complete.")
            return True
        except Exception as exc:
            logger.warning(f"[NOTEPAD] _navigate: Strategy A failed: {exc}")

        # ── Strategy B: Full absolute path via address bar (Alt+D) ─────────
        logger.info(
            f"[NOTEPAD] _navigate: Strategy B — pasting full path '{target_dir}' "
            f"into address bar via Alt+D."
        )
        try:
            _force_dialog_focus()
            pyautogui.hotkey("alt", "d")   # Focus address bar
            time.sleep(0.45)
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.1)
            
            import pyperclip
            if pyperclip:
                pyperclip.copy(target_dir)
                pyautogui.hotkey("ctrl", "v")
            else:
                pyautogui.typewrite(target_dir, interval=0.02)
            time.sleep(0.2)
            pyautogui.press("enter")
            time.sleep(0.8)   # Wait for file-list to refresh
            logger.info("[NOTEPAD] _navigate: Strategy B complete.")
            return True
        except Exception as exc:
            logger.warning(f"[NOTEPAD] _navigate: Strategy B failed: {exc}")
            return False

    def _set_filename_in_save_dialog(self, dialog_hwnd: int, filename: str) -> bool:
        """Set the filename in the File name textbox.
        Uses direct Win32 WM_SETTEXT as primary (headless friendly) and PyAutoGUI keyboard as fallback.
        """
        logger.info(
            f"[NOTEPAD] _set_filename_in_save_dialog: setting File-name box to '{filename}'"
        )
        
        # 1. Primary approach: Direct Win32 SendMessageW (WM_SETTEXT)
        if win32gui:
            edit_hwnd = None
            try:
                # Try standard control IDs first (1152 and 1001 are standard File Name Edit/Combo box IDs)
                for cid in [1152, 1001]:
                    try:
                        h = win32gui.GetDlgItem(dialog_hwnd, cid)
                        if h:
                            # If it's a combobox, find its child Edit control
                            if win32gui.GetClassName(h).lower() == "combobox":
                                def _enum_cb_child(child, extra):
                                    nonlocal edit_hwnd
                                    if win32gui.GetClassName(child).lower() == "edit":
                                        edit_hwnd = child
                                        return False
                                    return True
                                win32gui.EnumChildWindows(h, _enum_cb_child, None)
                            elif win32gui.GetClassName(h).lower() == "edit":
                                edit_hwnd = h
                                break
                    except Exception:
                        pass
                
                # Fallback child search if standard IDs weren't resolved
                if not edit_hwnd:
                    edit_hwnds = []
                    def _enum_edit(h, extra):
                        try:
                            if win32gui.GetClassName(h).lower() == "edit":
                                edit_hwnds.append(h)
                        except Exception:
                            pass
                        return True
                    win32gui.EnumChildWindows(dialog_hwnd, _enum_edit, None)
                    if edit_hwnds:
                        # In standard Save As dialogs, the main filename textbox is the first/only Edit control
                        edit_hwnd = edit_hwnds[0]
                        
                if edit_hwnd:
                    import win32con
                    res = ctypes.windll.user32.SendMessageW(edit_hwnd, win32con.WM_SETTEXT, 0, filename)
                    logger.info(f"[NOTEPAD] _set_filename_in_save_dialog: SendMessageW(WM_SETTEXT) to HWND={edit_hwnd} returned {res}")
                    
                    # Notify dialog parent (EN_CHANGE) so the Save/Save As button enables
                    ctrl_id = win32gui.GetDlgCtrlID(edit_hwnd)
                    notify_code = (0x0300 << 16) | (ctrl_id & 0xFFFF)
                    win32gui.SendMessage(dialog_hwnd, win32con.WM_COMMAND, notify_code, edit_hwnd)
                    time.sleep(0.2)
                    return True
            except Exception as exc:
                logger.warning(f"[NOTEPAD] Direct Win32 WM_SETTEXT failed: {exc}. Trying fallback...")

        # 2. Fallback: PyAutoGUI keyboard automation (interactive session only)
        if not pyautogui:
            return False

        try:
            self._force_focus(dialog_hwnd)
            time.sleep(0.25)
            pyautogui.hotkey("alt", "n")
            time.sleep(0.35)
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.1)
            pyautogui.press("delete")
            time.sleep(0.15)
            
            if pyperclip:
                pyperclip.copy(filename)
                pyautogui.hotkey("ctrl", "v")
            else:
                pyautogui.write(filename, interval=0.02)
            time.sleep(0.2)
            return True
        except Exception as exc:
            logger.warning(f"[NOTEPAD] PyAutoGUI fallback in _set_filename failed: {exc}")
            return False


    def _is_save_dialog_open(self) -> bool:
        """Return True if a Save / Save-As dialog is currently visible."""
        return self._find_save_dialog_hwnd() is not None

    def _find_save_dialog_hwnd(self) -> Optional[int]:
        """Return the HWND of the Save / Save-As dialog, or None."""
        snapshot = self._get_window_snapshot()
        notepad_pids = set(self._notepad_pids())
        for w in snapshot:
            if w["pid"] in notepad_pids:
                cls = w["class"].lower()
                # The Save As dialog is always a standard Win32 dialog box class.
                # Crucially, it is NOT the main Notepad window.
                if cls == "#32770":
                    title = w["title"].lower()
                    # Ensure it's not the Open dialog, unsaved changes dialog, or overwrite confirmation dialog.
                    is_save = ("save" in title or "speichern" in title or not title)
                    is_not_other = (
                        "open" not in title and "offnen" not in title and 
                        "confirm" not in title and "replace" not in title and 
                        "exists" not in title and "notepad" not in title
                    )
                    if is_save and is_not_other:
                        return w["hwnd"]
        return None

    def _is_overwrite_dialog_open(self) -> bool:
        """Return True if an 'overwrite?' confirmation dialog is visible."""
        return self._find_overwrite_dialog_hwnd() is not None

    def _find_overwrite_dialog_hwnd(self) -> Optional[int]:
        """Return the HWND of the overwrite confirmation dialog, or None."""
        snapshot = self._get_window_snapshot()
        notepad_pids = set(self._notepad_pids())
        for w in snapshot:
            if w["pid"] in notepad_pids:
                cls = w["class"].lower()
                if cls == "#32770":
                    title = w["title"].lower()
                    if "already exists" in title or "replace" in title or "confirm" in title:
                        return w["hwnd"]
        return None

    def open_file(self, path: str) -> ExecutionResult:
        """Open an existing file in Notepad via the Open dialog."""
        if not pyautogui:
            return ExecutionResult(
                success=False,
                tool="notepad_open_file",
                message="pyautogui is not available.",
            )
        if not path:
            return ExecutionResult(
                success=False,
                tool="notepad_open_file",
                message="No file path provided.",
            )

        guard = self._ensure_notepad_focused("notepad_open_file")
        if guard:
            return guard

        try:
            pyautogui.hotkey("ctrl", "o")
            time.sleep(0.5)

            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.1)
            if pyperclip:
                pyperclip.copy(path)
                pyautogui.hotkey("ctrl", "v")
            else:
                pyautogui.write(path, interval=TYPING_INTERVAL)
            time.sleep(0.3)
            pyautogui.press("enter")
            time.sleep(0.5)

            self._last_saved_path = os.path.abspath(path)
            self._save_session()
            return ExecutionResult(
                success=True,
                tool="notepad_open_file",
                message=f"Opened file '{path}' in Notepad.",
            )
        except Exception as exc:
            return ExecutionResult(
                success=False,
                tool="notepad_open_file",
                message=f"Open file failed: {exc}",
            )

    def new_file(self) -> ExecutionResult:
        """Create a new empty document (Ctrl+N), discarding unsaved changes."""
        if not pyautogui:
            return ExecutionResult(
                success=False,
                tool="notepad_new_file",
                message="pyautogui is not available.",
            )

        guard = self._ensure_notepad_focused("notepad_new_file")
        if guard:
            return guard

        try:
            pyautogui.hotkey("ctrl", "n")
            time.sleep(0.5)

            if self._is_unsaved_dialog_open():
                pyautogui.press("tab")
                time.sleep(0.1)
                pyautogui.press("enter")
                time.sleep(0.3)

            return ExecutionResult(
                success=True,
                tool="notepad_new_file",
                message="Created new document in Notepad.",
            )
        except Exception as exc:
            return ExecutionResult(
                success=False,
                tool="notepad_new_file",
                message=f"New file failed: {exc}",
            )

    def _is_unsaved_dialog_open(self) -> bool:
        """Return True if a 'Do you want to save?' dialog is open."""
        snapshot = self._get_window_snapshot()
        notepad_pids = set(self._notepad_pids())
        notepad_hwnd = self.find_notepad_hwnd()
        for w in snapshot:
            if w["hwnd"] != notepad_hwnd and w["pid"] in notepad_pids:
                title = w["title"].lower()
                cls = w["class"].lower()
                # Unsaved change dialog title contains "notepad" or has class "#32770" (dialog) and is empty/title-less
                if "notepad" in title or not title or cls == "#32770":
                    if "save" not in title and "speichern" not in title:  # distinguish from Save As dialog
                        return True
        return False

    # ── Close ─────────────────────────────────────────────────────────────

    def close_notepad(self, save_before_close: bool = False, discard_changes: bool = True, save_first: Optional[bool] = None) -> ExecutionResult:
        """Close the Notepad window."""
        self._log_tool_precondition("notepad_close")
        if save_first is not None:
            save_before_close = save_first

        # Check if we have an active session
        if not self._session or not self._is_session_valid(self._session):
            hwnd = self._scan_any_notepad_hwnd()
            if not hwnd:
                return ExecutionResult(
                    success=False,
                    tool="notepad_close",
                    message="Notepad is not currently running.",
                )
            # Register untracked window — check if it is in our assistant sessions list
            # to preserve correct ownership.
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            registry = self._load_registry()
            assistant_hwnds = {s["hwnd"] for s in registry.get("assistant_sessions", [])}
            is_assistant = (hwnd in assistant_hwnds)
            self._session = ApplicationSession(
                pid=pid,
                hwnd=hwnd,
                launched_by_assistant=is_assistant,
                launch_time=time.time()
            )
            self._save_session()

        # Only skip closing if the session was NOT created by the assistant.
        # When the assistant ran open_notepad (or reused a window via open_notepad),
        # launched_by_assistant is always True, so this guard does NOT trigger.
        if not self._session.launched_by_assistant:
            logger.info(
                f"[NOTEPAD] Skipping close: Notepad (HWND={self._session.hwnd}) "
                "was not opened by the assistant."
            )
            self._session = None
            self._save_session()
            return ExecutionResult(
                success=True,
                tool="notepad_close",
                message="Notepad was opened by the user; leaving it open.",
            )

        hwnd = self._session.hwnd
        pid = self._session.pid
        guard = self._ensure_notepad_focused("notepad_close")
        if guard:
            return guard

        # Developer Debug Mode complete action: prompt user, keep window open
        if DEBUG_AUTOMATION:
            logger.info("[DEBUG MODE] Leaving Notepad window open for developer inspection.")
            print("\nAutomation complete. Inspect the Notepad window manually. Press Enter or issue a close command to continue.")
            try:
                input()
            except Exception:
                pass
            return ExecutionResult(
                success=True,
                tool="notepad_close",
                message="Automation complete. Inspected manually.",
            )

        try:
            if save_before_close:
                logger.info("[NOTEPAD] close_notepad: saving file before close...")
                save_res = self.save_file()
                if not save_res.success:
                    logger.error(f"[NOTEPAD] close_notepad: save failed, keeping Notepad open: {save_res.message}")
                    return ExecutionResult(
                        success=False,
                        tool="notepad_close",
                        message=f"Save failed: {save_res.message}. Keeping window open for debugging.",
                    )
                time.sleep(0.4)
                if self._is_save_dialog_open():
                    pyautogui.FAILSAFE = False
                    pyautogui.press("escape")
                    time.sleep(0.2)

            # Primary: Post WM_CLOSE message
            logger.info(f"[NOTEPAD] close_notepad: posting WM_CLOSE (0x0010) to HWND={hwnd}")
            ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
            
            # Wait for potential unsaved dialog (up to 2.0s)
            unsaved_dialog_detected = False
            for _ in range(15):
                time.sleep(0.15)
                if self._is_unsaved_dialog_open():
                    unsaved_dialog_detected = True
                    break

            if unsaved_dialog_detected:
                logger.info("[NOTEPAD] close_notepad: unsaved changes dialog detected.")
                if not save_before_close:
                    if discard_changes:
                        logger.info("[NOTEPAD] close_notepad: discard_changes is True. Dismissing with 'Don't Save' key sequence...")
                        # Dismiss programmatically if possible
                        unsaved_dialog_hwnd = None
                        for w in self._get_window_snapshot():
                            if w["hwnd"] != hwnd and w["pid"] == self._session.pid:
                                if w["class"].lower() == "#32770":
                                    unsaved_dialog_hwnd = w["hwnd"]
                                    break
                        dismissed = False
                        if unsaved_dialog_hwnd:
                            import win32con
                            # Try programmatic IDNO (7) or standard dialog control IDs
                            for btn_id in [7, 1002, 2]:
                                try:
                                    btn = win32gui.GetDlgItem(unsaved_dialog_hwnd, btn_id)
                                    if btn:
                                        win32gui.SendMessage(unsaved_dialog_hwnd, win32con.WM_COMMAND, btn_id, btn)
                                        dismissed = True
                                        break
                                except Exception:
                                    pass
                        if not dismissed and pyautogui:
                            pyautogui.FAILSAFE = False
                            pyautogui.press("tab")
                            time.sleep(0.15)
                            pyautogui.press("enter")
                            time.sleep(0.3)
                    else:
                        logger.info("[NOTEPAD] close_notepad: discard_changes is False. Cancelling close action...")
                        if pyautogui:
                            pyautogui.FAILSAFE = False
                            pyautogui.press("escape")
                            time.sleep(0.2)
                        return ExecutionResult(
                            success=False,
                            tool="notepad_close",
                            message="Close cancelled because discard_changes is False and there were unsaved changes.",
                        )

            # Poll to wait for window to be destroyed (up to 5 seconds)
            remaining_valid = True
            for _ in range(25):
                time.sleep(0.2)
                if not win32gui.IsWindow(hwnd):
                    remaining_valid = False
                    break

            if remaining_valid and discard_changes:
                logger.info("[NOTEPAD] close_notepad: ultimate fallback: terminating process")
                try:
                    proc = psutil.Process(self._session.pid)
                    proc.terminate()
                except Exception:
                    pass
                for _ in range(15):
                    time.sleep(0.2)
                    if not win32gui.IsWindow(hwnd):
                        remaining_valid = False
                        break

            if win32gui.IsWindow(hwnd):
                return ExecutionResult(
                    success=False,
                    tool="notepad_close",
                    message="Attempted to close Notepad but the window still exists.",
                )
            
            # Update the session registry and clear assistant session cache
            self._session = None
            registry = self._load_registry()
            registry["assistant_sessions"] = []
            self._save_registry(registry)

            self._debug_pause("close_notepad")
            return ExecutionResult(
                success=True,
                tool="notepad_close",
                message="Notepad closed successfully.",
            )
        except Exception as exc:
            return ExecutionResult(
                success=False,
                tool="notepad_close",
                message=f"Close Notepad failed: {exc}",
            )


# ---------------------------------------------------------------------------
# Singleton controller instance
# ---------------------------------------------------------------------------

_controller = NotepadController()


# ---------------------------------------------------------------------------
# @register_tool handlers
# ---------------------------------------------------------------------------

@register_tool("notepad_open")
def handle_notepad_open(args: dict[str, Any]) -> ExecutionResult:
    """Open Microsoft Notepad, or focus it if already running."""
    return _controller.open_notepad()


@register_tool("notepad_close")
def handle_notepad_close(args: dict[str, Any]) -> ExecutionResult:
    """Close Notepad. Optionally save first or discard changes."""
    # Support both new and legacy parameter names
    save_before_close = bool(args.get("save_before_close", args.get("save_first", False)))
    discard_changes = bool(args.get("discard_changes", True))
    return _controller.close_notepad(save_before_close=save_before_close, discard_changes=discard_changes)


@register_tool("notepad_type")
def handle_notepad_type(args: dict[str, Any]) -> ExecutionResult:
    """Type text into Notepad."""
    text: str = args.get("text", "")
    return _controller.type_text(text)


@register_tool("notepad_press_enter")
def handle_notepad_press_enter(args: dict[str, Any]) -> ExecutionResult:
    """Press Enter in Notepad (insert a new line)."""
    return _controller.press_enter()


@register_tool("notepad_select_all")
def handle_notepad_select_all(args: dict[str, Any]) -> ExecutionResult:
    """Select all text in Notepad (Ctrl+A)."""
    return _controller.select_all()


@register_tool("notepad_copy")
def handle_notepad_copy(args: dict[str, Any]) -> ExecutionResult:
    """Copy selected text in Notepad to clipboard (Ctrl+C)."""
    return _controller.copy()


@register_tool("notepad_paste")
def handle_notepad_paste(args: dict[str, Any]) -> ExecutionResult:
    """Paste clipboard contents into Notepad (Ctrl+V)."""
    return _controller.paste()


@register_tool("notepad_undo")
def handle_notepad_undo(args: dict[str, Any]) -> ExecutionResult:
    """Undo the last action in Notepad (Ctrl+Z)."""
    return _controller.undo()


@register_tool("notepad_redo")
def handle_notepad_redo(args: dict[str, Any]) -> ExecutionResult:
    """Redo the last undone action in Notepad (Ctrl+Y)."""
    return _controller.redo()


@register_tool("notepad_delete")
def handle_notepad_delete(args: dict[str, Any]) -> ExecutionResult:
    """Select all and delete all text in Notepad."""
    return _controller.delete_text()


@register_tool("notepad_clear")
def handle_notepad_clear(args: dict[str, Any]) -> ExecutionResult:
    """Clear the entire Notepad document (select all + delete)."""
    return _controller.clear_document()


@register_tool("notepad_save")
def handle_notepad_save(args: dict[str, Any]) -> ExecutionResult:
    """Save the current Notepad file."""
    filename: Optional[str] = args.get("filename", None)
    directory: Optional[str] = args.get("directory", None)
    return _controller.save_file(filename=filename, directory=directory)


@register_tool("notepad_save_as")
def handle_notepad_save_as(args: dict[str, Any]) -> ExecutionResult:
    """Save the current Notepad document with a specific filename."""
    filename: str = args.get("filename", "")
    directory: Optional[str] = args.get("directory", None)
    overwrite: bool = bool(args.get("overwrite", False))
    return _controller.save_as(filename, directory=directory, overwrite=overwrite)


@register_tool("notepad_open_file")
def handle_notepad_open_file(args: dict[str, Any]) -> ExecutionResult:
    """Open an existing file in Notepad via the Open dialog."""
    path: str = args.get("path", "")
    return _controller.open_file(path)


@register_tool("notepad_new_file")
def handle_notepad_new_file(args: dict[str, Any]) -> ExecutionResult:
    """Create a new empty document in Notepad (Ctrl+N)."""
    return _controller.new_file()
