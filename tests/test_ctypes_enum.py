import sys
import os
import time
sys.path.insert(0, os.path.abspath("."))
sys.stdout.reconfigure(encoding='utf-8')

import win32gui
import win32process
import psutil
import uiautomation as auto
import pyautogui
pyautogui.FAILSAFE = False

import win32con

def find_telegram_hwnd():
    telegram_pids = set()
    for p in psutil.process_iter(['pid', 'name']):
        try:
            if 'telegram' in (p.info.get('name') or '').lower():
                telegram_pids.add(p.info['pid'])
        except Exception:
            pass

    valid_hwnds = []
    
    # Method 1: EnumWindows with safe callback
    def enum_cb(h, _):
        try:
            if win32gui.IsWindow(h):
                _, pid = win32process.GetWindowThreadProcessId(h)
                cname = win32gui.GetClassName(h)
                title = win32gui.GetWindowText(h)
                rect = win32gui.GetWindowRect(h)
                w = rect[2] - rect[0]
                h_len = rect[3] - rect[1]
                if (pid in telegram_pids or (cname.startswith("Qt") and "QWindowIcon" in cname) or "telegram" in title.lower()) and "tray" not in cname.lower() and "message" not in cname.lower() and w > 300 and h_len > 200:
                    valid_hwnds.append((h, cname, rect, title))
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(enum_cb, None)
    except Exception:
        pass

    if valid_hwnds:
        return valid_hwnds[0][0]

    # Method 2: GetWindow loop
    try:
        h = win32gui.GetTopWindow(0)
        while h:
            try:
                if win32gui.IsWindow(h):
                    _, pid = win32process.GetWindowThreadProcessId(h)
                    cname = win32gui.GetClassName(h)
                    title = win32gui.GetWindowText(h)
                    rect = win32gui.GetWindowRect(h)
                    w = rect[2] - rect[0]
                    h_len = rect[3] - rect[1]
                    if (pid in telegram_pids or (cname.startswith("Qt") and "QWindowIcon" in cname) or "telegram" in title.lower()) and "tray" not in cname.lower() and "message" not in cname.lower() and w > 300 and h_len > 200:
                        return h
            except Exception:
                pass
            h = win32gui.GetWindow(h, win32con.GW_HWNDNEXT)
    except Exception:
        pass

    return None

from automation.telegram.telegram_automation import find_telegram_desktop, _focus_telegram_desktop
from automation.applications import resolve_app_launch_strategy, dispatch_os_launch

hwnd = find_telegram_hwnd()
if not hwnd:
    telegram_exe = find_telegram_desktop()
    print("find_telegram_desktop:", telegram_exe, flush=True)
    if telegram_exe:
        import subprocess
        subprocess.Popen([telegram_exe], shell=False)
    else:
        os.startfile("tg://")
    for _ in range(20):
        time.sleep(0.4)
        hwnd = find_telegram_hwnd()
        if hwnd:
            break

print("Found Telegram HWND:", hwnd, flush=True)


if hwnd:
    from automation.applications import force_focus_window
    force_focus_window(hwnd)
    time.sleep(0.4)

    ctrl = auto.ControlFromHandle(hwnd)
    print("Root Control:", ctrl, flush=True)

    pyautogui.press("escape")
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "f")
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "a")
    pyautogui.press("delete")
    pyautogui.write("harshita", interval=0.04)
    time.sleep(1.2)

    print("\n=== All Controls after typing 'harshita' ===", flush=True)
    def inspect_node(node, depth=0):
        if depth > 10:
            return
        try:
            children = node.GetChildren()
        except Exception:
            return
        for child in children:
            name = (child.Name or "").strip()
            ctype = child.ControlTypeName
            aid = child.AutomationId or ""
            cname = child.ClassName or ""
            rect = child.BoundingRectangle
            print(f"{'  '*depth}[{ctype}] Name='{name}' AutoId='{aid}' Class='{cname}' Rect={rect} Offscreen={child.IsOffscreen}", flush=True)
            inspect_node(child, depth + 1)

    # Let's inspect the Chats list specifically
    chats_list = None
    for c in auto.WalkControl(ctrl, maxDepth=8):
        control = c[0] if isinstance(c, tuple) else c
        if control.ControlTypeName == "ListControl" and (control.Name == "Chats" or "dialogs" in (control.ClassName or "").lower() or "dialogs" in (control.AutomationId or "").lower()):
            chats_list = control
            break

    if chats_list:
        print("\n=== Found Chats / Dialogs List ===", flush=True)
        print(f"List: Name='{chats_list.Name}' Rect={chats_list.BoundingRectangle}", flush=True)
        for idx, item in enumerate(chats_list.GetChildren()):
            print(f"  Item {idx}: [{item.ControlTypeName}] Name='{item.Name}' Rect={item.BoundingRectangle}", flush=True)
    else:
        print("\n=== Chats list not found directly, walking all ===", flush=True)
        inspect_node(ctrl)










