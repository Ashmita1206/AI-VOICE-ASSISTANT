import sys
import os
import time
import uiautomation as auto
import win32gui
import win32process
import win32con
import pyautogui

sys.path.insert(0, ".")

from automation.telegram.telegram_automation import (
    handle_open_telegram,
    handle_search_telegram_contact,
    handle_verify_telegram_contact,
    _get_telegram_window_handle,
    _uia_window,
    _iter_uia_descendants,
    _focus_telegram_desktop,
    ensure_telegram_foreground,
    _chat_header_matches,
    _telegram_state
)

def run_test():
    print("=== 1. Open Telegram ===")
    res_open = handle_open_telegram({})
    print("res_open:", res_open.to_dict())
    time.sleep(2)

    hwnd = _get_telegram_window_handle()
    print(f"Telegram HWND: {hwnd}")
    if not hwnd:
        print("ERROR: Telegram window not found.")
        return

    print("=== 2. Search for harshita ===")
    res_search = handle_search_telegram_contact({"contact": "harshita"})
    print("res_search:", res_search.to_dict())
    time.sleep(2)

    print("=== 3. Inspect UI Controls during search results ===")
    win = auto.ControlFromHandle(hwnd)
    if win:
        print(f"Window Rect: {win.BoundingRectangle}")
        print("\n--- ALL VISIBLE CONTROLS ---")
        for c in _iter_uia_descendants(win, max_depth=8):
            try:
                name = c.Name
                ctype = c.ControlTypeName
                rect = c.BoundingRectangle
                if name or ctype in ("ListItemControl", "EditControl", "ButtonControl"):
                    print(f"  [{ctype}] Name={name!r} Rect={rect} Patterns={c.GetSupportedPatterns()}")
            except Exception as e:
                pass

if __name__ == "__main__":
    run_test()
