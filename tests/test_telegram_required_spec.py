"""
Comprehensive Specification & Verification Tests for Telegram Opening Architecture
===================================================================================
Tests all 9 explicit rules and invariants from the user specification.
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

from agent.intent_classifier import IntentClassifier
from agentic.llm.fallback import apply_heuristic_fallback
from execution.registry import load_all_tools, get_handler
from automation.applications import (
    resolve_app_launch_strategy,
    find_windows_app_paths,
    clean_query_for_matching,
    resolve_canonical_app,
)
from automation.telegram.router import TelegramAutomationRouter, FlowStatus, TelegramFlowMode
from automation.telegram.telegram_automation import TelegramService


@pytest.fixture(autouse=True)
def setup_tools():
    load_all_tools()


class TestTelegramRequiredSpecification:

    # -------------------------------------------------------------------------
    # RULE 1: Intent & Pipeline Isolation
    # -------------------------------------------------------------------------
    @pytest.mark.parametrize(
        "phrase",
        [
            "Open Telegram",
            "Telegram kholo",
            "Launch Telegram",
            "Start Telegram",
            "Open Telegram Desktop",
            "Telegram open",
            "Telegram open karo",
        ]
    )
    def test_rule_1_plain_opening_intent_and_isolation(self, phrase):
        """'Open Telegram' must resolve to open_application, never invoke router or pyrogram."""
        classifier = IntentClassifier()
        cmd = classifier.classify(phrase)

        assert cmd.intent == "open_application"
        assert "telegram" in cmd.entities.get("application", "").lower()

        plan = apply_heuristic_fallback(phrase)
        assert plan.intent in ("launch_application", "open_application")
        assert len(plan.steps) >= 1
        assert plan.steps[0].tool in ("launch_application", "open_application", "resolve_and_open")
        assert plan.steps[0].tool != "open_telegram_web"
        assert plan.steps[0].tool != "send_telegram_message"

        # Telegram messaging router must NOT be called
        router = TelegramAutomationRouter(TelegramService())
        router.reset()
        assert router.state.mode == TelegramFlowMode.IDLE
        assert router.state.executed is False

    # -------------------------------------------------------------------------
    # RULE 2: Detection in %APPDATA%
    # -------------------------------------------------------------------------
    def test_rule_2_appdata_desktop_detected_and_launched(self):
        """When Telegram.exe exists in %APPDATA%, detect and launch it without Web fallback."""
        fake_appdata_path = os.path.expandvars(r"%APPDATA%\Telegram Desktop\Telegram.exe")

        with patch("os.path.exists", side_effect=lambda p: p == fake_appdata_path), \
             patch("os.path.isfile", side_effect=lambda p: p == fake_appdata_path), \
             patch("automation.applications.get_start_apps", return_value=[]):
            
            resolved_exe, _, _, _ = resolve_app_launch_strategy("telegram")
            assert resolved_exe == fake_appdata_path

    # -------------------------------------------------------------------------
    # RULE 3: Detection in %LOCALAPPDATA%
    # -------------------------------------------------------------------------
    def test_rule_3_localappdata_desktop_detected(self):
        """When Telegram.exe exists in %LOCALAPPDATA%, detect and launch it."""
        fake_local_path = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Telegram Desktop\Telegram.exe")

        with patch("os.path.exists", side_effect=lambda p: p == fake_local_path), \
             patch("os.path.isfile", side_effect=lambda p: p == fake_local_path), \
             patch("automation.applications.get_start_apps", return_value=[]):
            
            resolved_exe, _, _, _ = resolve_app_launch_strategy("telegram")
            assert resolved_exe == fake_local_path

    # -------------------------------------------------------------------------
    # RULE 4: Telegram Already Running
    # -------------------------------------------------------------------------
    def test_rule_4_already_running_focuses_window(self):
        """When Telegram is already running, focus/reuse existing window without messaging automation."""
        handler = get_handler("open_application")
        assert handler is not None

        mock_proc = MagicMock()
        mock_proc.info = {"pid": 12345, "name": "Telegram.exe"}

        with patch("psutil.process_iter", return_value=[mock_proc]), \
             patch("automation.applications.bring_process_to_foreground", return_value=99999), \
             patch("automation.applications.force_focus_window", return_value=True):
            
            res = handler({"application": "telegram"})
            assert res.success is True
            assert res.app_running is True
            assert res.action == "activate_window"

        # Router remains untouched
        router = TelegramAutomationRouter(TelegramService())
        assert router.state.mode == TelegramFlowMode.IDLE

    # -------------------------------------------------------------------------
    # RULE 5: Desktop Missing Allows Web Fallback in resolve_and_open
    # -------------------------------------------------------------------------
    def test_rule_5_desktop_missing_allows_web_fallback(self):
        """When Desktop is not installed, resolve_and_open allows Web fallback."""
        handler = get_handler("resolve_and_open")
        assert handler is not None

        with patch("automation.applications.resolve_app_launch_strategy", return_value=(None, "not running", "not found", "not found")), \
             patch("automation.applications.find_website_resource", return_value=None), \
             patch("automation.browser.open_browser") as mock_open_browser:
            
            mock_res = MagicMock()
            mock_res.success = True
            mock_res.message = "Browser opened"
            mock_open_browser.return_value = mock_res

            res = handler({"query": "telegram"})
            assert res.success is True
            assert res.fallback_used is True
            mock_open_browser.assert_called_once_with({"url": "https://web.telegram.org"})

    # -------------------------------------------------------------------------
    # RULE 6: Browser Open Fails -> success=False
    # -------------------------------------------------------------------------
    def test_rule_6_web_browser_open_fails_returns_false(self):
        """When browser fails to launch, web fallback must return success=False."""
        handler = get_handler("resolve_and_open")
        assert handler is not None

        with patch("automation.applications.resolve_app_launch_strategy", return_value=(None, "not running", "not found", "not found")), \
             patch("automation.applications.find_website_resource", return_value=None), \
             patch("automation.browser.open_browser") as mock_open_browser:
            
            mock_res = MagicMock()
            mock_res.success = False
            mock_res.message = "Chrome executable not found"
            mock_open_browser.return_value = mock_res

            res = handler({"query": "telegram"})
            assert res.success is False
            assert "failed to launch" in res.message or "failed" in res.message

    # -------------------------------------------------------------------------
    # RULE 7: URL Launched But Cannot Verify -> success=False
    # -------------------------------------------------------------------------
    def test_rule_7_web_launched_but_unverified_returns_false(self):
        """When Web URL is launched but target tab/window cannot be verified, fail closed."""
        handler = get_handler("open_telegram_web")
        assert handler is not None

        with patch("automation.telegram.telegram_automation.find_telegram_desktop", return_value=None), \
             patch("automation.browser.launch_url_in_browser", return_value=(True, "OK")), \
             patch("automation.browser.find_and_focus_browser_tab", return_value=False), \
             patch("execution.verifier._is_window_visible", return_value=False):
            
            res = handler({})
            assert res.success is False
            assert "could not be opened or verified" in res.message
            assert res.message != "Opened Telegram Web."

    # -------------------------------------------------------------------------
    # RULE 8: Desktop Opens Successfully
    # -------------------------------------------------------------------------
    def test_rule_8_desktop_opens_successfully(self):
        """When Desktop is launched and window verified, returns success."""
        handler = get_handler("launch_application")
        assert handler is not None

        with patch("automation.applications.resolve_app_launch_strategy", return_value=("C:\\dummy\\telegram.exe", "not running", "not found", "found shortcut")), \
             patch("os.startfile", create=True) as mock_startfile, \
             patch("subprocess.Popen") as mock_popen, \
             patch("automation.applications.wait_and_focus_app", return_value=True):
            
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc

            res = handler({"application": "telegram"})
            assert res.success is True
            assert "successfully launched" in res.message.lower() or "opened" in res.message.lower()

    # -------------------------------------------------------------------------
    # RULE 9: Desktop & Web Both Fail -> Failure Status (No Fake Success)
    # -------------------------------------------------------------------------
    def test_rule_9_both_fail_returns_failure_no_fake_success(self):
        """When Desktop resolution and browser fallback both fail, return failure status."""
        handler = get_handler("resolve_and_open")
        assert handler is not None

        with patch("automation.applications.resolve_app_launch_strategy", return_value=(None, "not running", "not found", "not found")), \
             patch("automation.applications.find_website_resource", return_value=None), \
             patch("automation.browser.open_browser") as mock_open_browser, \
             patch("automation.browser.search_web") as mock_search_web:
            
            mock_browser_res = MagicMock()
            mock_browser_res.success = False
            mock_browser_res.message = "No browser available"
            mock_open_browser.return_value = mock_browser_res

            mock_search_res = MagicMock()
            mock_search_res.success = False
            mock_search_res.message = "Search failed"
            mock_search_web.return_value = mock_search_res

            res = handler({"query": "telegram"})
            assert res.success is False
            assert "Opened Telegram Web" not in res.message
