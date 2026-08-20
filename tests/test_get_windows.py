import sys
sys.stdout.reconfigure(encoding='utf-8')
import win32gui, win32con, win32process, psutil

hwnd = win32gui.GetDesktopWindow()
child = win32gui.GetWindow(hwnd, win32con.GW_CHILD)

count = 0
telegram_hwnds = []

while child:
    if win32gui.IsWindowVisible(child):
        title = win32gui.GetWindowText(child)
        cls = win32gui.GetClassName(child)
        _, pid = win32process.GetWindowThreadProcessId(child)
        try:
            pname = psutil.Process(pid).name()
        except Exception:
            pname = "unknown"
            
        if title:
            print(f"HWND={child} PID={pid} ({pname}) Class='{cls}' Title='{title}'")
        if 'telegram' in pname.lower() or 'telegram' in title.lower() or 'qt' in cls.lower():
            telegram_hwnds.append((child, pid, pname, cls, title))
        count += 1
    child = win32gui.GetWindow(child, win32con.GW_HWNDNEXT)

print(f"\nTotal visible windows checked: {count}")
print(f"Telegram-matching HWNDs: {telegram_hwnds}")
