import sys
sys.stdout.reconfigure(encoding='utf-8')
import uiautomation as auto

root = auto.GetRootControl()
print("Desktop Root:", root)
for i, child in enumerate(root.GetChildren()):
    print(f"Top-level {i}: Name='{child.Name}' Type={child.ControlTypeName} Class='{child.ClassName}' Handle={child.NativeWindowHandle}")
