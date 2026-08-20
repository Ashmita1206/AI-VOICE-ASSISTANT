"""
Unit tests for decomposed Telegram tools
=========================================
Tests each individual Telegram execution tool:
- open_telegram
- search_telegram_contact
- verify_telegram_contact
- open_telegram_chat
- type_telegram_message
- send_telegram_message
- verify_telegram_message_sent
- close_telegram
- duplicate-send prevention
- state machine transitions
"""

import pytest
from unittest.mock import patch
from execution.registry import load_all_tools, get_handler
from automation.telegram.telegram_automation import _telegram_state


@pytest.fixture(autouse=True)
def setup_tools_and_state():
    load_all_tools()
    _telegram_state.clear()
    _telegram_state.update({
        "client": "telegram_web",
        "ready": True,
        "contact": None,
        "candidates": [],
        "chat_open": False,
        "draft_ready": False,
        "message": "",
        "send_attempted": False,
        "sent_verified": False,
    })


class TestDecomposedTelegramTools:

    def test_open_telegram(self):
        handler = get_handler("open_telegram_web")
        assert handler is not None
        with patch("automation.browser.find_and_focus_browser_tab", return_value=True), \
             patch("execution.verifier._is_window_visible", return_value=True):
            res = handler({})
        assert res.success is True
        assert res.data["ready"] is True
        assert res.data["client"] in ("web", "telegram_web")

    def test_search_telegram_contact_success(self):
        handler = get_handler("search_telegram_contact")
        assert handler is not None
        _telegram_state["ready"] = True
        with patch("automation.browser.find_and_focus_browser_tab", return_value=True), \
             patch("execution.verifier._is_window_visible", return_value=True):
            res = handler({"contact": "Harshita"})
        assert res.success is True
        assert len(res.data["candidates"]) >= 1

    def test_search_telegram_contact_missing_query(self):
        handler = get_handler("search_telegram_contact")
        res = handler({"contact": ""})
        assert res.success is False

    def test_verify_telegram_contact_single_match(self):
        search_handler = get_handler("search_telegram_contact")
        verify_handler = get_handler("verify_telegram_contact")
        _telegram_state["ready"] = True
        with patch("automation.browser.find_and_focus_browser_tab", return_value=True), \
             patch("execution.verifier._is_window_visible", return_value=True):
            search_handler({"contact": "Harshita"})
        res = verify_handler({"contact": "Harshita"})
        assert res.success is True
        assert res.data["contact"] == "Harshita"

    def test_verify_telegram_contact_no_match(self):
        verify_handler = get_handler("verify_telegram_contact")
        res = verify_handler({"contact": "NonExistentContact999"})
        assert res.success is False

    def test_open_telegram_chat(self):
        verify_handler = get_handler("verify_telegram_contact")
        chat_handler = get_handler("open_telegram_chat")
        verify_handler({"contact": "Harshita"})
        with patch("automation.browser.find_and_focus_browser_tab", return_value=True), \
             patch("execution.verifier._is_window_visible", return_value=True):
            res = chat_handler({"contact": "Harshita"})
        assert res.success is True
        assert res.data["chat_open"] is True

    def test_type_telegram_message(self):
        type_handler = get_handler("type_telegram_message")
        with patch("automation.browser.find_and_focus_browser_tab", return_value=True), \
             patch("execution.verifier._is_window_visible", return_value=True):
            res = type_handler({"message": "hello"})
        assert res.success is True
        assert res.data["draft_ready"] is True
        assert res.data["message"] == "hello"

    def test_type_telegram_message_empty(self):
        type_handler = get_handler("type_telegram_message")
        res = type_handler({"message": ""})
        assert res.success is False

    def test_send_telegram_message(self):
        send_handler = get_handler("send_telegram_message")
        _telegram_state["draft_ready"] = True
        _telegram_state["contact_confirmed"] = True
        _telegram_state["send_confirmed"] = True
        with patch("automation.browser.find_and_focus_browser_tab", return_value=True), \
             patch("execution.verifier._is_window_visible", return_value=True):
            res = send_handler({"message": "hello"})
        assert res.success is True
        assert res.data["send_attempted"] is True

    def test_verify_telegram_message_sent(self):
        send_handler = get_handler("send_telegram_message")
        verify_sent_handler = get_handler("verify_telegram_message_sent")
        
        # Before send attempt
        _telegram_state["send_attempted"] = False
        res_before = verify_sent_handler({"message": "hello"})
        assert res_before.success is False

        # After send attempt
        _telegram_state["draft_ready"] = True
        _telegram_state["contact_confirmed"] = True
        _telegram_state["send_confirmed"] = True
        with patch("automation.browser.find_and_focus_browser_tab", return_value=True), \
             patch("execution.verifier._is_window_visible", return_value=True):
            send_handler({"message": "hello"})
        res_after = verify_sent_handler({"message": "hello"})
        assert res_after.success is True
        assert res_after.data["verified"] is True


    def test_duplicate_send_prevention(self):
        send_handler = get_handler("send_telegram_message")
        _telegram_state["sent_verified"] = True
        res = send_handler({})
        assert res.success is True
        assert res.data.get("already_sent") is True

    def test_close_telegram_requires_verification(self):
        close_handler = get_handler("close_telegram")
        _telegram_state["sent_verified"] = False
        res_fail = close_handler({})
        assert res_fail.success is False

        _telegram_state["sent_verified"] = True
        res_pass = close_handler({})
        assert res_pass.success is True
