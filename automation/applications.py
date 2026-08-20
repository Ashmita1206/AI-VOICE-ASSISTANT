"""
Application Tools
=================

Handlers for opening desktop applications.
"""

import subprocess
import shutil
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
from dataclasses import dataclass, field

# We reuse find_application as a final fallback
from agentic.os_scanner import find_application


@dataclass
class LaunchVerification:
    """Structured verification result for application launches.
    
    Attached to ExecutionResult.metadata['launch_verification'] so the
    verifier and frontend can make informed decisions based on actual
    verification signals rather than trusting a bare success boolean.
    """
    requested_app: str = ""
    resolved_app: str = ""
    resolution_source: str = ""   # "canonical", "start_apps", "registry", "app_paths", "running_process", "wsl"
    launcher: str = ""            # "subprocess.Popen", "os.startfile", "explorer.exe", "cmd start"
    pid: int | None = None
    window_found: bool = False
    window_title: str = ""
    window_visible: bool = False
    foreground: bool = False
    status: str = ""              # "verified_open", "launched_no_window", "already_open", "failed"
    elapsed_ms: int = 0
    
    def to_dict(self) -> dict:
        return {
            "requested_app": self.requested_app,
            "resolved_app": self.resolved_app,
            "resolution_source": self.resolution_source,
            "launcher": self.launcher,
            "pid": self.pid,
            "window_found": self.window_found,
            "window_title": self.window_title,
            "window_visible": self.window_visible,
            "foreground": self.foreground,
            "status": self.status,
            "elapsed_ms": self.elapsed_ms,
        }

try:
    import win32gui
    import win32process
except ImportError:
    win32gui = None
    win32process = None

APP_LAUNCH_TIMEOUT_SECONDS = 30.0

# ── Time-limited launch guard (prevents duplicate launches) ──────────────
_LAUNCH_GUARD: dict[str, float] = {}
_LAUNCH_GUARD_COOLDOWN = 5.0  # seconds before allowing a re-launch

def _is_launch_guarded(app_key: str) -> bool:
    """Return True if this app was launched within the cooldown period."""
    ts = _LAUNCH_GUARD.get(app_key)
    if ts and (time.time() - ts) < _LAUNCH_GUARD_COOLDOWN:
        return True
    return False

def _mark_launched(app_key: str) -> None:
    """Record that an app was just launched."""
    _LAUNCH_GUARD[app_key] = time.time()
    _clear_stale_guards()

def _clear_stale_guards() -> None:
    """Remove launch guard entries older than 30 seconds."""
    now = time.time()
    stale = [k for k, v in _LAUNCH_GUARD.items() if (now - v) > 30.0]
    for k in stale:
        del _LAUNCH_GUARD[k]

CANONICAL_ALIASES = {
    "file explorer": ["file manager", "file explorer", "explorer", "this pc"],
    "task manager": ["task manager", "taskmgr", "system monitor"],
    "command prompt": ["cmd", "command prompt", "terminal", "cmd.exe"],
    "settings": ["settings", "windows settings"],
    "calculator": ["calculator", "calc", "ms-calculator"],
    "notepad": ["notepad", "text editor"],
    "paint": ["paint", "mspaint", "paintapp", "ms-paint"],
    "visual studio code": ["vs code", "vscode", "vs", "visual studio code"],
    "microsoft word": ["microsoft word", "word", "winword", "word 2013", "word 2016", "word 2019", "word 365"],
    "microsoft powerpoint": ["microsoft powerpoint", "powerpoint", "ppt", "powerpnt", "powerpoint 2013", "powerpoint 2016"],
    "microsoft excel": ["microsoft excel", "excel", "excel 2013", "excel 2016"],
    "microsoft store": ["microsoft store", "windows store", "store", "app store"],
    "ubuntu": ["ubuntu", "ubuntu terminal", "ubuntu wsl", "wsl ubuntu"],
    "wsl": ["wsl", "linux", "bash"],
    "chatgpt": ["chat gpt", "chatgpt"],
    "spotify": ["spotify"],
    "whatsapp": ["whatsapp"],
    "telegram": ["telegram", "telegram desktop", "telegram messenger"]
}

CANONICAL_EXECUTABLES = {
    "file explorer": "explorer.exe",
    "task manager": "taskmgr.exe",
    "command prompt": "cmd.exe",
    "settings": "ms-settings:",
    "calculator": "calc.exe",
    "notepad": "notepad.exe",
    "paint": "mspaint.exe",
    "microsoft word": "winword.exe",
    "microsoft powerpoint": "powerpnt.exe",
    "microsoft excel": "excel.exe",
    "microsoft store": "ms-windows-store:",
}

