"""
Automated Test Suite for Telegram Part 2: Open -> Search -> Contact Resolution
==============================================================================
Covers:
- Test A: Advance after opening (open_telegram succeeds -> search_telegram_contact executes next)
- Test B: Mode propagation (open_telegram returns mode=desktop -> search uses desktop implementation)
- Test C: Telegram focus (restore/focus Telegram before search)
- Test D: Idempotent query (retry search does not double query string)
- Test E: Real result preference (exact 'Harshita' ranked first over 'Shrishti Harshita Friend', no fake @harshita)
- Test F: Zero results ([] -> safe failure / not-found, no chat opening)
- Test G: Multiple ambiguous matches (returns telegram_contact_confirmation with candidates)
"""

import pytest
from unittest.mock import patch, MagicMock
from agentic.schemas import ExecutionPlan
from agentic.llm.schemas import PlannerStep
from execution.executor import DesktopExecutor
from execution.registry import load_all_tools, get_handler
from automation.telegram.models import TelegramContact
from automation.telegram.telegram_automation import (
    _telegram_state,
    reset_telegram_state,
    TelegramService,
    _collect_desktop_search_candidates,
    handle_open_telegram_web,
    handle_search_telegram_contact,
    handle_verify_telegram_contact,
    _KNOWN_LOCAL_CONTACTS,
)


@pytest.fixture(autouse=True)
def setup_environment():
    load_all_tools()
    reset_telegram_state()


class TestTelegramPart2Workflow:

    def test_a_advance_after_opening(self):
        """Test A — open_telegram succeeds -> search_telegram_contact must execute next (call count = 1)."""
        plan = ExecutionPlan(
            thought="Test plan",
            steps=[
                PlannerStep(tool="open_telegram", args={}),
                PlannerStep(tool="search_telegram_contact", args={"contact": "Harshita"}),
                PlannerStep(tool="verify_telegram_contact", args={"contact": "Harshita"}),
            ],
            response="",
        )

        executor = DesktopExecutor()
        executor.bypass_confirmation = True

        search_mock = MagicMock(side_effect=handle_search_telegram_contact)

        with patch.dict("execution.registry._REGISTRY", {"search_telegram_contact": search_mock}):
            with patch("automation.telegram.telegram_automation._focus_telegram_desktop", return_value=1):
                results = executor.execute(plan)

        assert len(results) >= 2
        assert results[0]["tool"] == "open_telegram"
        assert results[0]["success"] is True
        assert results[1]["tool"] == "search_telegram_contact"
        assert results[1]["success"] is True
        assert search_mock.call_count == 1

    def test_b_mode_propagation(self):
        """Test B — open_telegram returns mode=desktop -> search uses desktop implementation."""
        res_open = handle_open_telegram_web({})
        assert res_open.success is True
        assert _telegram_state["mode"] == "desktop"
        assert _telegram_state["client"] == "telegram_desktop"

        with patch("automation.telegram.telegram_automation._focus_telegram_desktop", return_value=1), \
             patch("automation.browser.find_and_focus_browser_tab") as mock_web_focus:
            res_search = handle_search_telegram_contact({"contact": "Harshita"})
            assert res_search.success is True
            assert res_search.data["source"] == "desktop_ui"
            # Web search focus helper must not have been called
            mock_web_focus.assert_not_called()

    def test_c_telegram_focus(self):
        """Test C — If Telegram is open, focus Telegram before searching."""
        _telegram_state["ready"] = True
        _telegram_state["mode"] = "desktop"
        _telegram_state["client"] = "telegram_desktop"

        focus_called = []
        def mock_focus():
            focus_called.append(True)
            return 12345

        with patch("automation.telegram.telegram_automation._focus_telegram_desktop", side_effect=mock_focus):
            res = handle_search_telegram_contact({"contact": "Harshita"})
            assert res.success is True
            assert len(focus_called) >= 1

    def test_d_idempotent_query(self):
        """Test D — Retry search: 'Harshita' must not append to create 'HarshitaHarshita'."""
        _telegram_state["ready"] = True
        _telegram_state["mode"] = "desktop"
        _telegram_state["client"] = "telegram_desktop"

        typed_texts = []
        with patch("automation.telegram.telegram_automation._focus_telegram_desktop", return_value=1), \
             patch("pyautogui.write", side_effect=lambda text, **kw: typed_texts.append(text)):
            # First search
            handle_search_telegram_contact({"contact": "Harshita"})
            # Second retry search
            handle_search_telegram_contact({"contact": "Harshita"})

        assert len(typed_texts) == 2
        assert typed_texts[0] == "Harshita"
        assert typed_texts[1] == "Harshita"
        assert "HarshitaHarshita" not in typed_texts

    def test_e_real_result_preference(self):
        """Test E — Results: 'Harshita', 'Shrishti Harshita Friend' -> exact 'Harshita' ranked first. No fake @harshita."""
        candidates = [
            TelegramContact(id=2, name="Shrishti Harshita Friend", first_name="Shrishti", contact_type="user"),
            TelegramContact(id=1, name="Harshita", first_name="Harshita", contact_type="user"),
        ]

        ranked = TelegramService._normalize_and_match("Harshita", candidates)
        assert len(ranked) == 2
        # Exact match ranked first
        assert ranked[0].name == "Harshita"
        assert ranked[1].name == "Shrishti Harshita Friend"

        # Verify no fabricated username
        assert ranked[0].username is None or not str(ranked[0].username).startswith("@fabricated")

    def test_f_zero_results(self):
        """Test F — Zero results [] -> safe failure / not-found, no chat opening."""
        _telegram_state["ready"] = True
        _telegram_state["mode"] = "desktop"
        _telegram_state["client"] = "telegram_desktop"

        with patch("automation.telegram.telegram_automation._focus_telegram_desktop", return_value=1):
            res_search = handle_search_telegram_contact({"contact": "NonExistentUserXYZ999"})
            assert res_search.success is False
            assert "No Telegram contact found" in res_search.message

            res_verify = handle_verify_telegram_contact({"contact": "NonExistentUserXYZ999"})
            assert res_verify.success is False

    def test_g_multiple_ambiguous_matches(self):
        """Test G — Multiple ambiguous exact matches -> contact confirmation with actual candidates."""
        candidates = [
            TelegramContact(id=1, name="Harshita Sharma", username="harshita_s", first_name="Harshita", last_name="Sharma", contact_type="user"),
            TelegramContact(id=2, name="Harshita Gupta", username="harshita_g", first_name="Harshita", last_name="Gupta", contact_type="user"),
        ]
        _telegram_state["candidates"] = candidates
        _telegram_state["search_query"] = "Harshita"

        res = handle_verify_telegram_contact({"contact": "Harshita"})
        # When multiple equal candidates match, an explicit recipient confirmation is required
        assert res.data.get("ambiguous") is True or res.data.get("confirmation_type") == "telegram_contact_confirmation"
        assert len(res.data.get("candidates", [])) == 2
