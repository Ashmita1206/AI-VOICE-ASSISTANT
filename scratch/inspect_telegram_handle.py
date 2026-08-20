from automation.telegram.telegram_automation import _get_telegram_window_handle, _uia_window, _iter_uia_descendants
import uiautomation as auto
import win32gui

h = _get_telegram_window_handle()
print("Handle from _get_telegram_window_handle:", h)
if h:
    print("Title:", win32gui.GetWindowText(h))
    print("Class:", win32gui.GetClassName(h))
    win = auto.ControlFromHandle(h)
    if win:
        print("Root control:", win.ControlTypeName, win.Name)
        for ctrl in _iter_uia_descendants(win, max_depth=6):
            name = ctrl.Name
            ctype = ctrl.ControlTypeName
            rect = ctrl.BoundingRectangle
            rect_str = f"({rect.left},{rect.top},{rect.right},{rect.bottom})" if rect else "None"
            print(f"  [{ctype}] Name='{name}' Rect={rect_str}")
