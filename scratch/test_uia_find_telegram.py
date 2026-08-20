import sys
import os
import time
import uiautomation as auto

# Find Telegram window using uiautomation directly
for win in auto.GetRootControl().GetChildren():
    try:
        name = win.Name
        cname = win.ClassName
        pid = win.ProcessId
        if "telegram" in (name or "").lower() or "qt" in (cname or "").lower() or win.NativeWindowHandle:
            print(f"Window: Name={name!r} Class={cname!r} PID={pid} HWND={win.NativeWindowHandle} Rect={win.BoundingRectangle}")
    except Exception as e:
        pass