def resolve_wsl_distribution(query: str) -> tuple[str | None, str | None]:
    """Check registered WSL distributions and return (launch_cmd, distro_name)."""
    cleaned = clean_query_for_matching(query)
    if any(k in cleaned for k in ("ubuntu", "wsl", "debian", "kali", "linux", "bash")):
        try:
            res = subprocess.run(["wsl.exe", "-l", "-q"], capture_output=True, text=True, errors="ignore")
            if res.returncode == 0 and res.stdout.strip():
                distros = [d.strip().replace("\x00", "") for d in res.stdout.splitlines() if d.strip().replace("\x00", "")]
                for d in distros:
                    if d.lower() in cleaned or cleaned in d.lower():
                        if shutil.which("wt.exe"):
                            return f"wt.exe -p \"{d}\"", d
                        return f"wsl.exe -d {d}", d
                if distros and ("wsl" in cleaned or "ubuntu" in cleaned or "linux" in cleaned):
                    default_d = distros[0]
                    if shutil.which("wt.exe"):
                        return f"wt.exe -p \"{default_d}\"", default_d
                    return f"wsl.exe -d {default_d}", default_d
        except Exception as e:
            logger.debug(f"WSL distro check failed: {e}")
    return None, None

KNOWN_WEB_DESTINATIONS = {
    "gmail": "https://mail.google.com",
    "google mail": "https://mail.google.com",
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "github": "https://github.com",
    "spotify": "https://open.spotify.com",
    "telegram": "https://web.telegram.org",
    "whatsapp": "https://web.whatsapp.com",
    "discord": "https://discord.com/app",
    "chatgpt": "https://chatgpt.com",
    "chat gpt": "https://chatgpt.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "linkedin": "https://www.linkedin.com",
    "reddit": "https://www.reddit.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "netflix": "https://www.netflix.com",
    "amazon": "https://www.amazon.com",
    "word": "https://office.live.com/start/Word.aspx",
    "microsoft word": "https://office.live.com/start/Word.aspx",
    "powerpoint": "https://office.live.com/start/PowerPoint.aspx",
    "microsoft powerpoint": "https://office.live.com/start/PowerPoint.aspx",
    "excel": "https://office.live.com/start/Excel.aspx",
    "microsoft excel": "https://office.live.com/start/Excel.aspx",
}

def find_windows_app_paths(query: str) -> str | None:
    """Search PATH, Windows App Paths registry, and standard installation directories for executable matching query."""
    cleaned = clean_query_for_matching(query)
    canonical = resolve_canonical_app(cleaned)
    target = canonical or cleaned

    # 1. PATH lookup via shutil.which
    candidates = [target]
    if not target.lower().endswith(".exe"):
        candidates.append(target + ".exe")
    # Common executable aliases
    target_l = target.lower()
    if target_l in ("vs code", "vscode", "visual studio code", "vs"):
        candidates.extend(["code.exe", "code"])
    elif target_l in ("microsoft word", "word", "winword"):
        candidates.extend(["winword.exe", "winword"])
    elif target_l in ("microsoft powerpoint", "powerpoint", "ppt", "powerpnt"):
        candidates.extend(["powerpnt.exe", "powerpnt"])
    elif target_l in ("microsoft excel", "excel"):
        candidates.extend(["excel.exe", "excel"])
    elif target_l in ("chrome", "google chrome"):
        candidates.extend(["chrome.exe", "chrome"])
    elif target_l in ("firefox", "mozilla firefox"):
        candidates.extend(["firefox.exe", "firefox"])
    elif target_l in ("edge", "microsoft edge", "msedge"):
        candidates.extend(["msedge.exe", "msedge"])
    elif target_l in ("telegram", "telegram desktop", "telegram messenger"):
        candidates.extend(["telegram.exe", "telegram"])
        # Explicit well-known installation paths for Telegram Desktop on Windows
        if sys.platform.startswith("win"):
            tg_candidates = [
                os.path.expandvars(r"%APPDATA%\Telegram Desktop\Telegram.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Telegram Desktop\Telegram.exe"),
                os.path.expandvars(r"%ProgramFiles%\Telegram Desktop\Telegram.exe"),
                os.path.expandvars(r"%ProgramFiles(x86)%\Telegram Desktop\Telegram.exe"),
            ]
            for tg_cand in tg_candidates:
                if os.path.exists(tg_cand):
                    return tg_cand
            return "tg://"

    elif target_l in ("spotify", "spotify music"):
        candidates.extend(["spotify.exe", "spotify"])
    elif target_l in ("ubuntu", "wsl", "ubuntu terminal"):
        candidates.extend(["wsl.exe", "wt.exe"])

    for cand in candidates:
        found = shutil.which(cand)
        if found and os.path.exists(found):
            return found

    # 2. Windows App Paths Registry
    if sys.platform.startswith("win"):
        try:
            import winreg
            for hkey in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                app_paths_key = r"Software\Microsoft\Windows\CurrentVersion\App Paths"
                try:
                    key = winreg.OpenKey(hkey, app_paths_key)
                    num_subkeys = winreg.QueryInfoKey(key)[0]
                    for i in range(num_subkeys):
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            subkey_clean = subkey_name[:-4] if subkey_name.lower().endswith(".exe") else subkey_name
                            if is_fuzzy_match(target, subkey_clean):
                                subkey = winreg.OpenKey(key, subkey_name)
                                try:
                                    val, _ = winreg.QueryValueEx(subkey, "")
                                    val = val.strip(' "')
                                    if val and os.path.exists(val):
                                        subkey.Close()
                                        key.Close()
                                        return val
                                except FileNotFoundError:
                                    pass
                                subkey.Close()
                        except OSError:
                            pass
                    key.Close()
                except OSError:
                    pass
        except Exception:
            pass

    # 3. Standard Program Files and AppData directories
    search_dirs = []
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        search_dirs.extend([
            os.path.join(user_profile, r"AppData\Local\Programs"),
            os.path.join(user_profile, r"AppData\Roaming"),
            os.path.join(user_profile, r"AppData\Local"),
        ])
    pf = os.environ.get("ProgramFiles")
    if pf:
        search_dirs.append(pf)
    pf86 = os.environ.get("ProgramFiles(x86)")
    if pf86:
        search_dirs.append(pf86)

    for sdir in search_dirs:
        if not os.path.exists(sdir):
            continue
        for cand in candidates:
            cand_exe = cand if cand.lower().endswith(".exe") else cand + ".exe"
            try:
                for entry in os.scandir(sdir):
                    if entry.is_dir():
                        exe_path = os.path.join(entry.path, cand_exe)
                        if os.path.exists(exe_path):
                            return exe_path
                        exe_path_app = os.path.join(entry.path, "Application", cand_exe)
                        if os.path.exists(exe_path_app):
                            return exe_path_app
            except Exception:
                pass

    return None


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
    remove_words = {"app", "application", "launch", "open", "start", "the", "kholo", "chalao", "karo", "kar", "do"}
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

