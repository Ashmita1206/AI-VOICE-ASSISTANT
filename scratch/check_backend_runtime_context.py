"""
Backend Runtime Environment & Direct OS Launcher Diagnostic
============================================================
"""

import sys
import os
import platform
import subprocess

def run_diagnostic():
    print("=" * 70)
    print("BACKEND RUNTIME ENVIRONMENT DIAGNOSTIC")
    print("=" * 70)
    print(f"Python Executable: {sys.executable}")
    print(f"Platform: {sys.platform}")
    print(f"OS System: {platform.system()} {platform.release()} ({platform.version()})")
    print(f"Working Directory: {os.getcwd()}")
    print(f"Is Windows: {sys.platform.startswith('win')}")
    print(f"USER / USERNAME: {os.environ.get('USERNAME') or os.environ.get('USER')}")
    print("=" * 70)

    print("\n[DIRECT OS LAUNCHER TESTS]")
    
    # 1. Calculator (Win32 / system utility)
    try:
        proc = subprocess.Popen(["calc.exe"])
        print(f"1. Calculator (calc.exe): Popen launched with PID {proc.pid}")
    except Exception as e:
        print(f"1. Calculator (calc.exe): FAILED -> {e}")

    # 2. Notepad (Win32)
    try:
        proc = subprocess.Popen(["notepad.exe"])
        print(f"2. Notepad (notepad.exe): Popen launched with PID {proc.pid}")
    except Exception as e:
        print(f"2. Notepad (notepad.exe): FAILED -> {e}")

    # 3. Microsoft Store (UWP URI)
    try:
        if hasattr(os, "startfile"):
            os.startfile("ms-windows-store:")
            print(f"3. Microsoft Store (ms-windows-store:): os.startfile dispatched successfully")
        else:
            subprocess.Popen(["cmd.exe", "/c", "start", "ms-windows-store:"], shell=True)
            print(f"3. Microsoft Store (ms-windows-store:): cmd /c start dispatched successfully")
    except Exception as e:
        print(f"3. Microsoft Store (ms-windows-store:): FAILED -> {e}")

    # 4. Ubuntu / WSL
    try:
        proc = subprocess.Popen(["wsl.exe", "-d", "Ubuntu"])
        print(f"4. Ubuntu WSL (wsl.exe -d Ubuntu): Popen launched with PID {proc.pid}")
    except Exception as e:
        print(f"4. Ubuntu WSL (wsl.exe -d Ubuntu): FAILED -> {e}")

    # 5. Word (winword.exe)
    try:
        proc = subprocess.Popen(["winword.exe"])
        print(f"5. Word (winword.exe): Popen launched with PID {proc.pid}")
    except Exception as e:
        print(f"5. Word (winword.exe): FAILED -> {e}")

    # 6. PowerPoint (powerpnt.exe)
    try:
        proc = subprocess.Popen(["powerpnt.exe"])
        print(f"6. PowerPoint (powerpnt.exe): Popen launched with PID {proc.pid}")
    except Exception as e:
        print(f"6. PowerPoint (powerpnt.exe): FAILED -> {e}")

    print("=" * 70)

if __name__ == "__main__":
    run_diagnostic()
