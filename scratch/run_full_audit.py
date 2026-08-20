import os
import sys
import glob
import subprocess
import json
import re

python_exe = sys.executable
env = os.environ.copy()
env["PYTHONPATH"] = os.path.abspath(".")

test_files = sorted(glob.glob("tests/test_*.py"))
results = {}
total_passed = 0
total_failed = 0
total_skipped = 0
total_errors = 0

print(f"Starting audit of {len(test_files)} test files with PYTHONPATH={env['PYTHONPATH']}", flush=True)

for f in test_files:
    cmd = [python_exe, "-m", "pytest", "-o", "pythonpath=.", f, "-q", "--tb=no"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20, env=env)
        output = (proc.stdout + "\n" + proc.stderr).strip()
        last_line = output.split("\n")[-1] if output else "no output"
        
        passed_m = re.search(r"(\d+) passed", last_line)
        failed_m = re.search(r"(\d+) failed", last_line)
        skipped_m = re.search(r"(\d+) skipped", last_line)
        err_m = re.search(r"(\d+) error", last_line)

        p_count = int(passed_m.group(1)) if passed_m else 0
        f_count = int(failed_m.group(1)) if failed_m else 0
        s_count = int(skipped_m.group(1)) if skipped_m else 0
        e_count = int(err_m.group(1)) if err_m else 0

        status = "PASSED" if (proc.returncode == 0 and p_count > 0) else ("SKIPPED" if (proc.returncode == 0 and s_count > 0 and p_count == 0) else "FAILED")
        if "no tests ran" in last_line:
            status = "NO_TESTS"

        results[f] = {
            "returncode": proc.returncode,
            "status": status,
            "passed": p_count,
            "failed": f_count,
            "skipped": s_count,
            "errors": e_count,
            "summary": last_line
        }
        total_passed += p_count
        total_failed += f_count
        total_skipped += s_count
        total_errors += e_count
        print(f"[{status:8s}] {f:45s} -> {last_line}", flush=True)
    except subprocess.TimeoutExpired:
        results[f] = {"returncode": -1, "status": "TIMEOUT", "passed": 0, "failed": 0, "skipped": 0, "errors": 1, "summary": "Timed out after 20s"}
        total_errors += 1
        print(f"[TIMEOUT ] {f:45s} -> Timed out (20s)", flush=True)
    except Exception as e:
        results[f] = {"returncode": -2, "status": "ERROR", "passed": 0, "failed": 0, "skipped": 0, "errors": 1, "summary": str(e)}
        total_errors += 1
        print(f"[ERROR   ] {f:45s} -> {e}", flush=True)

    with open("scratch/full_test_audit_results.json", "w") as out:
        json.dump({
            "total_files": len(test_files),
            "total_passed": total_passed,
            "total_failed": total_failed,
            "total_skipped": total_skipped,
            "total_errors": total_errors,
            "files": results
        }, out, indent=2)

print("\n================ FINAL TEST AUDIT SUMMARY ================", flush=True)
print(f"Total Files: {len(test_files)} | Passed Tests: {total_passed} | Failed: {total_failed} | Skipped: {total_skipped} | Errors: {total_errors}", flush=True)
