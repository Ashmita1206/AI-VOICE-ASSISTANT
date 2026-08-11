"""
Browser Automation & Search Tools
==================================

Provides tools for opening websites, searching the web, and launching browsers.
"""

import os
import webbrowser
import urllib.parse
import subprocess
import sys
import platform
import logging
from typing import Any

import config
from config import get_logger
from execution.registry import register_tool
from execution.schemas import ExecutionResult, ExecutionTimer

logger = get_logger(__name__)

# Alias mapping for the `webbrowser` module
_BROWSER_ALIASES = {
    "chrome": "google-chrome",
    "firefox": "firefox",
    "edge": "edge",
}

def find_and_focus_browser_tab(url: str) -> bool:
    """Check whether a browser tab matching *url* is already open and focus it.

    On Windows, walks all top-level windows via ``uiautomation`` looking for a
    browser tab whose title contains a recognisable fragment of *url* (the
    hostname).  When a match is found the tab is selected and the browser window
    is brought to the foreground.

    On macOS, uses AppleScript to query Chrome directly.

    Returns ``True`` if a matching tab was found and focused, ``False``
    otherwise.  All exceptions are suppressed so callers can always fall back to
    opening a new tab without raising.
    """
    if not url:
        return False

    # ---- macOS: AppleScript path ----
    if platform.system() == "Darwin":
        try:
            script = f'''
            tell application "Google Chrome"
                set found to false
                repeat with w in windows
                    repeat with t in tabs of w
                        if URL of t contains "{url}" then
                            set active tab index of w to (index of t)
                            set index of w to 1
                            set found to true
                        end if
                    end repeat
                end repeat
                return found
            end tell
            '''
            result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
            return "true" in result.stdout.lower()
        except Exception:
            pass
        return False

    # ---- Windows: uiautomation path ----
    # Derive a short hostname fragment for tab-title matching.
    # e.g. "https://web.whatsapp.com/some/path" -> "web.whatsapp.com"
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc.lower()
        # Strip "www." so "www.youtube.com" matches a tab titled "YouTube"
        host_no_www = host.lstrip("www.")
        path_parts = [p for p in parsed.path.split("/") if p]
        path_hint = path_parts[0].lower() if path_parts else ""
    except Exception:
        host = url.lower()
        host_no_www = host
        path_hint = ""

    try:
        # pyrefly: ignore [missing-import]
        import uiautomation as auto

        try:
            import win32gui
        except ImportError:
            win32gui = None

        root = auto.GetRootControl()

        for browser_win in root.GetChildren():
            if not _window_is_browser(browser_win):
                continue

            matched_tab = _find_tab_by_url_hint(
                browser_win, host, host_no_www, path_hint, depth=0
            )
            if matched_tab is not None:
                _select_tab(matched_tab)
                _focus_window(browser_win, win32gui)
                return True

    except Exception:
        pass

    return False


# ---------------------------------------------------------------------------
# Private helpers for find_and_focus_browser_tab (Windows)
# ---------------------------------------------------------------------------

def _window_is_browser(control) -> bool:
    """Return True when *control* looks like a browser window."""
    try:
        name = (control.Name or "").lower()
        class_name = (control.ClassName or "").lower()
        keywords = ("chrome", "firefox", "mozilla", "edge", "opera", "brave", "chromium")
        return any(kw in name or kw in class_name for kw in keywords)
    except Exception:
        return False


def _find_tab_by_url_hint(
    root_control,
    host: str,
    host_no_www: str,
    path_hint: str,
    depth: int,
):
    """Recursively search *root_control*'s children for a matching tab item.

    A tab item matches when its label contains the hostname (with or without
    "www.") or, as a secondary hint, the first path segment.

    Returns the matching control or ``None``.
    """
    if depth > 10:
        return None

    try:
        children = root_control.GetChildren()
    except Exception:
        return None

    for child in children:
        try:
            ctrl_type = child.ControlTypeName
            name = (child.Name or "").lower()

            if ctrl_type in ("TabItemControl", "ListItemControl"):
                if host and host in name:
                    return child
                if host_no_www and host_no_www in name:
                    return child
                if path_hint and path_hint in name:
                    return child

            result = _find_tab_by_url_hint(child, host, host_no_www, path_hint, depth + 1)
            if result is not None:
                return result
        except Exception:
            continue

    return None


def _select_tab(tab_control) -> None:
    """Activate *tab_control* via the SelectionItem pattern or a click."""
    try:
        pattern = tab_control.GetSelectionItemPattern()
        if pattern:
            pattern.Select()
            return
    except Exception:
        pass
    try:
        tab_control.Click(simulateMove=False)
    except Exception:
        pass


def _focus_window(window_control, win32gui) -> None:
    """Bring *window_control* to the foreground."""
    try:
        window_control.SetFocus()
    except Exception:
        pass
    if win32gui:
        try:
            import ctypes
            hwnd = window_control.NativeWindowHandle
            if hwnd:
                if win32gui.IsIconic(hwnd):
                    win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE
                win32gui.BringWindowToTop(hwnd)
                win32gui.SetForegroundWindow(hwnd)
                ctypes.windll.user32.SetActiveWindow(hwnd)
        except Exception:
            pass

