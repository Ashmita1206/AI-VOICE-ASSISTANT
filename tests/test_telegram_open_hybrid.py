"""
Unit Tests for Hybrid Telegram Open Architecture (Desktop vs Web Fallback)
==========================================================================
"""

import pytest
from unittest.mock import patch, MagicMock
from execution.registry import load_all_tools, get_handler
from execution.verifier import dispatch_verify
from automation.telegram.telegram_automation import _telegram_state


@pytest.fixture(autouse=True)
def setup_tools():
    load_all_tools()
    _telegram_state.clear()


class TestTelegramHybridOpen:

    def test_open_telegram_desktop_installed(self):
        """When Telegram Desktop is installed, launch Desktop client."""
        handler = get_handler("open_telegram_web")
        assert handler is not None

        fake_exe = r"C:\Program Files\Telegram Desktop\Telegram.exe"

        with patch("automation.telegram.telegram_automation.find_telegram_desktop", return_value=fake_exe), \
             patch("subprocess.Popen") as mock_popen, \
             patch("automation.browser.launch_url_in_browser") as mock_browser, \
             patch("execution.verifier.verify_application_launched", return_value=MagicMock(passed=True)):

            res = handler({})
            assert res.success is True
            assert res.data["client"] == "telegram_desktop"
            assert res.data["executable"] == fake_exe
            mock_popen.assert_called_once_with([fake_exe])
            mock_browser.assert_not_called()

            # Test Verifier routing for desktop
            v_res = dispatch_verify("open_telegram_web", {}, res)
            assert v_res.passed is True
            assert "Desktop" in v_res.message

    def test_open_telegram_web_fallback(self):
        """When Telegram Desktop is NOT installed, fall back to Telegram Web in browser."""
        handler = get_handler("open_telegram_web")
        assert handler is not None

        with patch("automation.telegram.telegram_automation.find_telegram_desktop", return_value=None), \
             patch("subprocess.Popen") as mock_popen, \
             patch("automation.browser.launch_url_in_browser", return_value=(True, "OK")) as mock_browser, \
             patch("execution.verifier._is_window_visible", return_value=True):

            res = handler({})
            assert res.success is True
            assert res.data["client"] == "telegram_web"
            mock_popen.assert_not_called()
            mock_browser.assert_called_once()

            # Test Verifier routing for web
            v_res = dispatch_verify("open_telegram_web", {}, res)
            assert v_res.passed is True
            assert "Web" in v_res.message
