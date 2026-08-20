import ctypes
import ctypes.wintypes
import psutil

user32 = ctypes.windll.user32

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

hwnds = []

def enum_windows_callback(hwnd, extra):
    if user32.IsWindowVisible(hwnd):
        length = user32.GetWindowTextLengthW(hwnd)
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        
        c_len = 256
        c_buff = ctypes.create_unicode_buffer(c_len)
        user32.GetClassNameW(hwnd, c_buff, c_len)
        
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        
        title = buff.value
        cname = c_buff.value
        if "telegram" in title.lower() or "telegram" in cname.lower() or "qt" in cname.lower():
            hwnds.append((hwnd, title, cname, pid.value))
    return True

user32.EnumWindows(WNDENUMPROC(enum_windows_callback), 0)
print("Found windows via ctypes:", hwnds)
