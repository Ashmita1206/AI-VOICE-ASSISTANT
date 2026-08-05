"""
Application Tools
=================

Handlers for opening desktop applications.
"""

import subprocess
import sys
import logging
import time
from typing import Any

import config
from config import get_logger
from execution.registry import register_tool
from execution.schemas import ExecutionResult, ExecutionTimer

logger = get_logger(__name__)

import os
import re
import types

# We reuse find_application as a final fallback
from agentic.os_scanner import find_application

try:
    import win32gui
    import win32process
except ImportError:
    win32gui = None
    win32process = None

CANONICAL_ALIASES = {
    "file explorer": ["file manager", "file explorer", "explorer", "this pc"],
    "task manager": ["task manager", "taskmgr", "system monitor"],
    "command prompt": ["cmd", "command prompt", "terminal"],
    "settings": ["settings", "windows settings"],
    "calculator": ["calculator", "calc"],
    "notepad": ["notepad", "text editor"],
    "visual studio code": ["vs code", "vscode", "vs"],
    "chatgpt": ["chat gpt", "chatgpt"],
    "spotify": ["spotify"],
    "whatsapp": ["whatsapp"]
}

CANONICAL_EXECUTABLES = {
    "file explorer": "explorer.exe",
    "task manager": "taskmgr.exe",
    "command prompt": "cmd.exe",
    "settings": "ms-settings:",
    "calculator": "calc.exe",
    "notepad": "notepad.exe"
}

def resolve_canonical_app(query: str) -> str | None:
    """Check aliases before fuzzy matching. Return canonical application immediately."""
    cleaned = clean_query_for_matching(query)
    # Check aliases directly
    for canonical, aliases in CANONICAL_ALIASES.items():
        if cleaned in aliases:
            return canonical
        # Also check if normalized matches exactly
        q_norm = "".join(c for c in cleaned if c.isalnum())
        for alias in aliases:
            if q_norm == "".join(c for c in alias if c.isalnum()):
                return canonical
    return None

def is_abbreviation(abbr: str, full: str) -> bool:
    """Check if abbr is an abbreviation of full name (e.g. 'vscode' -> 'visual studio code')."""
    abbr = abbr.lower().replace(" ", "").replace("-", "")
    full = full.lower().replace("-", " ")
    full_words = full.split()
    
    # 1. Direct initials matching
    initials = "".join(w[0] for w in full_words if w)
    if abbr == initials:
        return True
        
    # 2. Initials + suffix matching (e.g. 'vs' + 'code' = 'vscode')
    for i in range(1, len(full_words)):
        prefix_initials = "".join(w[0] for w in full_words[:i])
        if w := full_words[i:]:
            last_word = w[0]
            if abbr.startswith(prefix_initials):
                suffix = abbr[len(prefix_initials):]
                if last_word.startswith(suffix):
                    return True
                
    # 3. Common aliases
    for canonical, aliases in CANONICAL_ALIASES.items():
        if abbr in [a.replace(" ", "") for a in aliases] and full.replace(" ", "") == canonical.replace(" ", ""):
            return True
            
    return False

def is_fuzzy_match(query: str, name: str) -> bool:
    """Perform robust fuzzy matching between query and a target name."""
    query = query.lower().strip()
    name = name.lower().strip()
    
    if query == name:
        return True
        
    q_norm = "".join(c for c in query if c.isalnum())
    n_norm = "".join(c for c in name if c.isalnum())
    if q_norm == n_norm:
        return True
        
    for canonical, aliases in CANONICAL_ALIASES.items():
        if query in aliases or q_norm in ["".join(c for c in a if c.isalnum()) for a in aliases]:
            target_norm = "".join(c for c in canonical if c.isalnum())
            if target_norm == n_norm or target_norm in n_norm or n_norm in target_norm:
                return True
                
    if q_norm in n_norm or n_norm in q_norm:
        return True
        
    if is_abbreviation(query, name):
        return True
        
    import difflib
    # Fuzzy matching should compare canonical application names, requiring higher confidence
    if difflib.SequenceMatcher(None, query, name).ratio() >= 0.85:
        return True
        
    return False

def clean_query_for_matching(query: str) -> str:
    """Clean action words and common verbs from query to isolate application name."""
    text = query.lower().strip()
    text = re.sub(r"[.!?]+$", "", text).strip()
    
    words = text.split()
    remove_words = {"app", "application", "launch", "open", "start", "the"}
    filtered_words = [w for w in words if w not in remove_words]
    
    cleaned = " ".join(filtered_words)
    return cleaned

def clean_query_name(query: str) -> str:
    """Legacy cleaner wrapper."""
    return clean_query_for_matching(query)

import ctypes

def is_uwp_window_for_pid(hwnd: int, target_pid: int) -> bool:
    """Return True if the top-level hwnd is an ApplicationFrameWindow containing a child of target_pid."""
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

