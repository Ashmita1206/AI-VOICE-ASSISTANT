import uiautomation as auto
root = auto.GetRootControl()
children = root.GetChildren()
print(f"Total root children: {len(children)}")
for c in children:
    try:
        print(f"[{c.ControlTypeName}] Name={c.Name!r} Class={c.ClassName!r} PID={c.ProcessId} HWND={c.NativeWindowHandle}")
    except Exception as e:
        print("Error:", e)