def launch_url_in_browser(url: str, browser_name: str = "") -> tuple[bool, str]:
    """
    Launch a URL in the real Windows desktop browser.

    On Windows, os.startfile() is used as the primary launcher because it
    delegates the URL to the interactive user's registered browser handler.
    """
    if not url:
        return False, "No URL provided."

    # If the requested URL is already open, focus that tab first.
    try:
        if find_and_focus_browser_tab(url):
            logger.info(f"[BROWSER_LAUNCH] Focused existing browser tab: {url}")
            return True, f"Focused existing tab for {url}."
    except Exception as ex:
        logger.debug(f"[BROWSER_LAUNCH] Existing-tab detection failed: {ex}")

    # ---------------------------------------------------------
    # WINDOWS — REAL DESKTOP URL EXECUTION
    # ---------------------------------------------------------
    if sys.platform.startswith("win"):
        try:
            logger.info(
                f"[BROWSER_LAUNCH] Opening URL with Windows os.startfile: {url}"
            )

            # This has been manually verified on this machine to actually
            # open the URL in the user's interactive desktop browser.
            os.startfile(url)

            return True, f"Opened browser to {url}."

        except OSError as ex:
            logger.exception(
                f"[BROWSER_LAUNCH] Windows os.startfile failed for {url}"
            )
            return False, f"Failed to open browser URL '{url}': {ex}"

        except Exception as ex:
            logger.exception(
                f"[BROWSER_LAUNCH] Unexpected browser launch failure for {url}"
            )
            return False, f"Failed to launch browser: {ex}"

    # ---------------------------------------------------------
    # NON-WINDOWS FALLBACK
    # ---------------------------------------------------------
    try:
        b_name = browser_name.lower().strip()

        if b_name and b_name in _BROWSER_ALIASES:
            try:
                browser_inst = webbrowser.get(_BROWSER_ALIASES[b_name])
                opened = browser_inst.open_new_tab(url)
            except Exception:
                opened = webbrowser.open_new_tab(url)
        else:
            opened = webbrowser.open_new_tab(url)

        if opened is False:
            return False, f"System browser launcher returned failure for '{url}'."

        return True, f"Opened browser to {url}."

    except Exception as ex:
        logger.exception(f"[BROWSER_LAUNCH] Browser launch failed for {url}")
        return False, f"Failed to launch browser: {ex}"

@register_tool("open_browser")
def open_browser(args: dict[str, Any]) -> ExecutionResult:
    """Launch the default web browser and open an optional URL."""
    browser_name = args.get("browser", "").lower()
    url = args.get("url", "")
    
    # If the URL is actually a website query name (e.g. "chatgpt"), resolve it
    if url and not (url.startswith("http://") or url.startswith("https://")):
        from agentic.discovery.manager import resolve_best_resource
        res = resolve_best_resource(url, f"open {url}")
        if res:
            if res.type == "application":
                from automation.applications import open_application
                return open_application({"application": res.name})
            elif res.type == "folder":
                from automation.filesystem import open_folder
                return open_folder({"path": res.path})
            elif res.type == "file":
                from automation.filesystem import open_file
                return open_file({"path": res.path})
            elif res.type == "website" and res.url:
                url = res.url
        else:
            if "." in url:
                url = "https://" + url
            else:
                return search_web({"query": url, "application": browser_name})
                
    with ExecutionTimer() as timer:
        ok, msg = launch_url_in_browser(url, browser_name)
        return ExecutionResult(
            success=ok,
            tool="open_browser",
            message=msg,
            execution_time_ms=timer.elapsed_ms
        )

@register_tool("open_website")
def open_website(args: dict[str, Any]) -> ExecutionResult:
    """Open a specific URL in the default browser."""
    url = args.get("url", "")
    if not url:
        return ExecutionResult(success=False, tool="open_website", message="No URL provided.")
        
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url
        
    with ExecutionTimer() as timer:
        ok, msg = launch_url_in_browser(url, "")
        return ExecutionResult(
            success=ok,
            tool="open_website",
            message=f"Opened website: {url}" if ok else msg,
            execution_time_ms=timer.elapsed_ms
        )

@register_tool("search_web")
def search_web(args: dict[str, Any]) -> ExecutionResult:
    """Search the internet for a specific query."""
    query = args.get("query", "")
    browser_name = args.get("application", "") or args.get("browser", "")
    if not query:
        return ExecutionResult(
            success=False,
            tool="search_web",
            message="No search query provided."
        )
        
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://www.google.com/search?q={encoded_query}"
    
    with ExecutionTimer() as timer:
        ok, msg = launch_url_in_browser(url, browser_name)
        return ExecutionResult(
            success=ok,
            tool="search_web",
            message=f"Searched web for: {query}" if ok else f"Search launch failed: {msg}",
            execution_time_ms=timer.elapsed_ms
        )