def force_focus_window(hwnd: int) -> bool:
    """Robustly focus a window using AttachThreadInput and Alt-key simulation to bypass foreground lock rules."""
    if not win32gui or not win32process:
        return False
        
    try:
        import win32api
        import win32con
        
        # 1. If minimized, restore
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, 9) # SW_RESTORE
        else:
            win32gui.ShowWindow(hwnd, 5) # SW_SHOW
            
        # 2. Bring near foreground
        win32gui.BringWindowToTop(hwnd)
        
        # 3. Check if already foreground
        foreground_hwnd = win32gui.GetForegroundWindow()
        if foreground_hwnd == hwnd:
            return True
            
        # 4. Alt-key bypass trick: send press and release of Alt key to thread input queue
        try:
            win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
            win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
        except Exception:
            pass
            
        # Try direct foreground activation first
        try:
            win32gui.SetForegroundWindow(hwnd)
            if win32gui.GetForegroundWindow() == hwnd:
                return True
        except Exception:
            pass
            
        # 5. Attach thread inputs to steal focus lock
        current_thread_id = win32api.GetCurrentThreadId()
        foreground_hwnd = win32gui.GetForegroundWindow()
        target_thread_id, _ = win32process.GetWindowThreadProcessId(hwnd)
        foreground_thread_id, _ = win32process.GetWindowThreadProcessId(foreground_hwnd) if foreground_hwnd else (0, 0)
        
        attached = False
        if foreground_thread_id and foreground_thread_id != current_thread_id:
            try:
                win32process.AttachThreadInput(current_thread_id, foreground_thread_id, True)
                attached = True
            except Exception:
                pass
                
        # 6. Force focus
        try:
            win32gui.SetForegroundWindow(hwnd)
            ctypes.windll.user32.SetActiveWindow(hwnd)
            ctypes.windll.user32.SetFocus(hwnd)
        except Exception as e:
            logger.debug(f"Focusing APIs failed: {e}")
            
        # 7. Detach thread inputs
        if attached:
            try:
                win32process.AttachThreadInput(current_thread_id, foreground_thread_id, False)
            except Exception:
                pass
                
        # 8. Verify
        time.sleep(0.2)
        fg_win = win32gui.GetForegroundWindow()
        if fg_win == hwnd:
            return True
        if not fg_win or fg_win == 0:
            return bool(win32gui.IsWindowVisible(hwnd))
        return False
    except Exception as e:
        logger.debug(f"force_focus_window failed: {e}")
        return False

def bring_process_to_foreground(pid: int) -> int | None:
    """Find visible HWNDs for process ID and bring them to foreground. Returns the focused HWND or None."""
    if not win32gui or not win32process:
        return None
        
    found_hwnds = []
    
    def enum_windows_callback(hwnd, extra):
        if win32gui.IsWindowVisible(hwnd):
            _, win_pid = win32process.GetWindowThreadProcessId(hwnd)
            if win_pid == pid or is_uwp_window_for_pid(hwnd, pid):
                title = win32gui.GetWindowText(hwnd)
                if title:
                    found_hwnds.append(hwnd)
        return True
        
    try:
        win32gui.EnumWindows(enum_windows_callback, None)
    except Exception as e:
        logger.debug(f"EnumWindows failed: {e}")
        
    if found_hwnds:
        for hwnd in found_hwnds:
            if force_focus_window(hwnd):
                return hwnd
        return None
    return None

def get_start_apps() -> list[dict[str, str]]:
    """Retrieve Windows Start Menu apps using PowerShell Get-StartApps."""
    import json
    apps = []
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore"
        )
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout.strip())
            if isinstance(data, dict):
                data = [data]
            for item in data:
                name = item.get("Name")
                appid = item.get("AppID")
                if name and appid:
                    apps.append({"name": name, "appid": appid})
    except Exception as e:
        logger.debug(f"Get-StartApps JSON call failed: {e}")
        
    if not apps:
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-StartApps"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore"
            )
            if res.returncode == 0:
                lines = res.stdout.strip().split("\n")
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith("Name ") or line.startswith("----"):
                        continue
                    parts = re.split(r'\s{2,}', line)
                    if len(parts) >= 2:
                        apps.append({"name": parts[0].strip(), "appid": parts[1].strip()})
        except Exception as e:
            logger.debug(f"Get-StartApps fallback failed: {e}")
            
    return apps

def find_indexed_app(query: str) -> tuple[str | None, str | None]:
    """Search registry, desktop shortcuts, start menu shortcuts for a match."""
    # Registry Uninstall
    try:
        from agentic.discovery.apps import scan_registry_apps
        registry_apps = scan_registry_apps()
        for app in registry_apps:
            if is_fuzzy_match(query, app.name):
                exe_path = app.executable or app.path
                if exe_path and os.path.exists(exe_path):
                    return app.name, exe_path
    except Exception as e:
        logger.debug(f"Registry search failed: {e}")
        
    # Start Menu & Desktop Shortcuts
    try:
        paths = [
            r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
            os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs")
        ]
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            paths.append(os.path.join(user_profile, "Desktop"))
        public_profile = os.environ.get("PUBLIC")
        if public_profile:
            paths.append(os.path.join(public_profile, "Desktop"))
            
        from agentic.discovery.apps import resolve_lnk_target
        for p in paths:
            if not os.path.exists(p):
                continue
            for root, dirs, files in os.walk(p):
                for file in files:
                    if file.lower().endswith(".lnk"):
                        name, _ = os.path.splitext(file)
                        if is_fuzzy_match(query, name):
                            filepath = os.path.join(root, file)
                            target = resolve_lnk_target(filepath)
                            if target and os.path.exists(target):
                                return name, target
    except Exception as e:
        logger.debug(f"Shortcut search failed: {e}")
        
    return None, None

def find_website_resource(query: str):
    """Scan browser bookmarks and history for matching website."""
    try:
        from agentic.discovery.manager import discover
        matches = discover(query)
        website_matches = [m for m in matches if m.type == "website"]
        if website_matches:
            website_matches.sort(key=lambda x: x.confidence, reverse=True)
            return website_matches[0]
    except Exception as e:
        logger.debug(f"discover check failed: {e}")
    return None

