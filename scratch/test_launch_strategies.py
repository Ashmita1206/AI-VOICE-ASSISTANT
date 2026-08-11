"""
Test Windows Launch Strategies for Win32 & Office Apps
======================================================
"""

import sys
import os
import winreg
import subprocess

def find_app_path_from_registry(app_exe):
    """Query Windows Registry App Paths for full executable path."""
    sub_key = f"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\{app_exe}"
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root, sub_key) as key:
                val, _ = winreg.QueryValueEx(key, "")
                if val and os.path.exists(val):
                    return val
        except Exception:
            pass
    return None

def test_strategies():
    print("=" * 70)
    print("TESTING WINDOWS APP LAUNCH STRATEGIES")
    print("=" * 70)

    test_apps = ["winword.exe", "powerpnt.exe", "excel.exe", "calc.exe", "notepad.exe"]

    for app in test_apps:
        print(f"\nTarget: {app}")

        # 1. Registry App Path Lookups
        reg_path = find_app_path_from_registry(app)
        print(f"  1. Registry App Path: {reg_path}")

        # 2. Strategy A: Popen full path (if reg_path exists)
        if reg_path:
            try:
                proc = subprocess.Popen([reg_path])
                print(f"  2. Popen full path ({reg_path}): SUCCESS (PID {proc.pid})")
            except Exception as e:
                print(f"  2. Popen full path: FAILED -> {e}")

        # 3. Strategy B: os.startfile(app)
        try:
            os.startfile(app)
            print(f"  3. os.startfile({app}): SUCCESS")
        except Exception as e:
            print(f"  3. os.startfile({app}): FAILED -> {e}")

        # 4. Strategy C: cmd /c start app
        try:
            proc = subprocess.Popen(["cmd.exe", "/c", "start", "", app], shell=False)
            print(f"  4. cmd.exe /c start {app}: SUCCESS (PID {proc.pid})")
        except Exception as e:
            print(f"  4. cmd.exe /c start {app}: FAILED -> {e}")

if __name__ == "__main__":
    test_strategies()
