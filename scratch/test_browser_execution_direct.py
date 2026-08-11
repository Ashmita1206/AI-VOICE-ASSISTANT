"""
Direct Low-Level Browser Execution Verification Script
=====================================================

Tests launching:
1. https://web.whatsapp.com/
2. https://mail.google.com/
3. https://telegram.org/
4. https://www.google.com/
"""

import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from automation.browser import launch_url_in_browser

def test_url(url_str):
    print(f"\n[TESTING URL] {url_str}")
    t0 = time.time()
    ok, msg = launch_url_in_browser(url_str)
    dt = time.time() - t0
    status = "SUCCESS" if ok else "FAILED"
    print(f"  Status: {status}")
    print(f"  Message: {msg}")
    print(f"  Duration: {dt:.2f}s")
    return ok

def main():
    print("=" * 70)
    print("LOW-LEVEL DIRECT BROWSER EXECUTION VERIFICATION")
    print("=" * 70)

    urls = [
        "https://web.whatsapp.com/",
        "https://mail.google.com/",
        "https://telegram.org/",
        "https://www.google.com/"
    ]

    all_passed = True
    for u in urls:
        ok = test_url(u)
        if not ok:
            all_passed = False
        time.sleep(1.0)

    print("\n" + "=" * 70)
    if all_passed:
        print("ALL 4 DIRECT BROWSER LAUNCH TESTS PASSED")
    else:
        print("SOME BROWSER LAUNCH TESTS FAILED")
    print("=" * 70)

if __name__ == "__main__":
    main()
