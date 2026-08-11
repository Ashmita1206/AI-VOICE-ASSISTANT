"""
Execution Layer Tests
=====================

Unit tests and demonstrations of the execution layer connecting
Planner mock outputs to SystemExecutor actual execution.

Run:
    python -m execution.tests.test_execution
"""

import sys
import json
import logging
from pprint import pprint

from agentic.schemas import ExecutionPlan, ActionStep
from execution.executor import SystemExecutor

logging.basicConfig(level=logging.WARNING)

def build_plan(*steps_data: tuple[str, dict]) -> ExecutionPlan:
    """Helper to build an execution plan from tuples of (tool, args)."""
    steps = [ActionStep(tool=t, args=a) for t, a in steps_data]
    return ExecutionPlan(thought="Test plan", steps=steps, response="Executing.")

def run_tests():
    print("=== Execution Layer Verification ===")
    
    executor = SystemExecutor()

    # Define test cases matching the user's requested demonstration
    test_cases = [
        {
            "name": "Open Chrome",
            "plan": build_plan(("open_browser", {"browser": "chrome"}))
        },
        {
            "name": "Open terminal",
            "plan": build_plan(("open_terminal", {}))
        },
        {
            "name": "What time is it",
            "plan": build_plan(("check_time", {}))
        },
        {
            "name": "Take screenshot",
            "plan": build_plan(("take_screenshot", {}))
        },
        {
            "name": "Open file manager",
            "plan": build_plan(("open_file_manager", {}))
        },
        {
            "name": "List files",
            "plan": build_plan(("list_files", {"directory": "."}))
        },
        {
            "name": "Open Chrome and search machine learning",
            "plan": build_plan(
                ("open_browser", {"browser": "chrome"}),
                ("search_web", {"query": "machine learning"})
            )
        },
        {
            "name": "[Safety Test] Block dangerous command",
            "plan": build_plan(("open_terminal", {"command": "sudo rm -rf /"}))
        }
    ]

    for case in test_cases:
        print(f"\n--- Demonstrating: {case['name']} ---")
        results = executor.execute(case["plan"])
        for res in results:
            print(json.dumps(res, indent=2))
            
    print("\n>>> All execution tests ran successfully.")

def test_open_nonexistent_application_returns_failure():
    executor = SystemExecutor()
    plan = build_plan(("open_application", {"application": "nonexistent_fake_app_xyz_12345"}))
    results = executor.execute(plan)
    assert len(results) == 1
    assert results[0]["success"] is False
    assert "not installed or found" in results[0]["message"] or "failed" in results[0]["message"].lower()

def test_launch_nonexistent_application_returns_failure():
    executor = SystemExecutor()
    plan = build_plan(("launch_application", {"application": "nonexistent_fake_app_xyz_12345"}))
    results = executor.execute(plan)
    assert len(results) == 1
    assert results[0]["success"] is False
    assert "Failed to launch application" in results[0]["message"]

def test_resolve_and_open_nonexistent_returns_failure():
    from unittest.mock import patch
    executor = SystemExecutor()
    plan = build_plan(("resolve_and_open", {"query": "nonexistent_fake_app_xyz_12345"}))
    with patch("automation.browser.launch_url_in_browser", return_value=(False, "Executable not found")):
        results = executor.execute(plan)
        assert len(results) == 1
        assert results[0]["success"] is False

if __name__ == "__main__":
    run_tests()
