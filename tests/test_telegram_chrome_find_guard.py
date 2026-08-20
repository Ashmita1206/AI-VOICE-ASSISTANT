"""
Regression Test Suite for Telegram Foreground Guard & Chrome Find Leak Prevention
================================================================================
Covers:
1. Chrome foreground -> Keystrokes blocked if Telegram cannot be verified in foreground
2. Chrome foreground -> Telegram automatically refocused before search/typing
3. Single external send dispatch -> No duplicate sends -> Verified state transition
"""

import pytest
from unittest.mock import patch, MagicMock
from automation.telegram.telegram_automation import (
    _telegram_state,
    reset_telegram_state,
    ensure_telegram_foreground,
    verify_telegram_foreground_action,
    handle_search_telegram_contact,
    handle_type_telegram_message,
    handle_send_telegram_message,
    handle_verify_telegram_message_sent,
    set_telegram_contact_confirmed,
    set_telegram_send_confirmed,
)
from automation.telegram.models import TelegramContact


@pytest.fixture(autouse=True)
def setup_env():
    reset_telegram_state()
    _telegram_state["ready"] = True
    _telegram_state["mode"] = "desktop"
    _telegram_state["client"] = "telegram_desktop"


class TestTelegramChromeFindGuard:

    def test_chrome_foreground_blocks_keystrokes_when_refocus_fails(self):
        """If Chrome is active and Telegram cannot be refocused, abort to prevent Chrome Find leak."""
        with patch("win32gui.GetForegroundWindow", return_value=9999), \
             patch("win32process.GetWindowThreadProcessId", return_value=(0, 1111)), \
             patch("psutil.Process") as mock_proc, \
             patch("automation.telegram.telegram_automation.ensure_telegram_foreground", return_value=None), \
             patch("pyautogui.hotkey") as mock_hotkey, \
             patch("pyautogui.write") as mock_write:

            mock_proc.return_value.name.return_value = "chrome.exe"

            res = handle_search_telegram_contact({"contact": "Harshita"})
            assert res.success is False
            assert "foreground" in res.message.lower()

            # Verify no keyboard shortcut or text was leaked into Chrome
            mock_hotkey.assert_not_called()
            mock_write.assert_not_called()

    def test_chrome_foreground_refocuses_telegram_before_search(self):
        """When Chrome is foreground, ensure Telegram is refocused before typing search query."""
        with patch("win32gui.GetForegroundWindow", return_value=9999), \
             patch("win32process.GetWindowThreadProcessId", return_value=(0, 1111)), \
             patch("psutil.Process") as mock_proc, \
             patch("automation.telegram.telegram_automation.ensure_telegram_foreground", return_value=12345), \
             patch("automation.telegram.telegram_automation._find_telegram_search_box", return_value=None), \
             patch("automation.telegram.telegram_automation._collect_desktop_search_candidates") as mock_candidates, \
             patch("pyautogui.hotkey") as mock_hotkey, \
             patch("pyautogui.write") as mock_write:

            mock_proc.return_value.name.return_value = "chrome.exe"
            mock_contact = TelegramContact(id=1, name="Harshita", first_name="Harshita", contact_type="user")
            mock_candidates.return_value = [(mock_contact, "Harshita")]

            res = handle_search_telegram_contact({"contact": "Harshita"})
            assert res.success is True
            assert res.data["query"] == "Harshita"
            assert mock_write.called

    def test_composer_existing_draft_reused_without_retyping(self):
        """If Harshita's composer already contains 'hello', reuse it without appending."""
        mock_composer = MagicMock()
        with patch("automation.telegram.telegram_automation.verify_telegram_foreground_action", return_value=(True, 12345)), \
             patch("automation.telegram.telegram_automation._find_telegram_composer", return_value=mock_composer), \
             patch("automation.telegram.telegram_automation._control_value", return_value="hello"), \
             patch("pyautogui.write") as mock_write:

            _telegram_state["chat_open"] = True
            _telegram_state["composer_focused"] = True
            _telegram_state["contact"] = TelegramContact(id=1, name="Harshita", first_name="Harshita", contact_type="user")

            res = handle_type_telegram_message({"message": "hello"})
            assert res.success is True
            assert res.requires_confirmation is True
            # Since draft already matched 'hello', no extra typing was performed
            mock_write.assert_not_called()

    def test_send_message_dispatches_once_and_prevents_duplicate(self):
        """send_telegram_message dispatches Enter exactly once and safely ignores subsequent retries."""
        _telegram_state["chat_open"] = True
        _telegram_state["composer_focused"] = True
        _telegram_state["contact"] = TelegramContact(id=1, name="Harshita", first_name="Harshita", contact_type="user")
        _telegram_state["message"] = "hello"
        set_telegram_send_confirmed(True)

        with patch("automation.telegram.telegram_automation.verify_telegram_foreground_action", return_value=(True, 12345)), \
             patch("automation.telegram.telegram_automation._chat_header_matches", return_value=True), \
             patch("automation.telegram.telegram_automation._find_telegram_composer", return_value=None), \
             patch("pyautogui.press") as mock_press:

            # 1. First send
            res1 = handle_send_telegram_message({"contact": "Harshita", "message": "hello"})
            assert res1.success is True
            assert _telegram_state["send_attempted"] is True
            assert _telegram_state["send_state"] == "DISPATCHED"
            assert mock_press.call_count == 1
            mock_press.assert_called_once_with("enter")

            # 2. Second send attempt (must be blocked idempotently)
            res2 = handle_send_telegram_message({"contact": "Harshita", "message": "hello"})
            assert res2.success is True
            assert res2.data.get("already_dispatched") is True
            # Keystroke count remains 1
            assert mock_press.call_count == 1

            # 3. Verify sent
            res_verify = handle_verify_telegram_message_sent({"message": "hello"})
            assert res_verify.success is True
            assert _telegram_state["sent_verified"] is True
            assert _telegram_state["send_state"] == "VERIFIED"