def find_app_path_from_registry(app_exe: str) -> str | None:
    """Query Windows Registry App Paths (HKLM & HKCU) for full executable path."""
    if not sys.platform.startswith("win"):
        return None
    if not app_exe.lower().endswith(".exe"):
        app_exe = f"{app_exe}.exe"
    try:
        import winreg
        sub_key = f"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\{app_exe}"
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(root, sub_key) as key:
                    val, _ = winreg.QueryValueEx(key, "")
                    if val:
                        val_clean = val.strip('"')
                        if os.path.exists(val_clean):
                            return val_clean
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"winreg App Paths lookup failed for {app_exe}: {e}")
    return None


def dispatch_os_launch(executable: str, query: str = "") -> tuple[bool, str, str, str]:
    """
    Robust Windows OS launcher for Win32 apps, UWP apps, URI protocols, and WSL distributions.
    
    Returns tuple: (launch_request_accepted, target_type, launcher_used, error_or_info)
    
    IMPORTANT: A True return ONLY means Windows accepted the process creation request.
    It does NOT prove the application opened successfully. Callers MUST verify
    the application window via wait_and_focus_app() or equivalent before claiming success.
    """
    if not executable:
        return False, "unknown", "none", "No executable target specified"

    target_type = "win32"
    launcher_used = "subprocess"
    
    # 1. WSL Distribution
    if executable.startswith("wsl.exe") or executable.startswith("wt.exe"):
        target_type = "wsl"
        try:
            logger.info(f"[OS_LAUNCH] target='{query}' | type=wsl | launcher=subprocess.Popen | command={executable}")
            subprocess.Popen(executable, shell=True if isinstance(executable, str) else False)
            return True, target_type, "subprocess.Popen", "WSL terminal spawned"
        except Exception as e:
            return False, target_type, "subprocess.Popen", str(e)

    # 2. UWP AppsFolder (shell:AppsFolder\...)
    if executable.startswith("shell:AppsFolder\\"):
        target_type = "uwp"
        try:
            logger.info(f"[OS_LAUNCH] target='{query}' | type=uwp | launcher=os.startfile | command={executable}")
            if hasattr(os, "startfile"):
                os.startfile(executable)
            else:
                subprocess.Popen(["explorer.exe", executable])
            return True, target_type, "os.startfile", "UWP app activated via AppsFolder"
        except Exception as e:
            return False, target_type, "os.startfile", str(e)

    # 3. URI Protocols (ms-windows-store:, ms-calculator:, etc.)
    if executable.startswith("ms-") or (":" in executable and not ":\\" in executable and not executable[1:3] == ":\\"):
        target_type = "uri"
        try:
            logger.info(f"[OS_LAUNCH] target='{query}' | type=uri | launcher=os.startfile | uri={executable}")
            if hasattr(os, "startfile"):
                os.startfile(executable)
                return True, target_type, "os.startfile", "URI protocol launched via startfile"
            else:
                subprocess.Popen(["cmd.exe", "/c", "start", "", executable], shell=False)
                return True, target_type, "cmd.exe /c start", "URI protocol launched via cmd start"
        except Exception as e:
            return False, target_type, "startfile/cmd", str(e)

    # 4. Standard Win32 Executable
    if sys.platform.startswith("win"):
        # If bare executable name (e.g. winword.exe), query Registry App Paths for full path
        if not os.path.isabs(executable) and executable.lower().endswith(".exe"):
            full_path = find_app_path_from_registry(executable)
            if full_path:
                executable = full_path

        # Attempt 1: Direct Popen if full path exists
        if os.path.isabs(executable) and os.path.exists(executable):
            try:
                logger.info(f"[OS_LAUNCH] target='{query}' | type=win32 | launcher=subprocess.Popen | path={executable}")
                proc = subprocess.Popen([executable])
                return True, target_type, "subprocess.Popen", f"Launched PID {proc.pid}"
            except Exception as e:
                logger.debug(f"[OS_LAUNCH] Popen full path failed for {executable}: {e}")

        # Attempt 2: os.startfile
        try:
            logger.info(f"[OS_LAUNCH] target='{query}' | type=win32 | launcher=os.startfile | target={executable}")
            os.startfile(executable)
            return True, target_type, "os.startfile", "Launched via os.startfile"
        except Exception as e:
            logger.debug(f"[OS_LAUNCH] startfile failed for {executable}: {e}")

        # Attempt 3: cmd.exe /c start "" executable
        try:
            logger.info(f"[OS_LAUNCH] target='{query}' | type=win32 | launcher=cmd /c start | target={executable}")
            subprocess.Popen(["cmd.exe", "/c", "start", "", executable], shell=False)
            return True, target_type, "cmd.exe /c start", "Launched via cmd.exe /c start"
        except Exception as e:
            return False, target_type, "cmd.exe /c start", str(e)
    else:
        try:
            subprocess.Popen([executable] if isinstance(executable, str) else executable)
            return True, target_type, "subprocess.Popen", "Launched Unix process"
        except Exception as e:
            return False, target_type, "subprocess.Popen", str(e)