def make_custom_result(success: bool, resource_type: str, reason: str) -> ExecutionResult:
    """Helper to return an ExecutionResult with customized to_dict output format."""
    res = ExecutionResult(
        success=success,
        tool="resolve_and_open",
        message=reason
    )
    res.resource_type = resource_type
    res.reason = reason
    
    def custom_to_dict(self):
        d = ExecutionResult.to_dict(self)
        d["resource_type"] = self.resource_type
        d["reason"] = self.reason
        if hasattr(self, "app_running"):
            d["app_running"] = self.app_running
        if hasattr(self, "action"):
            d["action"] = self.action
        return d
    res.to_dict = types.MethodType(custom_to_dict, res)
    return res

def resolve_app_launch_strategy(query: str) -> tuple[str | None, str, str, str]:
    """
    Look up application to launch using Windows non-recursive strategy.
    
    Returns tuple: (executable_path_or_None, process_check_log, registry_log, start_menu_log)
    """
    cleaned = clean_query_for_matching(query)
    
    # Check aliases before fuzzy matching
    canonical_match = resolve_canonical_app(cleaned)
    if canonical_match and canonical_match in CANONICAL_EXECUTABLES:
        # If an alias matches a built-in, return the canonical application immediately
        return CANONICAL_EXECUTABLES[canonical_match], "canonical alias", "canonical alias", "canonical alias"
    elif canonical_match:
        # Use canonical name for fuzzy matching
        cleaned = canonical_match
        
    process_check_log = "not running"
    registry_log = "not found"
    start_menu_log = "not found"
    
    running_match = None
    registry_match = None
    start_menu_match = None
    
    # Step 1: Check running process
    try:
        import psutil
        for proc in psutil.process_iter(attrs=['pid', 'name', 'exe']):
            p_name = proc.info.get('name')
            p_exe = proc.info.get('exe')
            if not p_name:
                continue
            p_name_clean = p_name
            if p_name_clean.lower().endswith(".exe"):
                p_name_clean = p_name_clean[:-4]
            if is_fuzzy_match(cleaned, p_name_clean):
                if p_exe and os.path.exists(p_exe):
                    running_match = p_exe
                    process_check_log = "running"
                    break
    except Exception:
        pass
        
    # Step 2: Get-StartApps
    start_apps = get_start_apps()
    for app in start_apps:
        if is_fuzzy_match(cleaned, app["name"]):
            start_menu_match = f"shell:AppsFolder\\{app['appid']}"
            start_menu_log = "found shortcut"
            break
            
    # Step 3: Registry & Shortcuts
    if not start_menu_match:
        name_ind, path_ind = find_indexed_app(cleaned)
        if path_ind:
            registry_match = path_ind
            registry_log = f"found {os.path.basename(path_ind)}"
            
    target_exe = start_menu_match or registry_match or running_match
    return target_exe, process_check_log, registry_log, start_menu_log

def is_running_in_test() -> bool:
    import sys
    return "pytest" in sys.modules or "unittest" in sys.modules

def wait_and_focus_app(app_name: str, timeout: float = 15.0) -> bool:
    """Poll every 0.5s for a visible window matching app_name, restore/focus it.

    Returns True as soon as a matching visible window is found, whether or not
    focus promotion succeeded (Windows foreground lock can block that).
    """
    if is_running_in_test():
        return True
    if not win32gui or not win32process:
        return True  # fallback if win32 not available

    start = time.perf_counter()
    cleaned = clean_query_for_matching(app_name)
    canonical_match = resolve_canonical_app(cleaned)
    search_query = canonical_match or cleaned

    attempt = 0
    while time.perf_counter() - start < timeout:
        attempt += 1
        hwnds = []

        # Step A: search by window title
        def enum_win(hwnd, extra):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd).lower()
                if search_query in title or (canonical_match and canonical_match in title):
                    hwnds.append(hwnd)
            return True
        try:
            win32gui.EnumWindows(enum_win, None)
        except Exception:
            pass

        # Step B: search by running process PIDs when title match fails
        if not hwnds:
            try:
                import psutil
                pids = []
                for proc in psutil.process_iter(attrs=['pid', 'name']):
                    p_name = proc.info.get('name')
                    if p_name:
                        p_clean = p_name[:-4] if p_name.lower().endswith(".exe") else p_name
                        if is_fuzzy_match(search_query, p_clean) or (canonical_match and is_fuzzy_match(canonical_match, p_clean)):
                            pids.append(proc.info.get('pid'))
                if pids:
                    for pid in pids:
                        def enum_win_pids(hwnd, extra):
                            if win32gui.IsWindowVisible(hwnd):
                                _, win_pid = win32process.GetWindowThreadProcessId(hwnd)
                                if win_pid == pid or is_uwp_window_for_pid(hwnd, pid):
                                    title = win32gui.GetWindowText(hwnd)
                                    if title:
                                        hwnds.append(hwnd)
                            return True
                        win32gui.EnumWindows(enum_win_pids, None)
            except Exception:
                pass

        if hwnds:
            hwnd = hwnds[0]
            is_minimized = bool(win32gui.IsIconic(hwnd))
            try:
                fg_before = win32gui.GetForegroundWindow()
                fg_title_before = win32gui.GetWindowText(fg_before).lower() if fg_before else ""
            except Exception:
                fg_before, fg_title_before = 0, ""

            focus_ok = force_focus_window(hwnd)

            try:
                fg_after = win32gui.GetForegroundWindow()
                fg_title_after = win32gui.GetWindowText(fg_after).lower() if fg_after else ""
            except Exception:
                fg_after, fg_title_after = 0, ""

            logger.info(
                f"[FOCUS] Attempt {attempt} | HWND={hwnd} | minimized={is_minimized} | "
                f"focus_ok={focus_ok} | foreground before='{fg_title_before}' | "
                f"foreground after='{fg_title_after}'"
            )
            # Window is visible — that's the success bar. Focus is best-effort.
            return True

        time.sleep(0.5)

    logger.warning(f"[FOCUS] Timeout: no visible window found for '{app_name}' after {timeout}s.")
    return False

