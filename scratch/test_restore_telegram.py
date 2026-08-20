import ctypes
import ctypes.wintypes
import psutil
import time

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

telegram_pids = set()
for p in psutil.process_iter(['pid', 'name']):
    try:
        if 'telegram' in (p.info.get('name') or '').lower():
            telegram_pids.add(p.info['pid'])
    except Exception:
        pass

print("Telegram PIDs:", telegram_pids)

all_tg_hwnds = []

def enum_cb(hwnd, _):
    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value in telegram_pids:
        length = user32.GetWindowTextLengthW(hwnd)
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        c_buff = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, c_buff, 256)
        vis = user32.IsWindowVisible(hwnd)
        all_tg_hwnds.append((hwnd, buff.value, c_buff.value, vis))
    return True

user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
print("All Telegram HWNDs:", all_tg_hwnds)

for h, title, cname, vis in all_tg_hwnds:
    if "icon" in cname.lower() or "qt" in cname.lower() or "telegram" in title.lower():
        print(f"Restoring and showing HWND {h} ({title}, {cname})...")
        user32.ShowWindow(h, 9) # SW_RESTORE
        user32.SetForegroundWindow(h)
        time.sleep(0.5)

time.sleep(1)
print("After restore, visible state:")
for h, title, cname, _ in all_tg_hwnds:
    print(f"HWND {h} isVisible={bool(user32.IsWindowVisible(h))}")