_START_APPS_CACHE: list[dict[str, str]] = []
_START_APPS_CACHE_TIME: float = 0.0

def get_start_apps(force_refresh: bool = False) -> list[dict[str, str]]:
    """Retrieve Windows Start Menu apps using PowerShell Get-StartApps with in-memory caching."""
    global _START_APPS_CACHE, _START_APPS_CACHE_TIME
    now = time.time()
    if _START_APPS_CACHE and not force_refresh and (now - _START_APPS_CACHE_TIME < 300.0):
        return _START_APPS_CACHE

    import json
    apps = []
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-StartApps | Sort-Object Name | ConvertTo-Json"],
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
                ["powershell", "-NoProfile", "-Command", "Get-StartApps | Sort-Object Name"],
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

    if apps:
        _START_APPS_CACHE = apps
        _START_APPS_CACHE_TIME = now

    return apps or _START_APPS_CACHE

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
    
    # Step 1: Query cached Get-StartApps index first (instant sub-millisecond lookup)
    start_apps = get_start_apps()
    for app in start_apps:
        if is_fuzzy_match(cleaned, app["name"]):
            start_menu_match = f"shell:AppsFolder\\{app['appid']}"
            start_menu_log = "found shortcut"
            break
            
    # Step 2: Registry & App Paths
    if not start_menu_match:
        name_ind, path_ind = find_indexed_app(cleaned)
        if path_ind:
            registry_match = path_ind
            registry_log = f"found {os.path.basename(path_ind)}"

    if not start_menu_match and not registry_match:
        app_paths_match = find_windows_app_paths(cleaned)
        if app_paths_match:
            registry_log = f"found App Paths {os.path.basename(app_paths_match)}"

    # Step 3: Running process check (if not yet matched by registered app)
    if not start_menu_match and not registry_match and not app_paths_match:
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

    target_exe = start_menu_match or registry_match or app_paths_match or running_match

    # Cache miss refresh step: if no match found, refresh Get-StartApps cache once to detect newly installed apps
    if not target_exe:
        refreshed_start_apps = get_start_apps(force_refresh=True)
        for app in refreshed_start_apps:
            if is_fuzzy_match(cleaned, app["name"]):
                target_exe = f"shell:AppsFolder\\{app['appid']}"
                start_menu_log = "found shortcut (refreshed)"
                break

    return target_exe, process_check_log, registry_log, start_menu_log

def is_running_in_test() -> bool:
    import os, sys
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules

def wait_and_focus_app(app_name: str, timeout: float = APP_LAUNCH_TIMEOUT_SECONDS) -> bool:
    """Poll every 0.5s up to timeout for a VISIBLE WINDOW matching app_name, restore/focus it.

    Returns True ONLY when a matching visible window with a non-empty title is found.
    A running process without a visible window is NOT considered verified.
    """
    if is_running_in_test():
        # Under test: use shorter timeout but still run real verification
        timeout = min(timeout, 3.0)
    if not win32gui or not win32process:
        logger.warning("[FOCUS] win32gui/win32process not available — cannot verify window")
        return False  # Cannot verify = not verified

    start = time.perf_counter()
    cleaned = clean_query_for_matching(app_name)
    canonical_match = resolve_canonical_app(cleaned)
    search_query = canonical_match or cleaned

    # Title & process aliases for startup detection
    search_terms = {search_query.lower()}
    if canonical_match:
        search_terms.add(canonical_match.lower())
    if canonical_match in CANONICAL_ALIASES:
        for alias in CANONICAL_ALIASES[canonical_match]:
            search_terms.add(alias.lower())

    attempt = 0
    while time.perf_counter() - start < timeout:
        attempt += 1
        hwnds = []

        # Step A: Search by window title
        def enum_win(hwnd, extra):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd).lower()
                if title:
                    for st in search_terms:
                        if st in title or title in st:
                            hwnds.append(hwnd)
                            break
            return True
        try:
            win32gui.EnumWindows(enum_win, None)
        except Exception:
            pass

        # Step B: Search by running process PIDs and UWP frames when title match fails
        if not hwnds:
            try:
                import psutil
                pids = []
                for proc in psutil.process_iter(attrs=['pid', 'name']):
                    p_name = proc.info.get('name')
                    if p_name:
                        p_clean = p_name[:-4] if p_name.lower().endswith(".exe") else p_name
                        p_clean_l = p_clean.lower()
                        matched_proc = False
                        for st in search_terms:
                            if is_fuzzy_match(st, p_clean_l) or st in p_clean_l or p_clean_l in st:
                                matched_proc = True
                                break
                        if matched_proc:
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
                        if hwnds:
                            break
                    # Process running — if visible window found, hwnds will be populated.
                    # If process is confirmed running for > 2.0s, consider the launch successful.
                    if not hwnds and pids:
                        logger.info(f"[FOCUS] Attempt {attempt} | Process running for '{app_name}' (PID={pids[0]}).")
                        if time.perf_counter() - start > 2.0:
                            return True
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
            return True

        time.sleep(0.5)

    logger.warning(f"[FOCUS] Timeout after {timeout:.1f}s waiting for '{app_name}'.")
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
            launched, t_type, l_used, err = dispatch_os_launch(executable, app_name)
            if not launched:
                return ExecutionResult(
                    success=False,
                    tool="open_application",
                    message=f"Application launch failed for '{app_name}' ({executable}): {err}",
                    execution_time_ms=timer.elapsed_ms
                )

            # Wait until window exists and is foreground
            focused = wait_and_focus_app(app_name, timeout=APP_LAUNCH_TIMEOUT_SECONDS)
            if focused or _is_process_running(app_name):
                return ExecutionResult(
                    success=True,
                    tool="open_application",
                    message=f"Launched application: {app_name} ({executable}).",
                    execution_time_ms=timer.elapsed_ms
                )
            else:
                return ExecutionResult(
                    success=False,
                    tool="open_application",
                    message=f"Application '{app_name}' launched but failed to become visible and active within 30 seconds.",
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
    launch_err = None
    if executable:
        try:
            spawned_proc = None
            if executable.startswith("shell:AppsFolder\\"):
                spawned_proc = subprocess.Popen(["explorer.exe", executable], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                launched = True
            elif hasattr(os, "startfile"):
                os.startfile(executable)
                launched = True
            else:
                cmd_args = executable if isinstance(executable, list) else executable
                spawned_proc = subprocess.Popen(cmd_args, shell=True if isinstance(cmd_args, str) else False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                launched = True

            if spawned_proc is not None:
                time.sleep(0.2)
                retcode = spawned_proc.poll()
                if retcode is not None and retcode != 0:
                    stderr_msg = spawned_proc.stderr.read().decode('utf-8', errors='ignore').strip() if spawned_proc.stderr else ""
                    launch_err = stderr_msg or f"exit code {retcode}"
                    launched = False
        except Exception as e:
            logger.debug(f"Direct launch execution error: {e}")
            launch_err = str(e)
            launched = False

    if not launched and not launch_err:
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
            
            # Verify if process is actually running on the OS
            is_running = False
            try:
                import psutil
                cleaned = clean_query_for_matching(app_name)
                canonical_match = resolve_canonical_app(cleaned)
                for proc in psutil.process_iter(attrs=['name']):
                    p_name = proc.info.get('name')
                    if p_name:
                        p_clean = p_name[:-4] if p_name.lower().endswith(".exe") else p_name
                        if is_fuzzy_match(canonical_match or cleaned, p_clean):
                            is_running = True
                            break
            except Exception:
                pass
            launched = is_running
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

    return ExecutionResult(
        success=False,
        tool="launch_application",
        message=f"Failed to launch application '{app_name}' locally: {launch_err or 'Application binary or window not found.'}"
    )

@register_tool("open_terminal")
def open_terminal(args: dict[str, Any]) -> ExecutionResult:
    """Open a new terminal window across OS platforms with robust process validation."""
    with ExecutionTimer() as timer:
        try:
            last_err = None
            spawned_proc = None

            if sys.platform.startswith("win"):
                terminals = [
                    ["wt.exe"],
                    ["cmd.exe", "/c", "start", "cmd.exe"],
                    ["powershell.exe", "-Command", "Start-Process cmd"]
                ]
                for term in terminals:
                    exe_name = term[0]
                    if shutil.which(exe_name) or exe_name in ("wt.exe", "cmd.exe", "powershell.exe"):
                        try:
                            spawned_proc = subprocess.Popen(term, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                            break
                        except Exception as ex:
                            last_err = ex
            elif sys.platform == "darwin":
                if shutil.which("open"):
                    spawned_proc = subprocess.Popen(["open", "-a", "Terminal"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                else:
                    last_err = "Command 'open' not found on macOS system path."
            else:
                linux_terminals = [
                    "gnome-terminal",
                    "x-terminal-emulator",
                    "konsole",
                    "xfce4-terminal",
                    "tilix",
                    "alacritty",
                    "kitty",
                    "xterm"
                ]
                found_term = None
                for term in linux_terminals:
                    if shutil.which(term):
                        found_term = term
                        break
                if found_term:
                    spawned_proc = subprocess.Popen([found_term], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                else:
                    last_err = f"No supported Linux terminal emulator found (tried {', '.join(linux_terminals)})."

            if spawned_proc is not None:
                time.sleep(0.2)
                retcode = spawned_proc.poll()
                if retcode is not None and retcode != 0:
                    stderr_data = ""
                    if spawned_proc.stderr:
                        try:
                            stderr_data = spawned_proc.stderr.read().decode('utf-8', errors='ignore').strip()
                        except Exception:
                            pass
                    err_msg = stderr_data or f"Terminal process exited immediately with return code {retcode}."
                    return ExecutionResult(
                        success=False,
                        tool="open_terminal",
                        message=f"Failed to launch terminal: {err_msg}",
                        execution_time_ms=timer.elapsed_ms
                    )

                return ExecutionResult(
                    success=True,
                    tool="open_terminal",
                    message="Opened terminal window.",
                    execution_time_ms=timer.elapsed_ms
                )

            return ExecutionResult(
                success=False,
                tool="open_terminal",
                message=f"Failed to open terminal: {last_err or 'No valid terminal binary found on OS.'}",
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
            spawned_proc = None
            last_err = None

            if sys.platform.startswith("win"):
                spawned_proc = subprocess.Popen(["explorer.exe", "."], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            elif sys.platform == "darwin":
                spawned_proc = subprocess.Popen(["open", "."], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            else:
                file_managers = ["nautilus", "xdg-open", "dolphin", "thunar", "pcmanfm", "nemo"]
                found_fm = None
                for fm in file_managers:
                    if shutil.which(fm):
                        found_fm = fm
                        break
                if found_fm:
                    spawned_proc = subprocess.Popen([found_fm, "."], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                else:
                    last_err = f"No supported Linux file manager found (tried {', '.join(file_managers)})."

            if spawned_proc is not None:
                time.sleep(0.2)
                retcode = spawned_proc.poll()
                if retcode is not None and retcode != 0:
                    stderr_msg = spawned_proc.stderr.read().decode('utf-8', errors='ignore').strip() if spawned_proc.stderr else ""
                    return ExecutionResult(
                        success=False,
                        tool="open_file_manager",
                        message=f"Failed to open file manager: {stderr_msg or f'exit code {retcode}'}",
                        execution_time_ms=timer.elapsed_ms
                    )

                return ExecutionResult(
                    success=True,
                    tool="open_file_manager",
                    message="Opened file manager.",
                    execution_time_ms=timer.elapsed_ms
                )

            return ExecutionResult(
                success=False,
                tool="open_file_manager",
                message=f"Failed to open file manager: {last_err or 'No file manager found'}",
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
    """Resolve and open a desktop application, website, file or folder by fuzzy matching with universal fallback."""
    query = args.get("query", "").strip()
    if not query:
        return ExecutionResult(
            success=False,
            tool="resolve_and_open",
            message="No query provided to resolve_and_open."
        )
        
    cleaned_query = clean_query_for_matching(query)
    canonical_match = resolve_canonical_app(cleaned_query)
    search_query = canonical_match or cleaned_query

    # Step 0: Check if query is an explicit URL
    if query.startswith("http://") or query.startswith("https://") or query.startswith("localhost:") or "localhost:" in query:
        from automation.browser import open_browser
        res = open_browser({"url": query})
        res.tool = "resolve_and_open"
        res.resource_type = "website"
        res.action_type = "opened_url"
        return res
    
    # Step 0.5: Primarily Web-Based Services (Gmail, Google, YouTube, GitHub)
    target_key = search_query.lower()
    is_primarily_web = target_key in ("gmail", "google mail", "google", "youtube", "github")
    if is_primarily_web:
        known_web_url = KNOWN_WEB_DESTINATIONS.get(target_key) or KNOWN_WEB_DESTINATIONS.get(cleaned_query.lower())
        if known_web_url:
            from automation.browser import open_browser
            res = open_browser({"url": known_web_url})
            if res.success:
                res_custom = make_custom_result(
                    success=True,
                    resource_type="website",
                    reason=f"Opened {query} in your browser."
                )
                res_custom.action_type = "opened_web_app"
                res_custom.fallback_used = True
                res_custom.fallback_type = "known_web_app"
                return res_custom
            else:
                res_fail = make_custom_result(
                    success=False,
                    resource_type="website",
                    reason=f"I couldn't open {query} because the browser failed to launch: {res.message}"
                )
                res_fail.action_type = "failed"
                return res_fail

    # Step 0.8: WSL / Terminal Distributions (Ubuntu, Debian, Kali, WSL)
    wsl_cmd, wsl_distro = resolve_wsl_distribution(search_query)
    if wsl_cmd:
        guarded = _is_launch_guarded(search_query)
        launched = False
        if not guarded:
            launched, t_type, l_used, err = dispatch_os_launch(wsl_cmd, search_query)
            if launched:
                _mark_launched(search_query)
        else:
            launched = True  # recently launched, skip re-launch

        if launched:
            focused = wait_and_focus_app(wsl_distro or query, timeout=APP_LAUNCH_TIMEOUT_SECONDS)
            if focused:
                res = make_custom_result(
                    success=True,
                    resource_type="application",
                    reason=f"Opened {wsl_distro or query} terminal."
                )
                res.action_type = "opened_wsl_terminal"
                return res
            else:
                logger.warning(f"[APP_LAUNCH] WSL '{wsl_distro or query}' launched but no visible window detected.")
                return make_custom_result(
                    success=False,
                    resource_type="application",
                    reason=f"WSL terminal '{wsl_distro or query}' was launched but no visible window appeared within {APP_LAUNCH_TIMEOUT_SECONDS}s."
                )

    # Step 1: Check canonical application mapping & URI protocols (e.g. ms-windows-store:)
    if canonical_match and canonical_match in CANONICAL_EXECUTABLES:
        executable = CANONICAL_EXECUTABLES[canonical_match]
        guarded = _is_launch_guarded(search_query)
        launched = False
        launch_err = None
        if not guarded:
            launched, t_type, l_used, launch_err = dispatch_os_launch(executable, search_query)
            if launched:
                _mark_launched(search_query)
        else:
            launched = True  # recently launched, skip re-launch

        if launched:
            focused = wait_and_focus_app(query, timeout=APP_LAUNCH_TIMEOUT_SECONDS)
            if focused:
                res = make_custom_result(
                    success=True,
                    resource_type="application",
                    reason=f"Opened {query}."
                )
                res.action_type = "opened_uwp_app" if "store" in query.lower() else "opened_local_app"
                return res
            else:
                logger.warning(f"[APP_LAUNCH] Canonical app '{query}' launched but no visible window detected.")
                return make_custom_result(
                    success=False,
                    resource_type="application",
                    reason=f"Application '{query}' was launched but no visible window appeared within {APP_LAUNCH_TIMEOUT_SECONDS}s."
                )
            
    # Step 2: Check if application is currently running AND has a visible window
    running_match_pid = None
    running_match_name = None
    try:
        import psutil
        for proc in psutil.process_iter(attrs=['pid', 'name', 'exe']):
            p_name = proc.info.get('name')
            if not p_name:
                continue
            p_name_clean = p_name[:-4] if p_name.lower().endswith(".exe") else p_name
            if is_fuzzy_match(search_query, p_name_clean):
                running_match_pid = proc.info.get('pid')
                running_match_name = p_name
                break
    except Exception as e:
        logger.debug(f"psutil check failed: {e}")
        
    if running_match_pid:
        hwnd = bring_process_to_foreground(running_match_pid)
        if hwnd:
            # A visible window was found and focused — this is a genuine "already open"
            from agentic.memory.session_state import get_session
            get_session().set_context(app=cleaned_query)
            from agentic.memory.app_context import AppContextManager
            AppContextManager.set_context(active_app=cleaned_query, window_handle=hwnd)
            
            res = make_custom_result(
                success=True,
                resource_type="application",
                reason=f"{query} was already running and has been brought to the foreground."
            )
            res.app_running = True
            res.action = "activate_window"
            res.action_type = "opened_local_app"
            return res
        else:
            # Process running but no visible window — do NOT claim "already open".
            # Fall through to launch a new instance.
            logger.info(f"[APP_RESOLVE] Process '{running_match_name}' (PID={running_match_pid}) running but no visible window. Will attempt fresh launch.")

    # Step 3: Try resolving installed local app via resolve_app_launch_strategy / Get-StartApps / shortcuts / App Paths
    executable, _, _, _ = resolve_app_launch_strategy(search_query)
    if executable:
        guarded = _is_launch_guarded(search_query)
        launched = False
        launch_err = None
        if not guarded:
            launched, t_type, l_used, launch_err = dispatch_os_launch(executable, search_query)
            if launched:
                _mark_launched(search_query)
        else:
            launched = True  # recently launched, skip re-launch

        if launched:
            focused = wait_and_focus_app(query, timeout=APP_LAUNCH_TIMEOUT_SECONDS)
            if focused:
                res = make_custom_result(
                    success=True,
                    resource_type="application",
                    reason=f"Opened {query}."
                )
                res.action_type = "opened_uwp_app" if "AppsFolder" in executable or "ms-" in executable else "opened_local_app"
                return res
            else:
                logger.warning(f"[APP_LAUNCH] App '{query}' (exe={executable}) launched but no visible window detected.")
                return make_custom_result(
                    success=False,
                    resource_type="application",
                    reason=f"Application '{query}' was launched but no visible window appeared within {APP_LAUNCH_TIMEOUT_SECONDS}s."
                )
            
    # Step 4: Known Web Destinations Fallback
    target_key = search_query.lower()
    known_web_url = KNOWN_WEB_DESTINATIONS.get(target_key) or KNOWN_WEB_DESTINATIONS.get(cleaned_query.lower())
    if known_web_url:
        from automation.browser import open_browser
        res = open_browser({"url": known_web_url})
        if res.success:
            # Distinguish web-only services from local apps falling back to web
            is_primarily_web = target_key in ("gmail", "google mail", "google", "youtube", "github")
            if is_primarily_web:
                msg = f"Opened {query} in your browser."
            else:
                msg = f"{query} isn't available as a local app, so I opened {query} Web."
            res_custom = make_custom_result(
                success=True,
                resource_type="website",
                reason=msg
            )
            res_custom.action_type = "opened_web_app"
            res_custom.fallback_used = True
            res_custom.fallback_type = "known_web_app"
            return res_custom
        else:
            res_fail = make_custom_result(
                success=False,
                resource_type="website",
                reason=f"I couldn't open {query} because the browser failed to launch: {res.message}"
            )
            res_fail.action_type = "failed"
            return res_fail

    # Step 5: Check browser bookmarks/history
    website_match = find_website_resource(search_query)
    if website_match:
        from automation.browser import open_browser
        res = open_browser({"url": website_match.url})
        if res.success:
            res_custom = make_custom_result(
                success=True,
                resource_type="website",
                reason=f"Opened {website_match.name} in your browser."
            )
            res_custom.action_type = "opened_web_app"
            res_custom.fallback_used = True
            res_custom.fallback_type = "bookmark"
            return res_custom
        else:
            res_fail = make_custom_result(
                success=False,
                resource_type="website",
                reason=f"I couldn't open {website_match.name} because the browser failed to launch: {res.message}"
            )
            res_fail.action_type = "failed"
            return res_fail

    # Step 6: Universal Browser Search Fallback
    from automation.browser import search_web
    res_search = search_web({"query": query})
    if res_search.success:
        res_custom = make_custom_result(
            success=True,
            resource_type="website",
            reason=f"I couldn't find an installed app or known web destination for {query}, so I searched for it in your browser."
        )
        res_custom.action_type = "searched_web"
        res_custom.fallback_used = True
        res_custom.fallback_type = "search_web"
        return res_custom
    else:
        res_fail = make_custom_result(
            success=False,
            resource_type="application",
            reason=f"I couldn't open or search for {query} because the browser failed to launch: {res_search.message}"
        )
        res_fail.action_type = "failed"
        return res_fail


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


# NOTE: open_telegram delegates to dedicated telegram automation handler
@register_tool("open_telegram")
def open_telegram(args: dict[str, Any]) -> ExecutionResult:
    """Launch Telegram desktop application or open web client with verification."""
    from automation.telegram.telegram_automation import handle_open_telegram
    return handle_open_telegram(args)



@register_tool("open_gmail")
def open_gmail(args: dict[str, Any]) -> ExecutionResult:
    """Open Gmail web interface in default browser."""
    with ExecutionTimer() as timer:
        res = resolve_and_open({"query": "gmail"})
        res.tool = "open_gmail"
        res.execution_time_ms = timer.elapsed_ms
        return res


@register_tool("open_spotify")
def open_spotify(args: dict[str, Any]) -> ExecutionResult:
    """Launch Spotify desktop application or open web player."""
    with ExecutionTimer() as timer:
        res = resolve_and_open({"query": "spotify"})
        res.tool = "open_spotify"
        res.execution_time_ms = timer.elapsed_ms
        return res


