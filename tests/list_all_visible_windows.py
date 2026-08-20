import sys, ctypes, ctypes.wintypes
sys.stdout.reconfigure(encoding='utf-8')
import psutil

windows = []
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

pid_to_name = {}
for p in psutil.process_iter(['pid', 'name']):
    try:
        pid_to_name[p.info['pid']] = p.info['name']
    except Exception:
        pass

def enum_windows_callback(hwnd, lparam):
    try:
        pid = ctypes.wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buff = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value
            
            cls_buff = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetClassNameW(hwnd, cls_buff, 256)
            cls = cls_buff.value
            
            vis = bool(ctypes.windll.user32.IsWindowVisible(hwnd))
            pname = pid_to_name.get(pid.value, "unknown")
            
            if vis:
                windows.append((hwnd, pid.value, pname, cls, title))
    except Exception:
        pass
    return True

cb = WNDENUMPROC(enum_windows_callback)
ctypes.windll.user32.EnumWindows(cb, 0)

print(f"Total visible windows with title: {len(windows)}")
for h, p, pname, cls, title in windows:
    print(f"  [{pname} ({p})] HWND={h} Class='{cls}' Title='{title}'")
