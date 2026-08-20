import sys
import os
import uiautomation as auto

def inspect():
    # Find Telegram window
    hwnds = []
    import win32gui
    def enum_cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if "telegram" in title.lower():
                hwnds.append((hwnd, title))
    win32gui.EnumWindows(enum_cb, None)
    print("Found Telegram HWNDs:", hwnds)

    if not hwnds:
        print("No Telegram window found.")
        return

    hwnd = hwnds[0][0]
    print(f"Inspecting HWND {hwnd} ({hwnds[0][1]}):")
    win = auto.ControlFromHandle(hwnd)
    if not win:
        print("Could not get ControlFromHandle")
        return

    # Print all controls with depth and details
    def dump_control(ctrl, depth=0):
        try:
            name = ctrl.Name
            ctype = ctrl.ControlTypeName
            rect = ctrl.BoundingRectangle
            rect_str = f"({rect.left},{rect.top},{rect.right},{rect.bottom})" if rect else "None"
            print(f"{'  '*depth}[{ctype}] Name='{name}' Rect={rect_str}")
            for child in ctrl.GetChildren():
                dump_control(child, depth+1)
        except Exception as e:
            print(f"{'  '*depth}Error: {e}")

    dump_control(win, 0)

if __name__ == "__main__":
    inspect()
