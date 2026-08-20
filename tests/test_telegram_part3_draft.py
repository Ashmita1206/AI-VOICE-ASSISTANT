"""
Automated Test Suite for Telegram Part 3: Contact Approval -> Open Chat -> Header Verification -> Focus Composer -> Type Draft -> Send Confirmation Gate
=====================================================================================================================================================
Covers:
- Test A: Contact approval resumes correctly (telegram_contact_confirmation -> approve -> open_telegram_chat called exactly once, no re-plan)
- Test B: Correct contact opened (approved 'Harshita' opens 'Harshita')
- Test C: Header mismatch blocks execution (header 'Another Person' -> focus composer / type message / send NOT called)
- Test D: Composer focus required (if composer cannot be focused -> type message NOT called)
- Test E: Draft idempotency (retry produces 'hello', not 'hellohello')
- Test F: No send before final confirmation (draft verification success -> send call count = 0, telegram_send_confirmation generated)
- Test G: Cancellation safe (if final send confirmation is cancelled -> send call count = 0)
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
    set_telegram_contact_confirmed,
    set_telegram_send_confirmed,
    handle_open_telegram_chat,
    handle_verify_telegram_chat_header,
    handle_focus_telegram_composer,
    handle_type_telegram_message,
    handle_send_telegram_message,
    _chat_header_matches,
)


@pytest.fixture(autouse=True)
def setup_environment():
    load_all_tools()
    reset_telegram_state()
    # Establish valid pre-condition from Part 2:
    _telegram_state["ready"] = True
    _telegram_state["mode"] = "desktop"
    _telegram_state["client"] = "telegram_desktop"
    _telegram_state["contact"] = TelegramContact(id=1, name="Harshita", first_name="Harshita", contact_type="user")
    _telegram_state["candidates"] = [_telegram_state["contact"]]


class TestTelegramPart3Workflow:

    def test_a_contact_approval_resumes_correctly(self):
        """Test A — Contact approval resumes execution at open_telegram_chat without re-planning or repeating search."""
        set_telegram_contact_confirmed(True)

        plan = ExecutionPlan(
            thought="Resumed Telegram Plan",
            steps=[
                PlannerStep(tool="open_telegram_chat", args={"contact": "Harshita"}),
                PlannerStep(tool="verify_telegram_chat_header", args={"contact": "Harshita"}),
                PlannerStep(tool="focus_telegram_composer", args={}),
                PlannerStep(tool="type_telegram_message", args={"message": "hello"}),
                PlannerStep(tool="send_telegram_message", args={"contact": "Harshita", "message": "hello"}),
            ],
            response="",
        )

        executor = DesktopExecutor()
        executor.bypass_confirmation = True

        open_chat_mock = MagicMock(side_effect=handle_open_telegram_chat)
        send_mock = MagicMock(side_effect=handle_send_telegram_message)

        with patch.dict("execution.registry._REGISTRY", {
            "open_telegram_chat": open_chat_mock,
            "send_telegram_message": send_mock,
        }):
            with patch("automation.telegram.telegram_automation.ensure_telegram_foreground", return_value=1), \
                 patch("automation.telegram.telegram_automation._focus_telegram_desktop", return_value=1), \
                 patch("automation.telegram.telegram_automation._chat_header_matches", return_value=True), \
                 patch("pyautogui.write"), \
                 patch("pyautogui.hotkey"), \
                 patch("pyautogui.press"):
                results = executor.execute(plan)

        # open_telegram_chat executed once
        assert open_chat_mock.call_count == 1
        # Pipeline executed up through type_telegram_message and paused before send
        assert len(results) >= 4
        assert results[0]["tool"] == "open_telegram_chat"
        assert results[0]["success"] is True
        assert results[1]["tool"] == "verify_telegram_chat_header"
        assert results[1]["success"] is True
        assert results[2]["tool"] == "focus_telegram_composer"
        assert results[2]["success"] is True
        assert results[3]["tool"] == "type_telegram_message"
        assert results[3]["success"] is True
        assert results[3]["requires_confirmation"] is True
        assert results[3]["data"]["confirmation_type"] == "telegram_send_confirmation"
        # Send was NOT called in Part 3
        assert send_mock.call_count == 0

    def test_b_correct_contact_opened(self):
        """Test B — Approved 'Harshita' opens 'Harshita' and matches header."""
        set_telegram_contact_confirmed(True)

        with patch("automation.telegram.telegram_automation.ensure_telegram_foreground", return_value=1), \
             patch("automation.telegram.telegram_automation._focus_telegram_desktop", return_value=1), \
             patch("automation.telegram.telegram_automation._chat_header_matches", return_value=True), \
             patch("pyautogui.press"):
            res = handle_open_telegram_chat({"contact": "Harshita"})
            assert res.success is True
            assert res.data["contact"] == "Harshita"
            assert _telegram_state["chat_open"] is True

    def test_c_header_mismatch_blocks_execution(self):
        """Test C — Header mismatch (e.g. 'Another Person') blocks composer focus, typing, and send."""
        set_telegram_contact_confirmed(True)
        _telegram_state["chat_open"] = True

        # Header returns mismatch
        with patch("automation.telegram.telegram_automation.ensure_telegram_foreground", return_value=1), \
             patch("automation.telegram.telegram_automation._chat_header_matches", return_value=False):
            res_header = handle_verify_telegram_chat_header({"contact": "Harshita"})
            assert res_header.success is False
            assert "does not exactly match" in res_header.message

            # Downstream tools refuse to run without header_verified
            res_focus = handle_focus_telegram_composer({})
            assert res_focus.success is False

            res_type = handle_type_telegram_message({"message": "hello"})
            assert res_type.success is False

            res_send = handle_send_telegram_message({"contact": "Harshita", "message": "hello"})
            assert res_send.success is False

    def test_d_composer_focus_required(self):
        """Test D — If composer cannot be focused, message typing is blocked."""
        set_telegram_contact_confirmed(True)
        _telegram_state["chat_open"] = True
        _telegram_state["header_verified"] = True
        _telegram_state["composer_focused"] = False

        # Attempt to type without composer focus
        res_type = handle_type_telegram_message({"message": "hello"})
        assert res_type.success is False
        assert "incomplete; refusing to type" in res_type.message

    def test_e_draft_idempotency(self):
        """Test E — Retrying type_telegram_message produces 'hello', not 'hellohello'."""
        set_telegram_contact_confirmed(True)
        _telegram_state["chat_open"] = True
        _telegram_state["header_verified"] = True
        _telegram_state["composer_focused"] = True

        typed_chunks = []
        hotkeys = []

        with patch("automation.telegram.telegram_automation.ensure_telegram_foreground", return_value=1), \
             patch("automation.telegram.telegram_automation._focus_telegram_desktop", return_value=1), \
             patch("automation.telegram.telegram_automation._chat_header_matches", return_value=True), \
             patch("pyautogui.write", side_effect=lambda text, **kw: typed_chunks.append(text)), \
             patch("pyautogui.hotkey", side_effect=lambda *keys: hotkeys.append(keys)), \
             patch("pyautogui.press"):
            # First typing
            res1 = handle_type_telegram_message({"message": "hello"})
            assert res1.success is True

            # Second typing (retry)
            res2 = handle_type_telegram_message({"message": "hello"})
            assert res2.success is True

        assert len(typed_chunks) == 2
        assert typed_chunks[0] == "hello"
        assert typed_chunks[1] == "hello"
        assert "hellohello" not in typed_chunks
        # Verified that clearing hotkey (ctrl+a) was called before writing
        assert ("ctrl", "a") in hotkeys

    def test_f_no_send_before_final_confirmation(self):
        """Test F — After successful draft verification, send call count = 0 and telegram_send_confirmation generated."""
        set_telegram_contact_confirmed(True)
        _telegram_state["chat_open"] = True
        _telegram_state["header_verified"] = True
        _telegram_state["composer_focused"] = True

        with patch("automation.telegram.telegram_automation.ensure_telegram_foreground", return_value=1), \
             patch("automation.telegram.telegram_automation._focus_telegram_desktop", return_value=1), \
             patch("automation.telegram.telegram_automation._chat_header_matches", return_value=True), \
             patch("pyautogui.write"), \
             patch("pyautogui.hotkey"), \
             patch("pyautogui.press"):
            res = handle_type_telegram_message({"message": "hello"})

        assert res.success is True
        assert res.requires_confirmation is True
        assert res.data["confirmation_type"] == "telegram_send_confirmation"
        assert res.data["draft_ready"] is True
        assert _telegram_state["draft_ready"] is True
        assert _telegram_state["message"] == "hello"

    def test_g_cancellation_safe(self):
        """Test G — If final send confirmation is cancelled, send tool is not executed."""
        set_telegram_contact_confirmed(True)
        set_telegram_send_confirmed(False)  # User cancels at final send confirmation
        _telegram_state["chat_open"] = True
        _telegram_state["header_verified"] = True
        _telegram_state["composer_focused"] = True
        _telegram_state["draft_ready"] = True

        res = handle_send_telegram_message({"contact": "Harshita", "message": "hello"})
        assert res.success is False
        assert "requires explicit" in res.message or "not been approved" in res.message or "Security violation" in res.message
        assert _telegram_state.get("sent_verified") is not True

    def test_h_text_child_invokes_row_parent(self):
        """Test H — If TextControl('Harshita') is inside a ListItem parent, row parent is invoked."""
        from automation.telegram.telegram_automation import _find_telegram_contact_row, _invoke_or_click_row
        
        mock_parent = MagicMock()
        mock_parent.ControlTypeName = "ListItemControl"
        mock_parent.Name = "Harshita, Online"
        mock_parent.BoundingRectangle = MagicMock(top=120, width=lambda: 200, height=lambda: 50)
        mock_parent.GetChildren.return_value = []

        mock_text_child = MagicMock()
        mock_text_child.ControlTypeName = "TextControl"
        mock_text_child.Name = "Harshita"
        mock_text_child.BoundingRectangle = MagicMock(top=130, width=lambda: 100, height=lambda: 20)
        mock_text_child.GetParentControl.return_value = mock_parent
        mock_text_child.GetChildren.return_value = []

        mock_parent.GetChildren.return_value = [mock_text_child]

        mock_window = MagicMock()
        mock_window.GetChildren.return_value = [mock_parent]

        with patch("automation.telegram.telegram_automation._uia_window", return_value=mock_window), \
             patch("automation.telegram.telegram_automation._get_telegram_window_handle", return_value=123):
            found_ctrl = _find_telegram_contact_row("Harshita", 123)
            assert found_ctrl is not None
            # Must return the interactive parent container, not the passive text child
            assert found_ctrl == mock_parent

    def test_i_exact_row_matching_priority(self):
        """Test I — Between 'Harshita' and 'Shrishti Harshita Friend', exact 'Harshita' row is selected."""
        from automation.telegram.telegram_automation import _find_telegram_contact_row

        mock_partial = MagicMock()
        mock_partial.ControlTypeName = "ListItemControl"
        mock_partial.Name = "Shrishti Harshita Friend"
        mock_partial.BoundingRectangle = MagicMock(top=100, width=lambda: 200, height=lambda: 50)
        mock_partial.GetChildren.return_value = []

        mock_exact = MagicMock()
        mock_exact.ControlTypeName = "ListItemControl"
        mock_exact.Name = "Harshita"
        mock_exact.BoundingRectangle = MagicMock(top=180, width=lambda: 200, height=lambda: 50)
        mock_exact.GetChildren.return_value = []

        mock_window = MagicMock()
        mock_window.GetChildren.return_value = [mock_partial, mock_exact]

        with patch("automation.telegram.telegram_automation._uia_window", return_value=mock_window), \
             patch("automation.telegram.telegram_automation._get_telegram_window_handle", return_value=123):
            found_ctrl = _find_telegram_contact_row("Harshita", 123)
            assert found_ctrl is not None
            assert found_ctrl == mock_exact

    def test_j_chrome_focus_loss_refocuses_telegram(self):
        """Test J — After Chrome confirmation steals focus, Telegram is refocused before row invocation."""
        set_telegram_contact_confirmed(True)

        focus_calls = []
        def mock_foreground():
            focus_calls.append("foreground")
            return 12345

        with patch("automation.telegram.telegram_automation.ensure_telegram_foreground", side_effect=mock_foreground), \
             patch("automation.telegram.telegram_automation._find_telegram_contact_row", return_value=None), \
             patch("automation.telegram.telegram_automation._is_chat_view_active", return_value=True), \
             patch("pyautogui.press"):
            res = handle_open_telegram_chat({"contact": "Harshita"})
            assert res.success is True
            assert len(focus_calls) >= 1

    def test_k_click_without_transition_fails_closed(self):
        """Test K — If row is clicked but chat UI transition is not observed, open_telegram_chat fails."""
        set_telegram_contact_confirmed(True)

        with patch("automation.telegram.telegram_automation.ensure_telegram_foreground", return_value=1), \
             patch("automation.telegram.telegram_automation._find_telegram_contact_row", return_value=MagicMock()), \
             patch("automation.telegram.telegram_automation._invoke_or_click_row", return_value=True), \
             patch("automation.telegram.telegram_automation._is_chat_view_active", return_value=False), \
             patch("automation.telegram.telegram_automation._chat_header_matches", return_value=False), \
             patch("pyautogui.press"):
            res = handle_open_telegram_chat({"contact": "Harshita"})
            assert res.success is False
            assert "UI transition to chat view was not observed" in res.message
            assert _telegram_state.get("chat_open") is False

    def test_l_header_mismatch_blocks_downstream_tools(self):
        """Test L — Header mismatch blocks composer, typing, and send calls with 0 executions."""
        set_telegram_contact_confirmed(True)
        _telegram_state["chat_open"] = True

        with patch("automation.telegram.telegram_automation.ensure_telegram_foreground", return_value=1), \
             patch("automation.telegram.telegram_automation._chat_header_matches", return_value=False):
            res_header = handle_verify_telegram_chat_header({"contact": "Harshita"})
            assert res_header.success is False

        # Attempt downstream steps
        res_focus = handle_focus_telegram_composer({})
        assert res_focus.success is False
        assert "incomplete" in res_focus.message

        res_type = handle_type_telegram_message({"message": "hello"})
        assert res_type.success is False

        res_send = handle_send_telegram_message({"contact": "Harshita", "message": "hello"})
        assert res_send.success is False

