"""
Unit and Integration Tests for Universal Execution Pipeline & False-Positive Fix
==============================================================================
"""

import pytest
from unittest.mock import patch, MagicMock

from automation.applications import (
    resolve_and_open,
    resolve_app_launch_strategy,
    find_windows_app_paths,
    KNOWN_WEB_DESTINATIONS,
)
from automation.browser import open_browser, search_web
from execution.schemas import ExecutionResult
from execution.verifier import dispatch_verify
from execution.executor import SystemExecutor
from agentic.schemas import ExecutionPlan, ActionStep
from tts.response_generator import generate_response


def test_known_web_destinations_exist():
    assert "gmail" in KNOWN_WEB_DESTINATIONS
    assert KNOWN_WEB_DESTINATIONS["gmail"] == "https://mail.google.com"
    assert "spotify" in KNOWN_WEB_DESTINATIONS
    assert KNOWN_WEB_DESTINATIONS["spotify"] == "https://open.spotify.com"
    assert "telegram" in KNOWN_WEB_DESTINATIONS
    assert KNOWN_WEB_DESTINATIONS["telegram"] == "https://web.telegram.org"


def test_resolve_explicit_url():
    with patch("automation.browser.launch_url_in_browser", return_value=(True, "Opened browser to https://example.com.")):
        res = resolve_and_open({"query": "https://example.com"})
        assert res.success is True
        assert res.action_type == "opened_url"


def test_resolve_known_web_service_gmail():
    with patch("automation.browser.launch_url_in_browser", return_value=(True, "Opened browser to https://mail.google.com.")):
        res = resolve_and_open({"query": "gmail"})
        assert res.success is True
        assert res.action_type == "opened_web_app"
        assert res.fallback_used is True
        assert "gmail in your browser" in res.message.lower()


def test_resolve_app_with_web_fallback_spotify():
    # Simulate Spotify not installed locally — must also prevent psutil from finding it as a running process
    with patch("automation.applications.resolve_app_launch_strategy", return_value=(None, "not running", "not found", "not found")), \
         patch("automation.applications.find_website_resource", return_value=None), \
         patch("automation.browser.launch_url_in_browser", return_value=(True, "Opened browser to https://open.spotify.com.")), \
         patch("psutil.process_iter", return_value=iter([])):
        
        res = resolve_and_open({"query": "spotify"})
        assert res.success is True
        assert res.action_type == "opened_web_app"
        assert res.fallback_used is True
        assert "isn't available as a local app, so I opened spotify Web" in res.message or "Spotify" in res.message


def test_resolve_unknown_target_search_fallback():
    # Unknown target not installed and no web destination
    with patch("automation.applications.resolve_app_launch_strategy", return_value=(None, "not running", "not found", "not found")), \
         patch("automation.applications.bring_process_to_foreground", return_value=None), \
         patch("automation.applications.find_website_resource", return_value=None), \
         patch("automation.browser.launch_url_in_browser", return_value=(True, "Searched web for ABCXYZToolThatDoesNotExist")):
        
        res = resolve_and_open({"query": "ABCXYZToolThatDoesNotExist"})
        assert res.success is True
        assert res.action_type == "searched_web"
        assert res.fallback_used is True
        assert "searched for it in your browser" in res.message
        assert "ABCXYZToolThatDoesNotExist" in res.message


def test_browser_launch_failure_propagates_failure():
    # Simulate browser failing to launch during search fallback
    with patch("automation.applications.resolve_app_launch_strategy", return_value=(None, "not running", "not found", "not found")), \
         patch("automation.applications.bring_process_to_foreground", return_value=None), \
         patch("automation.applications.find_website_resource", return_value=None), \
         patch("automation.browser.launch_url_in_browser", return_value=(False, "Executable not found")):
        
        res = resolve_and_open({"query": "ABCXYZToolThatDoesNotExist"})
        assert res.success is False
        assert res.action_type == "failed"
        assert "browser failed to launch" in res.message.lower() or "executable not found" in res.message.lower()


def test_response_generator_never_outputs_completed_resolve_and_open():
    results = [
        {
            "success": True,
            "tool": "resolve_and_open",
            "message": "Spotify isn't available as a local app, so I opened Spotify Web.",
            "action_type": "opened_web_app",
            "fallback_used": True,
        }
    ]
    response = generate_response(results)
    assert response == "Spotify isn't available as a local app, so I opened Spotify Web."
    assert "Completed resolve and open" not in response


def test_response_generator_for_search_fallback():
    results = [
        {
            "success": True,
            "tool": "resolve_and_open",
            "message": "I couldn't find an installed app or known web destination for ABC Editor, so I searched for it in your browser.",
            "action_type": "searched_web",
            "fallback_used": True,
        }
    ]
    response = generate_response(results)
    assert "searched for it in your browser" in response
    assert "Completed resolve and open" not in response


def test_verifier_accepts_browser_launches():
    res = ExecutionResult(success=True, tool="resolve_and_open", message="Opened Gmail in your browser.")
    res.action_type = "opened_web_app"
    res.resource_type = "website"

    with patch("execution.verifier._is_process_running", return_value=True):
        v_res = dispatch_verify("resolve_and_open", {"query": "gmail"}, res)
        assert v_res.passed is True


def test_executor_pipeline_with_mocked_success():
    executor = SystemExecutor()
    plan = ExecutionPlan(
        thought="Open calculator",
        steps=[ActionStep(tool="resolve_and_open", args={"query": "calculator"})],
        response=""
    )

    fake_result = ExecutionResult(success=True, tool="resolve_and_open", message="Opened calculator.")
    fake_result.action_type = "opened_local_app"

    with patch("execution.executor.get_handler", return_value=lambda args: fake_result), \
         patch("execution.executor.dispatch_verify", return_value=MagicMock(passed=True, message="Verified")):
        
        results = executor.execute(plan)
        assert len(results) == 1
        assert results[0]["success"] is True
        assert results[0]["state"] == "success"


def test_executor_pipeline_preserves_failure():
    executor = SystemExecutor()
    plan = ExecutionPlan(
        thought="Open broken app",
        steps=[ActionStep(tool="resolve_and_open", args={"query": "broken_app"})],
        response=""
    )

    fake_result = ExecutionResult(success=False, tool="resolve_and_open", message="Failed to launch app: FileNotFoundError")
    fake_result.action_type = "failed"

    with patch("execution.executor.get_handler", return_value=lambda args: fake_result), \
         patch("execution.recovery.recover_step", return_value=MagicMock(succeeded=False, message="Recovery failed")):
        
        results = executor.execute(plan)
        assert len(results) == 1
        assert results[0]["success"] is False
        assert results[0]["state"] == "failure"
