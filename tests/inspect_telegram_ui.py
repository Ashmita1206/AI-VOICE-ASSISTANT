import sys
import os
sys.path.insert(0, os.path.abspath("."))
sys.stdout.reconfigure(encoding='utf-8')

import win32gui
import win32process
import psutil

print("=== All Visible Windows ===")
def enum_cb(hwnd, extra):
    if win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd):
        title = win32gui.GetWindowText(hwnd)
        cname = win32gui.GetClassName(hwnd)
        rect = win32gui.GetWindowRect(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            pname = psutil.Process(pid).name()
        except Exception:
            pname = "?"
        if (rect[2] - rect[0] > 100) and (rect[3] - rect[1] > 100):
            print(f"HWND={hwnd} PID={pid} ({pname}) Class='{cname}' Title='{title}' Rect={rect}")
    return True

win32gui.EnumWindows(enum_cb, None)




