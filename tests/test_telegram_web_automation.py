"""
Unit Tests for Telegram Web Browser Automation Pipeline
======================================================
Tests the 13 Telegram Web browser automation steps:
- open_telegram_web
- verify_telegram_web_logged_in
- search_telegram_contact
- verify_telegram_contact
- open_telegram_chat
- verify_telegram_chat_header
- focus_telegram_composer
- type_telegram_message
- send_telegram_message
- verify_telegram_message_sent / verify_telegram_message_bubble
- close_telegram_tab / close_telegram
"""

import pytest
from unittest.mock import patch, MagicMock
from execution.registry import load_all_tools, get_handler
from automation.telegram.telegram_automation import _telegram_state


@pytest.fixture(autouse=True)
def setup_tools_and_state():
    load_all_tools()
    _telegram_state.clear()
    _telegram_state.update({
        "client": "web",
        "logged_in": True,
        "contact": None,
        "candidates": [],
        "chat_open": False,
        "header_verified": False,
        "composer_focused": False,
        "draft_ready": False,
        "message": "",
        "send_attempted": False,
        "sent_verified": False,
        "ready": True,
    })


class TestTelegramWebBrowserAutomationSteps:

    def test_open_telegram_web(self):
        handler = get_handler("open_telegram_web")
        assert handler is not None
        with patch("automation.browser.find_and_focus_browser_tab", return_value=True):
            res = handler({})
        assert res.success is True
        assert res.data["client"] in ("web", "telegram_web")




    def test_search_telegram_contact(self):
        handler = get_handler("search_telegram_contact")
        assert handler is not None
        _telegram_state["ready"] = True
        with patch("automation.browser.find_and_focus_browser_tab", return_value=True), \
             patch("execution.verifier._is_window_visible", return_value=True), \
             patch("pyautogui.write") as mock_write:
            res = handler({"contact": "Harshita"})
        assert res.success is True
        assert len(res.data["candidates"]) >= 1

    def test_search_telegram_contact_blocked_when_not_focused(self):
        handler = get_handler("search_telegram_contact")
        assert handler is not None
        _telegram_state["ready"] = False

        with patch("automation.browser.find_and_focus_browser_tab", return_value=False), \
             patch("execution.verifier._is_window_visible", return_value=False), \
             patch("pyautogui.write") as mock_write, \
             patch("pyautogui.hotkey") as mock_hotkey:
            res = handler({"contact": "Harshita"})

        assert res.success is False
        assert "not open/ready" in res.message or "could not be focused" in res.message
        mock_write.assert_not_called()
        mock_hotkey.assert_not_called()

    def test_verify_telegram_contact_single_match(self):
        search_h = get_handler("search_telegram_contact")
        verify_h = get_handler("verify_telegram_contact")
        _telegram_state["ready"] = True
        with patch("automation.browser.find_and_focus_browser_tab", return_value=True), \
             patch("execution.verifier._is_window_visible", return_value=True):
            search_h({"contact": "Harshita"})
        res = verify_h({"contact": "Harshita"})
        assert res.success is True
        assert res.requires_confirmation is True
        assert res.data["contact"] == "Harshita"

    def test_open_telegram_chat(self):
        verify_h = get_handler("verify_telegram_contact")
        chat_h = get_handler("open_telegram_chat")
        search_h = get_handler("search_telegram_contact")
        _telegram_state["ready"] = True
        with patch("automation.browser.find_and_focus_browser_tab", return_value=True), \
             patch("execution.verifier._is_window_visible", return_value=True):
            search_h({"contact": "Harshita"})
        verify_h({"contact": "Harshita"})
        res = chat_h({"contact": "Harshita"})
        assert res.success is True
        assert res.data["chat_open"] is True

    def test_verify_telegram_chat_header(self):
        _telegram_state["chat_open"] = True
        header_h = get_handler("verify_telegram_chat_header")
        assert header_h is not None
        res = header_h({"contact": "Harshita"})
        assert res.success is True
        assert res.data["header_verified"] is True

    def test_focus_telegram_composer(self):
        _telegram_state["chat_open"] = True
        focus_h = get_handler("focus_telegram_composer")
        assert focus_h is not None
        res = focus_h({})
        assert res.success is True
        assert res.data["composer_focused"] is True

    def test_type_telegram_message(self):
        type_h = get_handler("type_telegram_message")
        res = type_h({"message": "hello"})
        assert res.success is True
        assert res.requires_confirmation is True
        assert res.data["message"] == "hello"


    def test_send_telegram_message(self):
        send_h = get_handler("send_telegram_message")
        _telegram_state["draft_ready"] = True
        _telegram_state["contact_confirmed"] = True
        _telegram_state["send_confirmed"] = True
        res = send_h({"message": "hello"})
        assert res.success is True
        assert res.data["send_attempted"] is True

    def test_verify_telegram_message_bubble(self):
        send_h = get_handler("send_telegram_message")
        verify_bubble_h = get_handler("verify_telegram_message_bubble")
        assert verify_bubble_h is not None

        # Before send attempt
        _telegram_state["send_attempted"] = False
        res_before = verify_bubble_h({"message": "hello"})
        assert res_before.success is False

        # After send attempt
        _telegram_state["draft_ready"] = True
        _telegram_state["contact_confirmed"] = True
        _telegram_state["send_confirmed"] = True
        send_h({"message": "hello"})
        res_after = verify_bubble_h({"message": "hello"})
        assert res_after.success is True
        assert res_after.data["verified"] is True

    def test_close_telegram_tab(self):
        close_h = get_handler("close_telegram_tab")
        assert close_h is not None

        _telegram_state["sent_verified"] = False
        res_fail = close_h({})
        assert res_fail.success is False

        _telegram_state["sent_verified"] = True
        res_pass = close_h({})
        assert res_pass.success is True
        assert res_pass.data["closed"] is True