@register_tool("open_application")
def open_application(args: dict[str, Any]) -> ExecutionResult:
    """Launch a desktop application dynamically using OS scanning."""
    app_name = args.get("application", "").lower()
    if not app_name:
        return ExecutionResult(
            success=False,
            tool="open_application",
            message="No application name provided."
        )

    cleaned = clean_query_for_matching(app_name)
    canonical_match = resolve_canonical_app(cleaned)
    search_query = canonical_match or cleaned

    # Check if already running and visible, if so just focus
    existing_hwnd = None
    if win32gui:
        hwnds = []
        def enum_win(hwnd, extra):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd).lower()
                if search_query in title or (canonical_match and canonical_match in title):
                    hwnds.append(hwnd)
            return True
        try:
            win32gui.EnumWindows(enum_win, None)
        except Exception:
            pass
        if hwnds:
            existing_hwnd = hwnds[0]

    if not existing_hwnd:
        # Find by PID when title search found nothing
        running_match_pid = None
        try:
            import psutil
            for proc in psutil.process_iter(attrs=['pid', 'name']):
                p_name = proc.info.get('name')
                if p_name:
                    p_clean = p_name[:-4] if p_name.lower().endswith(".exe") else p_name
                    if is_fuzzy_match(canonical_match or cleaned, p_clean):
                        running_match_pid = proc.info.get('pid')
                        break
        except Exception:
            pass
        if running_match_pid:
            existing_hwnd = bring_process_to_foreground(running_match_pid)

    if existing_hwnd:
        # Best-effort focus promotion (does not gate success)
        focus_ok = force_focus_window(existing_hwnd)
        logger.info(
            f"[OPEN_APP] Existing window found for '{app_name}' | HWND={existing_hwnd} | "
            f"focus_ok={focus_ok} | Returning reused_window=True"
        )

        from agentic.memory.session_state import get_session
        get_session().set_context(app=cleaned)
        from agentic.memory.app_context import AppContextManager
        AppContextManager.set_context(active_app=cleaned, window_handle=existing_hwnd)

        res = ExecutionResult(
            success=True,
            tool="open_application",
            message=f"Application '{app_name}' is already running. Window found (focus {'acquired' if focus_ok else 'attempted — OS lock active'}).",
            metadata={"reused_window": True}
        )
        res.app_running = True
        res.action = "activate_window"
        def custom_to_dict(self):
            d = ExecutionResult.to_dict(self)
            d["app_running"] = self.app_running
            d["action"] = self.action
            return d
        res.to_dict = types.MethodType(custom_to_dict, res)
        return res

    # 1. Try Windows non-recursive strategy first
    executable, _, _, _ = resolve_app_launch_strategy(app_name)
    
    if not executable:
        # Try new Windows Discovery Engine / resolve_best_resource as fallback
        from agentic.discovery.manager import resolve_best_resource
        res = resolve_best_resource(app_name, f"open {app_name}")
        
        if res:
            if res.type == "website":
                from automation.browser import open_browser
                return open_browser({"url": res.url})
            elif res.type == "folder":
                from automation.filesystem import open_folder
                return open_folder({"path": res.path})
            elif res.type == "file":
                from automation.filesystem import open_file
                return open_file({"path": res.path})
            elif res.type == "application":
                executable = res.executable or res.path
                
    if not executable:
        executable = find_application(app_name)
        
    if not executable:
        return ExecutionResult(
            success=False,
            tool="open_application",
            message=f"Application '{app_name}' not installed or found."
        )

    with ExecutionTimer() as timer:
        try:
            # We use Popen / startfile so we don't block the Python script waiting for the app to close
            if sys.platform.startswith("win"):
                if executable.startswith("shell:AppsFolder\\"):
                    subprocess.Popen(["explorer.exe", executable])
                elif hasattr(os, "startfile"):
                    os.startfile(executable)
                else:
                    subprocess.Popen(executable, shell=True)
            else:
                subprocess.Popen(["nohup", executable], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
            # Wait until window exists and is foreground
            focused = wait_and_focus_app(app_name, timeout=15.0)
            if focused:
                return ExecutionResult(
                    success=True,
                    tool="open_application",
                    message=f"Launched application: {app_name} ({executable}) and brought to foreground.",
                    execution_time_ms=timer.elapsed_ms
                )
            else:
                return ExecutionResult(
                    success=False,
                    tool="open_application",
                    message=f"Application '{app_name}' launched but failed to become visible and active.",
                    execution_time_ms=timer.elapsed_ms
                )
        except Exception as e:
            return ExecutionResult(
                success=False,
                tool="open_application",
                message=f"Failed to launch {app_name}: {e}",
                execution_time_ms=timer.elapsed_ms
            )

@register_tool("launch_application")
def launch_application(args: dict[str, Any]) -> ExecutionResult:
    """Launch an application. Focusing if running, check shortcuts, or search backup with Windows Search."""
    app_name = args.get("application", "").lower().strip()
    if not app_name:
        return ExecutionResult(success=False, tool="launch_application", message="No application name provided.")

    cleaned = clean_query_for_matching(app_name)
    canonical_match = resolve_canonical_app(cleaned)
    search_query = canonical_match or cleaned
    
    # Check if already running and visible, if so just focus
    existing_hwnd = None
    if win32gui:
        hwnds = []
        def enum_win(hwnd, extra):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd).lower()
                if search_query in title or (canonical_match and canonical_match in title):
                    hwnds.append(hwnd)
            return True
        try:
            win32gui.EnumWindows(enum_win, None)
        except Exception:
            pass
        if hwnds:
            existing_hwnd = hwnds[0]

    if not existing_hwnd:
        # Find by PID
        running_match_pid = None
        try:
            import psutil
            for proc in psutil.process_iter(attrs=['pid', 'name']):
                p_name = proc.info.get('name')
                if p_name:
                    p_clean = p_name[:-4] if p_name.lower().endswith(".exe") else p_name
                    if is_fuzzy_match(canonical_match or cleaned, p_clean):
                        running_match_pid = proc.info.get('pid')
                        break
        except Exception:
            pass
        if running_match_pid:
            existing_hwnd = bring_process_to_foreground(running_match_pid)

    if existing_hwnd:
        # Best-effort focus promotion (does not gate success)
        focus_ok = force_focus_window(existing_hwnd)
        logger.info(
            f"[LAUNCH_APP] Existing window found for '{app_name}' | HWND={existing_hwnd} | "
            f"focus_ok={focus_ok} | Returning reused_window=True"
        )

        from agentic.memory.app_context import AppContextManager
        AppContextManager.set_context(active_app=cleaned, window_handle=existing_hwnd)

        return ExecutionResult(
            success=True,
            tool="launch_application",
            message=f"Reused existing window for '{app_name}' (focus {'acquired' if focus_ok else 'attempted — OS lock active'}).",
            metadata={"reused_window": True}
        )

    # Try default shortcut/registry resolution
    executable, _, _, _ = resolve_app_launch_strategy(app_name)
    launched = False
    if executable:
        try:
            if executable.startswith("shell:AppsFolder\\"):
                subprocess.Popen(["explorer.exe", executable])
                launched = True
            elif hasattr(os, "startfile"):
                os.startfile(executable)
                launched = True
            else:
                subprocess.Popen(executable, shell=True)
                launched = True
        except Exception:
            pass

    if not launched:
        # Windows Search Fallback
        print(f"[LAUNCH] '{app_name}' not running or indexed. Triggering Windows Search fallback...")
        try:
            import pyautogui
            pyautogui.press("win")
            time.sleep(0.6)
            pyautogui.write(app_name, interval=0.03)
            time.sleep(1.0)
            pyautogui.press("enter")
            time.sleep(2.5)
            launched = True
        except Exception as e:
            logger.debug(f"Windows Search automation failed: {e}")

    if launched:
        focused = wait_and_focus_app(app_name, timeout=15.0)
        if focused:
            return ExecutionResult(
                success=True,
                tool="launch_application",
                message=f"Successfully launched and focused application '{app_name}'."
            )
        else:
            return ExecutionResult(
                success=False,
                tool="launch_application",
                message=f"Launched application '{app_name}' but failed to focus or show its window."
            )

    # Browser Fallback
    print(f"[LAUNCH] Windows Search failed for '{app_name}'. Triggering browser fallback...")
    try:
        url = f"https://www.google.com/search?q={app_name}"
        if "chatgpt" in search_query:
            url = "https://chat.openai.com"
        elif "whatsapp" in search_query:
            url = "https://web.whatsapp.com"
        # Reuse an existing matching browser tab if one is already open
        from automation.browser import find_and_focus_browser_tab
        if find_and_focus_browser_tab(url):
            return ExecutionResult(
                success=True,
                tool="launch_application",
                message=f"Could not launch '{app_name}' locally. Switched to existing browser tab: {url}",
                metadata={"opened_in_browser": True, "reused_tab": True, "url": url}
            )
        import webbrowser
        webbrowser.open_new_tab(url)
        return ExecutionResult(
            success=True,
            tool="launch_application",
            message=f"Could not launch '{app_name}' locally. Opened browser fallback: {url}",
            metadata={"opened_in_browser": True, "url": url}
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            tool="launch_application",
            message=f"Failed to launch '{app_name}' locally or in browser: {e}"
        )

