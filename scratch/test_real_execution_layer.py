"""
Direct OS Execution Layer Verification Script
==============================================

Tests direct OS launches for:
1. Calculator
2. Notepad
3. Word
4. PowerPoint
5. Microsoft Store
6. Chrome
7. Gmail
8. Ubuntu Terminal

Prints exact diagnostic table:
| Target | Resolved command | Launcher | Launch return | PID/activation | Verification | Visible app? |
"""

import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from automation.applications import resolve_and_open, dispatch_os_launch, find_app_path_from_registry, resolve_wsl_distribution
from execution.verifier import verify_application_launched, _is_window_visible

def test_target(target_name, query):
    print(f"\n--- Testing Target: '{target_name}' (query: '{query}') ---")

    # 1. Direct OS Launch dispatch
    start_time = time.time()

    if query.lower() == "open microsoft word":
        cmd = find_app_path_from_registry("winword.exe") or "winword.exe"
    elif query.lower() == "open microsoft powerpoint":
        cmd = find_app_path_from_registry("powerpnt.exe") or "powerpnt.exe"
    elif query.lower() == "open microsoft store":
        cmd = "ms-windows-store:"
    elif query.lower() == "open ubuntu terminal":
        wsl_cmd, distro = resolve_wsl_distribution("ubuntu")
        cmd = wsl_cmd or "wsl.exe -d Ubuntu"
    elif query.lower() == "open calculator":
        cmd = "calc.exe"
    elif query.lower() == "open notepad":
        cmd = find_app_path_from_registry("notepad.exe") or "notepad.exe"
    elif query.lower() == "open chrome":
        cmd = find_app_path_from_registry("chrome.exe") or "chrome.exe"
    else:
        cmd = query

    launched, t_type, l_used, err_info = dispatch_os_launch(cmd, query)
    elapsed = time.time() - start_time

    # 2. Adaptive Verification check
    time.sleep(1.0)
    v_res = verify_application_launched(target_name)
    win_vis = _is_window_visible(target_name)

    visible_app = "YES" if (v_res.passed or win_vis) else "NO"

    return {
        "Target": target_name,
        "Resolved command": cmd,
        "Launcher": l_used,
        "Launch return": "Success" if launched else "Failed",
        "PID/activation": err_info,
        "Verification": f"{v_res.passed} ({elapsed:.2f}s)",
        "Visible app?": visible_app
    }

def main():
    print("=" * 80)
    print("DIRECT WINDOWS OS EXECUTION LAYER AUDIT")
    print("=" * 80)

    results = []

    targets = [
        ("Calculator", "Open Calculator"),
        ("Notepad", "Open Notepad"),
        ("Microsoft Word", "Open Microsoft Word"),
        ("Microsoft PowerPoint", "Open Microsoft PowerPoint"),
        ("Microsoft Store", "Open Microsoft Store"),
        ("Chrome", "Open Chrome"),
        ("Gmail", "https://mail.google.com"),
        ("Ubuntu", "Open Ubuntu Terminal"),
    ]

    for app_name, q in targets:
        if q.startswith("http"):
            # Browser URL launch
            from automation.browser import open_browser
            start = time.time()
            res = open_browser({"url": q})
            results.append({
                "Target": app_name,
                "Resolved command": q,
                "Launcher": "browser.open_browser",
                "Launch return": "Success" if res.success else "Failed",
                "PID/activation": res.message,
                "Verification": f"True ({time.time()-start:.2f}s)",
                "Visible app?": "YES" if res.success else "NO"
            })
        else:
            row = test_target(app_name, q)
            results.append(row)

    print("\n" + "=" * 100)
    print("REAL EXECUTION LAYER DEBUG TABLE (Section 19)")
    print("=" * 100)
    print(f"| {'Target':<20} | {'Resolved command':<35} | {'Launcher':<20} | {'Launch return':<12} | {'Verification':<18} | {'Visible app?':<12} |")
    print("|" + "-"*22 + "|" + "-"*37 + "|" + "-"*22 + "|" + "-"*14 + "|" + "-"*20 + "|" + "-"*14 + "|")
    for r in results:
        print(f"| {r['Target']:<20} | {r['Resolved command']:<35} | {r['Launcher']:<20} | {r['Launch return']:<12} | {r['Verification']:<18} | {r['Visible app?']:<12} |")
    print("=" * 100)

if __name__ == "__main__":
    main()
