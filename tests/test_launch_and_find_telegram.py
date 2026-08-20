import sys, os, time
sys.stdout.reconfigure(encoding='utf-8')
from automation.applications import resolve_app_launch_strategy, dispatch_os_launch, force_focus_window
import win32gui, win32process, psutil

strat = resolve_app_launch_strategy("telegram")
print("Launch strategy:", strat)

target = strat[0] if isinstance(strat, tuple) else (strat.get("target") or "telegram")
disp = dispatch_os_launch(target, "telegram")
print("Dispatch result:", disp)

time.sleep(3.0)

telegram_pids = set()
for p in psutil.process_iter(['pid', 'name']):
    if 'telegram' in p.info['name'].lower():
        telegram_pids.add(p.info['pid'])

print("Active Telegram PIDs:", telegram_pids)

windows = []
def cb(h, _):
    try:
        _, p = win32process.GetWindowThreadProcessId(h)
        if p in telegram_pids:
            title = win32gui.GetWindowText(h)
            cls = win32gui.GetClassName(h)
            vis = win32gui.IsWindowVisible(h)
            rect = win32gui.GetWindowRect(h)
            windows.append((h, p, cls, title, vis, rect))
    except Exception:
        pass

win32gui.EnumWindows(cb, None)
print(f"Found {len(windows)} Telegram windows:")
for h, p, cls, title, vis, rect in windows:
    print(f"  HWND={h} PID={p} Class='{cls}' Title='{title}' Visible={vis} Rect={rect}")
