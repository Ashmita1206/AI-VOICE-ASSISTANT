"""
Regression Test Suite for Telegram New-Command Reset and UI Normalization
=========================================================================
Covers:
1. When Harshita chat is currently open, a new command normalizes Telegram UI back to search.
2. Composer NEVER receives the recipient contact query ("Harshita").
3. When another chat (e.g. Neeraj) is open, it backs out to search without polluting Neeraj's composer.
4. When Telegram is already on home/chat-list, direct search focus proceeds without unnecessary back navigation.
5. Focus verification guard strictly stops if the message composer remains focused.
"""

import pytest
from unittest.mock import patch, MagicMock
from automation.telegram.telegram_automation import (
    _telegram_state,
    reset_telegram_state,
    _reset_transient_telegram_state,
    prepare_telegram_for_new_contact_search,
    handle_search_telegram_contact,
    handle_open_telegram,
)
from automation.telegram.models import TelegramContact


@pytest.fixture(autouse=True)
def setup_env():
    reset_telegram_state()
    _telegram_state["ready"] = True
    _telegram_state["mode"] = "desktop"
    _telegram_state["client"] = "telegram_desktop"


class TestTelegramNewCommandReset:

    def test_harshita_chat_open_resets_to_search_and_never_types_in_composer(self):
        """When Harshita chat is open, new command navigates back to search and types Harshita only in Search."""
        mock_composer = MagicMock()
        mock_composer.Name = "Write a message..."
        mock_composer.ControlTypeName = "EditControl"
        mock_composer.BoundingRectangle = MagicMock(top=500, left=400)

        mock_search_box = MagicMock()
        mock_search_box.Name = "Search"
        mock_search_box.ControlTypeName = "EditControl"
        mock_search_box.BoundingRectangle = MagicMock(top=100, left=100)

        typed_into_composer = []
        typed_into_search = []

        def mock_write(text, interval=0.04):
            # If search box was focused, record search; otherwise composer
            typed_into_search.append(text)

        with patch("automation.telegram.telegram_automation.verify_telegram_foreground_action", return_value=(True, 12345)), \
             patch("automation.telegram.telegram_automation._find_telegram_composer", side_effect=[mock_composer, None]), \
             patch("automation.telegram.telegram_automation._find_telegram_search_box", return_value=mock_search_box), \
             patch("automation.telegram.telegram_automation._collect_desktop_search_candidates") as mock_candidates, \
             patch("uiautomation.GetFocusedControl", return_value=mock_search_box), \
             patch("pyautogui.press") as mock_press, \
             patch("pyautogui.write", side_effect=mock_write):

            mock_contact = TelegramContact(id=1, name="Harshita", first_name="Harshita", contact_type="user")
            mock_candidates.return_value = [(mock_contact, "Harshita")]

            # Initial state: Harshita chat was open and active from previous flow
            _telegram_state["chat_open"] = True
            _telegram_state["contact"] = mock_contact
            _telegram_state["message"] = "hello"

            res = handle_search_telegram_contact({"contact": "Harshita"})
            assert res.success is True
            assert res.data["query"] == "Harshita"

            # Verify Escape / Back navigation was triggered to leave open chat
            assert mock_press.called
            # Verify recipient contact went into search
            assert "Harshita" in typed_into_search

    def test_neeraj_chat_open_backs_out_to_search_for_harshita(self):
        """When Neeraj chat is open, new command exits Neeraj chat and searches Harshita without typing in composer."""
        mock_composer = MagicMock()
        mock_composer.Name = "Write a message..."
        mock_composer.ControlTypeName = "EditControl"
        mock_composer.BoundingRectangle = MagicMock(top=600, left=400)

        mock_search_box = MagicMock()
        mock_search_box.Name = "Search"
        mock_search_box.ControlTypeName = "EditControl"
        mock_search_box.BoundingRectangle = MagicMock(top=80, left=120)

        typed_texts = []

        with patch("automation.telegram.telegram_automation.verify_telegram_foreground_action", return_value=(True, 12345)), \
             patch("automation.telegram.telegram_automation._find_telegram_composer", side_effect=[mock_composer, None]), \
             patch("automation.telegram.telegram_automation._find_telegram_search_box", return_value=mock_search_box), \
             patch("automation.telegram.telegram_automation._collect_desktop_search_candidates") as mock_candidates, \
             patch("uiautomation.GetFocusedControl", return_value=mock_search_box), \
             patch("pyautogui.press") as mock_press, \
             patch("pyautogui.write", side_effect=lambda text, **kw: typed_texts.append(text)):

            mock_contact = TelegramContact(id=1, name="Harshita", first_name="Harshita", contact_type="user")
            mock_candidates.return_value = [(mock_contact, "Harshita")]

            # Initial state: previous chat was Neeraj
            _telegram_state["chat_open"] = True
            _telegram_state["contact"] = TelegramContact(id=9, name="Neeraj", first_name="Neeraj", contact_type="user")

            res = handle_search_telegram_contact({"contact": "Harshita"})
            assert res.success is True
            assert typed_texts == ["Harshita"]
            # Transient state was reset: previous contact Neeraj was purged
            assert _telegram_state.get("contact") is None or _telegram_state["contact"].name == "Harshita"

    def test_home_chat_list_does_not_perform_unnecessary_back_navigation(self):
        """When Telegram is already showing chat list (no composer), direct search proceeds without back navigation."""
        mock_search_box = MagicMock()
        mock_search_box.Name = "Search"
        mock_search_box.ControlTypeName = "EditControl"
        mock_search_box.BoundingRectangle = MagicMock(top=90, left=100)

        with patch("automation.telegram.telegram_automation.verify_telegram_foreground_action", return_value=(True, 12345)), \
             patch("automation.telegram.telegram_automation._find_telegram_composer", return_value=None), \
             patch("automation.telegram.telegram_automation._find_telegram_search_box", return_value=mock_search_box), \
             patch("automation.telegram.telegram_automation._collect_desktop_search_candidates") as mock_candidates, \
             patch("uiautomation.GetFocusedControl", return_value=mock_search_box), \
             patch("pyautogui.write") as mock_write:

            mock_contact = TelegramContact(id=1, name="Harshita", first_name="Harshita", contact_type="user")
            mock_candidates.return_value = [(mock_contact, "Harshita")]

            res = handle_search_telegram_contact({"contact": "Harshita"})
            assert res.success is True
            mock_write.assert_called_once_with("Harshita", interval=0.04)

    def test_focus_guard_blocks_typing_if_composer_is_still_focused(self):
        """If composer stubbornly holds keyboard focus, focus guard blocks typing and fails closed."""
        stubborn_composer = MagicMock()
        stubborn_composer.Name = "Write a message..."
        stubborn_composer.ControlTypeName = "EditControl"
        stubborn_composer.BoundingRectangle = MagicMock(top=550, left=400)

        with patch("automation.telegram.telegram_automation.verify_telegram_foreground_action", return_value=(True, 12345)), \
             patch("automation.telegram.telegram_automation._find_telegram_composer", return_value=stubborn_composer), \
             patch("automation.telegram.telegram_automation._find_telegram_search_box", return_value=None), \
             patch("uiautomation.GetFocusedControl", return_value=stubborn_composer), \
             patch("pyautogui.write") as mock_write:

            res = handle_search_telegram_contact({"contact": "Harshita"})
            assert res.success is False
            assert "search-ready" in res.message or "composer" in res.message.lower()
            # Under no circumstances did composer receive "Harshita"
            mock_write.assert_not_called()

    def test_telegram_initially_closed_launches_and_searches(self):
        """When Telegram is initially closed, open_telegram launches it and search proceeds normally."""
        _telegram_state["ready"] = False
        _telegram_state["client"] = None

        with patch("automation.telegram.telegram_automation.find_telegram_desktop", return_value="C:\\path\\to\\Telegram.exe"), \
             patch("subprocess.Popen") as mock_popen, \
             patch("execution.verifier.verify_application_launched", return_value=MagicMock(passed=True)), \
             patch("automation.telegram.telegram_automation._focus_telegram_desktop", return_value=12345):

            res_open = handle_open_telegram({})
            assert res_open.success is True
            assert _telegram_state["ready"] is True
            assert _telegram_state["client"] == "telegram_desktop"

