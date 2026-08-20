import sys, os, time, subprocess
sys.stdout.reconfigure(encoding='utf-8')
import win32gui, win32process, psutil

print("1. Testing protocol start...")
os.system("start tg://")
time.sleep(2.0)

windows = []
def cb(h, _):
    try:
        t = win32gui.GetWindowText(h)
        c = win32gui.GetClassName(h)
        if "telegram" in t.lower() or "qt" in c.lower():
            windows.append((h, c, t, win32gui.IsWindowVisible(h)))
    except Exception:
        pass

win32gui.EnumWindows(cb, None)
print(f"Windows after 'start tg://': {windows}")

if not windows:
    print("2. Killing stale background Telegram.exe and starting fresh...")
    for p in psutil.process_iter(['pid', 'name']):
        if 'telegram' in p.info['name'].lower():
            p.kill()
    time.sleep(1.0)
    
    # Start fresh
    os.system("start shell:AppsFolder\\TelegramMessengerLLP.TelegramDesktop_t4vj0pshhgkwm!Telegram.TelegramDesktop.Store")
    time.sleep(3.0)
    
    windows2 = []
    def cb2(h, _):
        try:
            t = win32gui.GetWindowText(h)
            c = win32gui.GetClassName(h)
            if "telegram" in t.lower() or "qt" in c.lower():
                windows2.append((h, c, t, win32gui.IsWindowVisible(h)))
        except Exception:
            pass
    win32gui.EnumWindows(cb2, None)
    print(f"Windows after fresh AppX start: {windows2}")
