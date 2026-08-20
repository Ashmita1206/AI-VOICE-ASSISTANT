import sys
import os
import time
import win32gui
import win32process
import psutil

print("Launching tg:// ...")
try:
    os.startfile("tg://")
except Exception as e:
    print("startfile tg:// error:", e)

for i in range(20):
    time.sleep(0.5)
    for p in psutil.process_iter(['pid', 'name']):
        try:
            if 'telegram' in (p.info.get('name') or '').lower():
                print(f"Found process: {p.info}")
        except Exception:
            pass

    hwnds = []
    def enum_cb(h, _):
        if win32gui.IsWindowVisible(h):
            cname = win32gui.GetClassName(h)
            title = win32gui.GetWindowText(h)
            if "telegram" in title.lower() or "qt" in cname.lower():
                hwnds.append((h, title, cname))
        return True
    win32gui.EnumWindows(enum_cb, None)
    if hwnds:
        print(f"Visible windows at {i*0.5}s:", hwnds)
        break
