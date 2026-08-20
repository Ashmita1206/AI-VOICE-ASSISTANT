import sys
sys.stdout.reconfigure(encoding='utf-8')
import win32gui, win32process, psutil

telegram_pids = set()
for p in psutil.process_iter(['pid', 'name']):
    if 'telegram' in p.info['name'].lower():
        telegram_pids.add(p.info['pid'])

print("Telegram PIDs:", telegram_pids)

all_windows = []

def enum_cb(hwnd, _):
    try:
        if not win32gui.IsWindow(hwnd):
            return
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        title = win32gui.GetWindowText(hwnd)
        cls = win32gui.GetClassName(hwnd)
        vis = win32gui.IsWindowVisible(hwnd)
        rect = win32gui.GetWindowRect(hwnd)
        if pid in telegram_pids or 'telegram' in title.lower() or 'qt' in cls.lower():
            all_windows.append((hwnd, pid, cls, title, vis, rect))
    except Exception as e:
        pass

win32gui.EnumWindows(enum_cb, None)

print(f"Found {len(all_windows)} matching windows:")
for h, pid, cls, title, vis, rect in all_windows:
    print(f"  HWND={h} PID={pid} Class='{cls}' Title='{title}' Visible={vis} Rect={rect}")