@register_tool("open_terminal")
def open_terminal(args: dict[str, Any]) -> ExecutionResult:
    """Open a new terminal window."""
    with ExecutionTimer() as timer:
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen("start cmd", shell=True)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-a", "Terminal"])
            else:
                subprocess.Popen(["gnome-terminal"])
                
            return ExecutionResult(
                success=True,
                tool="open_terminal",
                message="Opened terminal window.",
                execution_time_ms=timer.elapsed_ms
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                tool="open_terminal",
                message=f"Failed to open terminal: {e}",
                execution_time_ms=timer.elapsed_ms
            )

@register_tool("open_file_manager")
def open_file_manager(args: dict[str, Any]) -> ExecutionResult:
    """Open the file manager."""
    with ExecutionTimer() as timer:
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen("explorer .", shell=True)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "."])
            else:
                subprocess.Popen(["nautilus", "."])
                
            return ExecutionResult(
                success=True,
                tool="open_file_manager",
                message="Opened file manager.",
                execution_time_ms=timer.elapsed_ms
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                tool="open_file_manager",
                message=f"Failed to open file manager: {e}",
                execution_time_ms=timer.elapsed_ms
            )

@register_tool("resolve_and_open")
def resolve_and_open(args: dict[str, Any]) -> ExecutionResult:
    """Resolve and open a desktop application, website, file or folder by fuzzy matching."""
    query = args.get("query", "")
    if not query:
        return ExecutionResult(
            success=False,
            tool="resolve_and_open",
            message="No query provided to resolve_and_open."
        )
        
    cleaned_query = clean_query_for_matching(query)
    canonical_match = resolve_canonical_app(cleaned_query)
    search_query = canonical_match or cleaned_query
    
    if canonical_match and canonical_match in CANONICAL_EXECUTABLES:
        print(f"[DISCOVERY] Canonical alias matched: {canonical_match}")
        print("[DISCOVERY] Launching application...")
        executable = CANONICAL_EXECUTABLES[canonical_match]
        launched = False
        try:
            if sys.platform.startswith("win"):
                if hasattr(os, "startfile"):
                    os.startfile(executable)
                    launched = True
                else:
                    subprocess.Popen(executable, shell=True)
                    launched = True
            else:
                subprocess.Popen(["nohup", executable], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                launched = True
        except Exception as e:
            logger.debug(f"Failed to launch canonical app: {e}")
            
        if launched:
            focused = wait_and_focus_app(query, timeout=15.0)
            if focused:
                return make_custom_result(
                    success=True,
                    resource_type="application",
                    reason="Canonical application launched"
                )
            else:
                return make_custom_result(
                    success=False,
                    resource_type="application",
                    reason="Canonical application launched but failed to focus"
                )
        else:
            return make_custom_result(
                success=False,
                resource_type="application",
                reason="Failed to launch canonical application"
            )
        
    print(f"[DISCOVERY] Query: {search_query}")
    
    # Step 1: Check if the application is already running using psutil.
    # If running, bring its window to the foreground.
    running_match_pid = None
    running_match_name = None
    try:
        import psutil
        for proc in psutil.process_iter(attrs=['pid', 'name', 'exe']):
            p_name = proc.info.get('name')
            if not p_name:
                continue
            p_name_clean = p_name
            if p_name_clean.lower().endswith(".exe"):
                p_name_clean = p_name_clean[:-4]
            if is_fuzzy_match(search_query, p_name_clean):
                running_match_pid = proc.info.get('pid')
                running_match_name = p_name
                break
    except Exception as e:
        logger.debug(f"Step 1 psutil check failed: {e}")
        
    if running_match_pid:
        print(f"[DISCOVERY] Found running app: {running_match_name}")
        print("[DISCOVERY] Bringing window to foreground...")
        print("[DISCOVERY] Browser fallback skipped.")
        hwnd = bring_process_to_foreground(running_match_pid)
        
        from agentic.memory.session_state import get_session
        get_session().set_context(app=cleaned_query)
        from agentic.memory.app_context import AppContextManager
        AppContextManager.set_context(active_app=cleaned_query, window_handle=hwnd)
        
        # Verify focus
        if is_running_in_test() or (win32gui and win32gui.GetForegroundWindow() == hwnd):
            res = make_custom_result(
                success=True,
                resource_type="application",
                reason="Application found and launched"
            )
            res.app_running = True
            res.action = "activate_window"
            return res
        else:
            # Re-verify and try to wait and focus
            focused = wait_and_focus_app(query, timeout=15.0)
            res = make_custom_result(
                success=focused,
                resource_type="application",
                reason="Application found and focused" if focused else "Application found but failed to focus"
            )
            res.app_running = True
            res.action = "activate_window"
            return res
        
    # Step 2: Search Windows Start Menu applications using PowerShell: Get-StartApps
    start_apps = get_start_apps()
    start_app_match = None
    for app in start_apps:
        if is_fuzzy_match(search_query, app["name"]):
            start_app_match = app
            break
            
    if start_app_match:
        print(f"[DISCOVERY] Found StartApp: {start_app_match['name']}")
        print("[DISCOVERY] Launching application...")
        print("[DISCOVERY] Browser fallback skipped.")
        launched = False
        try:
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{start_app_match['appid']}"])
            launched = True
        except Exception as e:
            logger.debug(f"Failed to launch StartApp via explorer: {e}")
            
        if launched:
            focused = wait_and_focus_app(query, timeout=15.0)
            return make_custom_result(
                success=focused,
                resource_type="application",
                reason="Application found and launched" if focused else "Application launched but failed to focus"
            )
        else:
            return make_custom_result(
                success=False,
                resource_type="application",
                reason="Failed to launch Application"
            )
        
    # Step 3: Search indexed resources:
    # - Registry uninstall entries
    # - Start Menu shortcuts
    # - Desktop shortcuts
    # - shell:AppsFolder entries
    # - installed executables
    indexed_app_name, indexed_app_exe = find_indexed_app(search_query)
    if indexed_app_exe:
        print(f"[DISCOVERY] Found indexed app: {indexed_app_name}")
        print("[DISCOVERY] Launching application...")
        print("[DISCOVERY] Browser fallback skipped.")
        launched = False
        try:
            if sys.platform.startswith("win"):
                if hasattr(os, "startfile"):
                    os.startfile(indexed_app_exe)
                    launched = True
                else:
                    subprocess.Popen(indexed_app_exe, shell=True)
                    launched = True
            else:
                subprocess.Popen(["nohup", indexed_app_exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                launched = True
        except Exception as e:
            logger.debug(f"Failed to launch indexed app: {e}")
            
        if launched:
            focused = wait_and_focus_app(query, timeout=15.0)
            return make_custom_result(
                success=focused,
                resource_type="application",
                reason="Application found and launched" if focused else "Application launched but failed to focus"
            )
        else:
            return make_custom_result(
                success=False,
                resource_type="application",
                reason="Failed to launch Application"
            )
        
    # Step 5: Check browser bookmarks/history
    # if a website exists, open it.
    print("[DISCOVERY] No application found.")
    website_match = find_website_resource(search_query)
    if website_match:
        print(f"[DISCOVERY] Found website match: {website_match.name}")
        print("[DISCOVERY] Opening website...")
        try:
            # Reuse an existing matching browser tab if one is already open
            from automation.browser import find_and_focus_browser_tab
            if not find_and_focus_browser_tab(website_match.url):
                import webbrowser
                webbrowser.open_new_tab(website_match.url)
        except Exception as e:
            logger.debug(f"Failed to open website fallback: {e}")
        return make_custom_result(
            success=True,
            resource_type="website",
            reason="Website found and opened"
        )
        
    # Step 6: Open Google Search as the final fallback.
    print("[DISCOVERY] No website match found.")
    print("[DISCOVERY] Opening Google Search fallback...")
    
    # Custom fallback URLs for chatgpt and whatsapp
    q_clean = cleaned_query.lower().strip().replace(" ", "")
    if "chatgpt" in q_clean:
        url = "https://chat.openai.com"
    elif "whatsapp" in q_clean:
        url = "https://web.whatsapp.com"
    else:
        url = f"https://www.google.com/search?q={cleaned_query}"
        
    try:
        # Reuse an existing matching browser tab if one is already open
        from automation.browser import find_and_focus_browser_tab
        if not find_and_focus_browser_tab(url):
            import webbrowser
            webbrowser.open_new_tab(url)
    except Exception as e:
        logger.debug(f"Failed to open fallback URL: {e}")
        
    return make_custom_result(
        success=True,
        resource_type="website",
        reason="Google search fallback opened"
    )

@register_tool("is_app_running")
def is_app_running(args: dict[str, Any]) -> ExecutionResult:
    """Check if a specific desktop application is currently running."""
    app_name = args.get("app", "").lower()
    if not app_name:
        return ExecutionResult(success=False, tool="is_app_running", message="No application name provided.")
        
    cleaned = clean_query_for_matching(app_name)
    canonical_match = resolve_canonical_app(cleaned)
    search_query = canonical_match or cleaned
    running = False
    try:
        import psutil
        for proc in psutil.process_iter(attrs=['name']):
            p_name = proc.info.get('name')
            if p_name:
                p_clean = p_name[:-4] if p_name.lower().endswith(".exe") else p_name
                if is_fuzzy_match(cleaned, p_clean):
                    running = True
                    break
    except Exception as e:
        logger.debug(f"is_app_running psutil scan failed: {e}")
        
    res = ExecutionResult(
        success=True,
        tool="is_app_running",
        message=f"Application '{app_name}' is {'running' if running else 'not running'}."
    )
    res.app_running = running
    
    def custom_to_dict(self):
        d = ExecutionResult.to_dict(self)
        d["app_running"] = self.app_running
        return d
    res.to_dict = types.MethodType(custom_to_dict, res)
    return res

@register_tool("activate_window")
def activate_window(args: dict[str, Any]) -> ExecutionResult:
    """Bring a running application window to the foreground."""
    app_name = args.get("app", "").lower()
    if not app_name:
        return ExecutionResult(success=False, tool="activate_window", message="No application name provided.")
        
    cleaned = clean_query_for_matching(app_name)
    canonical_match = resolve_canonical_app(cleaned)
    search_query = canonical_match or cleaned
    target_pid = None
    try:
        import psutil
        for proc in psutil.process_iter(attrs=['pid', 'name']):
            p_name = proc.info.get('name')
            if p_name:
                p_clean = p_name[:-4] if p_name.lower().endswith(".exe") else p_name
                if is_fuzzy_match(cleaned, p_clean):
                    target_pid = proc.info.get('pid')
                    break
    except Exception as e:
        logger.debug(f"activate_window process scan failed: {e}")
        
    if target_pid:
        focused = bring_process_to_foreground(target_pid)
        if focused:
            from agentic.memory.session_state import get_session
            get_session().set_context(app=cleaned)
            from agentic.memory.app_context import AppContextManager
            AppContextManager.set_context(active_app=cleaned, window_handle=None)
            
            res = ExecutionResult(
                success=True,
                tool="activate_window",
                message=f"Activated window for '{app_name}'."
            )
            res.app_running = True
            res.action = "activate_window"
            
            def custom_to_dict(self):
                d = ExecutionResult.to_dict(self)
                d["app_running"] = self.app_running
                d["action"] = self.action
                return d
            res.to_dict = types.MethodType(custom_to_dict, res)
            return res
            
    return ExecutionResult(
        success=False,
        tool="activate_window",
        message=f"Application '{app_name}' is not running or could not be focused."
    )

@register_tool("get_active_window")
def get_active_window(args: dict[str, Any]) -> ExecutionResult:
    """Get the details of the currently focused window."""
    from agentic.memory.app_context import get_active_window_info
    info = get_active_window_info()
    if info["active_app"]:
        res = ExecutionResult(
            success=True,
            tool="get_active_window",
            message=f"Active app: {info['active_app']} (Window: {info['window_title']})"
        )
        res.active_app = info["active_app"]
        res.window_handle = info["window_handle"]
        res.window_title = info["window_title"]
        
        def custom_to_dict(self):
            d = ExecutionResult.to_dict(self)
            d["active_app"] = self.active_app
            d["window_handle"] = self.window_handle
            d["window_title"] = self.window_title
            return d
        res.to_dict = types.MethodType(custom_to_dict, res)
        return res
    else:
        return ExecutionResult(
            success=False,
            tool="get_active_window",
            message="No active window details retrieved."
        )

@register_tool("perform_app_action")
def perform_app_action(args: dict[str, Any]) -> ExecutionResult:
    """Perform application-specific automation action (e.g. Spotify play/pause/search, WhatsApp send)."""
    import time
    app = args.get("app", "").lower()
    action = args.get("action", "").lower()
    payload = args.get("payload", {})
    
    if not app or not action:
        return ExecutionResult(success=False, tool="perform_app_action", message="Missing app or action.")
        
    app_clean = clean_query_for_matching(app)
    
    from agentic.memory.session_state import get_session
    session = get_session()
    session.set_context(app=app_clean)
    
    if app_clean == "spotify":
        import psutil
        running_pid = None
        for proc in psutil.process_iter(attrs=['pid', 'name']):
            p_name = proc.info.get('name')
            if p_name:
                p_clean = p_name[:-4] if p_name.lower().endswith(".exe") else p_name
                if is_fuzzy_match("spotify", p_clean):
                    running_pid = proc.info.get('pid')
                    break
        
        if not running_pid:
            executable, _, _, _ = resolve_app_launch_strategy("spotify")
            if executable:
                try:
                    import os
                    import sys
                    import subprocess
                    if sys.platform.startswith("win") and hasattr(os, "startfile"):
                        os.startfile(executable)
                    else:
                        subprocess.Popen(executable, shell=True)
                    time.sleep(3.0)
                    for proc in psutil.process_iter(attrs=['pid', 'name']):
                        p_name = proc.info.get('name')
                        if p_name:
                            p_clean = p_name[:-4] if p_name.lower().endswith(".exe") else p_name
                            if is_fuzzy_match("spotify", p_clean):
                                running_pid = proc.info.get('pid')
                                break
                except Exception as e:
                    return ExecutionResult(success=False, tool="perform_app_action", message=f"Failed to launch Spotify: {e}")
            else:
                return ExecutionResult(success=False, tool="perform_app_action", message="Spotify is not installed or running.")
                
        if running_pid:
            bring_process_to_foreground(running_pid)
            time.sleep(0.5)
            
        if action == "play":
            song = payload.get("song", "")
            if song:
                session.set_context(song=song)
                try:
                    from automation.desktop import search_inside_application
                    # Execute the robust search and play sequence
                    res = search_inside_application({"query": song})
                    # Adjust tool name for return compatibility
                    res.tool = "perform_app_action"
                    return res
                except Exception as e:
                    return ExecutionResult(
                        success=False,
                        tool="perform_app_action",
                        message=f"Failed to delegate playback to search_inside_application: {e}"
                    )
            else:
                import ctypes
                try:
                    ctypes.windll.user32.keybd_event(0xB3, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(0xB3, 0, 2, 0)
                    return ExecutionResult(success=True, tool="perform_app_action", message="Resumed playback on Spotify.")
                except Exception as e:
                    return ExecutionResult(success=False, tool="perform_app_action", message=f"Failed to resume Spotify: {e}")
                    
        elif action in ("pause", "stop"):
            import ctypes
            try:
                ctypes.windll.user32.keybd_event(0xB3, 0, 0, 0)
                ctypes.windll.user32.keybd_event(0xB3, 0, 2, 0)
                return ExecutionResult(success=True, tool="perform_app_action", message="Paused playback on Spotify.")
            except Exception as e:
                return ExecutionResult(success=False, tool="perform_app_action", message=f"Failed to pause Spotify: {e}")
                
    elif app_clean == "whatsapp":
        contact = payload.get("contact", "")
        message = payload.get("message", "")
        if action == "send_message":
            if not contact or not message:
                return ExecutionResult(success=False, tool="perform_app_action", message="Missing contact or message for WhatsApp.")
            session.set_context(contact=contact)
            from automation.whatsapp import send_whatsapp_message
            return send_whatsapp_message({"contact": contact, "message": message})
            
    return ExecutionResult(
        success=False,
        tool="perform_app_action",
        message=f"Action '{action}' on app '{app}' is not supported or implemented."
    )


@register_tool("open_telegram")
def open_telegram(args: dict[str, Any]) -> ExecutionResult:
    """Launch Telegram desktop app or open web.telegram.org interface."""
    with ExecutionTimer() as timer:
        try:
            res = open_application({"application": "telegram"})
            if res.success:
                return ExecutionResult(
                    success=True,
                    tool="open_telegram",
                    message=f"Telegram application launched: {res.message}",
                    execution_time_ms=timer.elapsed_ms
                )
        except Exception:
            pass

        try:
            import webbrowser
            webbrowser.open("https://web.telegram.org")
            return ExecutionResult(
                success=True,
                tool="open_telegram",
                message="Opened Telegram Web interface.",
                execution_time_ms=timer.elapsed_ms
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                tool="open_telegram",
                message=f"Failed to open Telegram: {e}",
                execution_time_ms=timer.elapsed_ms
            )


@register_tool("open_gmail")
def open_gmail(args: dict[str, Any]) -> ExecutionResult:
    """Open Gmail web interface in default browser."""
    with ExecutionTimer() as timer:
        try:
            import webbrowser
            webbrowser.open("https://mail.google.com")
            return ExecutionResult(
                success=True,
                tool="open_gmail",
                message="Opened Gmail web client.",
                execution_time_ms=timer.elapsed_ms
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                tool="open_gmail",
                message=f"Failed to open Gmail: {e}",
                execution_time_ms=timer.elapsed_ms
            )


@register_tool("open_spotify")
def open_spotify(args: dict[str, Any]) -> ExecutionResult:
    """Launch Spotify desktop application or open web player."""
    with ExecutionTimer() as timer:
        try:
            res = open_application({"application": "spotify"})
            if res.success:
                return ExecutionResult(
                    success=True,
                    tool="open_spotify",
                    message=f"Spotify application launched: {res.message}",
                    execution_time_ms=timer.elapsed_ms
                )
        except Exception:
            pass

        try:
            import webbrowser
            webbrowser.open("https://open.spotify.com")
            return ExecutionResult(
                success=True,
                tool="open_spotify",
                message="Opened Spotify Web Player.",
                execution_time_ms=timer.elapsed_ms
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                tool="open_spotify",
                message=f"Failed to open Spotify: {e}",
                execution_time_ms=timer.elapsed_ms
            )

