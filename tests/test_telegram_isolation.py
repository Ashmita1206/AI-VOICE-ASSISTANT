import sys
import os
import time
sys.path.insert(0, os.path.abspath("."))
sys.stdout.reconfigure(encoding='utf-8')

import win32gui
import win32process
import psutil
import uiautomation as auto

print("=== Running Processes matching 'telegram' ===")
for p in psutil.process_iter(['pid', 'name', 'exe']):
    if 'telegram' in (p.info.get('name') or '').lower():
        print(f"PID={p.info['pid']} Name={p.info['name']} Exe={p.info['exe']}")

auto.SetGlobalSearchTimeout(2.0)
print("=== UIA WindowControls ===", flush=True)
for w in auto.GetRootControl().GetChildren():
    print("Child:", w.Name, w.ClassName, w.NativeWindowHandle, flush=True)

win = auto.WindowControl(searchDepth=1, ClassName="class MainWindow")
print("WindowControl search:", win.Exists(1), win, flush=True)









print("\n=== STEP 3: search_telegram_contact('harshita') ===", flush=True)
search_res = handle_search_telegram_contact({"contact": "harshita"})
print("search_telegram_contact result:", search_res.success, search_res.message, search_res.data, flush=True)
assert search_res.success, f"search_telegram_contact failed: {search_res.message}"

print("\n=== STEP 4: verify_telegram_contact ===", flush=True)
verify_res = handle_verify_telegram_contact({"contact": "harshita"})
print("verify_telegram_contact result:", verify_res.success, verify_res.message, verify_res.data, flush=True)
assert verify_res.success, f"verify_telegram_contact failed: {verify_res.message}"

selected = _telegram_state.get("contact")
print("Selected contact:", selected, flush=True)
assert selected is not None, "No contact selected!"
assert selected.name == "Harshita", f"Expected 'Harshita' but got '{selected.name}'"

print("\n=== ALL ISOLATION CHECKS PASSED SUCCESSFULLY! ===", flush=True)
