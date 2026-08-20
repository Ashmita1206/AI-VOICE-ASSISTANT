"""
Unit Tests for Telegram Router & Safety Invariants
===================================================

Tests state transitions, 0/1/multiple matches, disambiguation, positive/negative
confirmation, duplicate execution prevention, wrong state guards, and cancellation.
"""

import pytest
from unittest.mock import MagicMock
from automation.telegram.models import (
    FlowStatus,
    TelegramContact,
    TelegramFlowMode,
)
from automation.telegram import _run_async
from automation.telegram.router import TelegramAutomationRouter
from automation.telegram.telegram_automation import TelegramService


@pytest.fixture
def mock_service():
    """Mock TelegramService with injectable callables."""
    svc = MagicMock(spec=TelegramService)

    # Defaults
    svc.search_contacts.return_value = []
    svc.open_preview.return_value = FlowStatus.LINK_LAUNCH_REQUESTED
    svc.send_current_draft.return_value = FlowStatus.SEND_KEY_DISPATCHED

    return svc


@pytest.fixture
def sample_contacts():
    return [
        TelegramContact(id=1, name="Harshita Sharma", username="harshita_s", first_name="Harshita", last_name="Sharma"),
        TelegramContact(id=2, name="Harshita Gupta", username="harshita_g", first_name="Harshita", last_name="Gupta"),
    ]


class TestTelegramRouterFlows:
    """Tests multi-turn orchestration and safety guards."""

    def test_full_successful_flow_single_match(self, mock_service):
        contact = TelegramContact(id=1, name="Harshita Sharma", username="harshita_s")
        mock_service.search_contacts.return_value = [contact]

        router = TelegramAutomationRouter(mock_service)

        # Turn 1: New Command
        cmd1 = "Telegram pe Harshita ko message bhejo ki main 10 min me aa rhi hu"
        res1 = _run_async(router.handle_input(cmd1))

        assert res1.status == FlowStatus.CONFIRMATION_REQUIRED
        assert router.state.mode == TelegramFlowMode.CONFIRMATION
        assert router.state.preview_opened is True
        assert router.state.pending_action_id is not None
        mock_service.open_preview.assert_called_once_with("harshita_s", "main 10 min me aa rhi hu")
        # Ensure Enter key was NOT pressed yet
        mock_service.send_current_draft.assert_not_called()

        # Turn 2: Confirmation "haan bhej do"
        res2 = _run_async(router.handle_input("haan bhej do"))

        assert res2.status == FlowStatus.SEND_KEY_DISPATCHED
        assert router.state.mode == TelegramFlowMode.COMPLETED
        assert router.state.executed is True
        mock_service.send_current_draft.assert_called_once()

    def test_cancel_flow(self, mock_service):
        contact = TelegramContact(id=1, name="Rahul Verma", username="rahul_99")
        mock_service.search_contacts.return_value = [contact]

        router = TelegramAutomationRouter(mock_service)

        # Turn 1: New Command
        _run_async(router.handle_input("Send a telegram to @rahul_99 saying call me"))
        assert router.state.mode == TelegramFlowMode.CONFIRMATION

        # Turn 2: Rejection "nahi rehne do"
        res2 = _run_async(router.handle_input("nahi rehne do"))

        assert res2.status == FlowStatus.CANCELLED
        assert router.state.mode == TelegramFlowMode.CANCELLED
        assert router.state.executed is False
        mock_service.send_current_draft.assert_not_called()

    def test_disambiguation_flow_option_number(self, mock_service, sample_contacts):
        mock_service.search_contacts.return_value = sample_contacts

        router = TelegramAutomationRouter(mock_service)

        # Turn 1: New Command (multiple matches)
        res1 = _run_async(router.handle_input("Telegram pe Harshita ko message bhejo ki hi"))
        assert res1.status == FlowStatus.DISAMBIGUATION_REQUIRED
        assert router.state.mode == TelegramFlowMode.DISAMBIGUATION

        # Turn 2: Disambiguation "option 2"
        res2 = _run_async(router.handle_input("option 2"))
        assert res2.status == FlowStatus.CONFIRMATION_REQUIRED
        assert router.state.selected_contact.name == "Harshita Gupta"
        assert router.state.mode == TelegramFlowMode.CONFIRMATION
        mock_service.open_preview.assert_called_once_with("harshita_g", "hi")

        # Turn 3: Confirmation "yes send it"
        res3 = _run_async(router.handle_input("yes send it"))
        assert res3.status == FlowStatus.SEND_KEY_DISPATCHED
        mock_service.send_current_draft.assert_called_once()

    def test_disambiguation_spoken_name(self, mock_service, sample_contacts):
        mock_service.search_contacts.return_value = sample_contacts
        router = TelegramAutomationRouter(mock_service)

        _run_async(router.handle_input("Telegram pe Harshita ko message bhejo ki hi"))
        res2 = _run_async(router.handle_input("Harshita Sharma"))

        assert res2.status == FlowStatus.CONFIRMATION_REQUIRED
        assert router.state.selected_contact.name == "Harshita Sharma"

    def test_disambiguation_invalid_choice_reprompts(self, mock_service, sample_contacts):
        mock_service.search_contacts.return_value = sample_contacts
        router = TelegramAutomationRouter(mock_service)

        _run_async(router.handle_input("Telegram pe Harshita ko message bhejo ki hi"))

        # Invalid choice: option 99
        res2 = _run_async(router.handle_input("option 99"))
        assert res2.status == FlowStatus.INVALID_SELECTION
        assert router.state.mode == TelegramFlowMode.DISAMBIGUATION  # state remains DISAMBIGUATION

    def test_zero_contact_matches(self, mock_service):
        mock_service.search_contacts.return_value = []
        router = TelegramAutomationRouter(mock_service)

        res = _run_async(router.handle_input("Telegram pe UnknownPerson ko message bhejo ki hi"))
        assert res.status == FlowStatus.CONTACT_NOT_FOUND
        assert router.state.mode == TelegramFlowMode.ERROR
        mock_service.open_preview.assert_not_called()
        mock_service.send_current_draft.assert_not_called()

    def test_contact_without_username(self, mock_service):
        contact = TelegramContact(id=5, name="Aman Kumar", username=None)
        mock_service.search_contacts.return_value = [contact]
        router = TelegramAutomationRouter(mock_service)

        res = _run_async(router.handle_input("Telegram pe Aman ko message bhejo ki hi"))
        assert res.status == FlowStatus.USERNAME_UNAVAILABLE
        assert router.state.mode == TelegramFlowMode.ERROR
        mock_service.open_preview.assert_not_called()
        mock_service.send_current_draft.assert_not_called()

    def test_duplicate_confirmation_protection(self, mock_service):
        contact = TelegramContact(id=1, name="Harshita Sharma", username="harshita_s")
        mock_service.search_contacts.return_value = [contact]
        router = TelegramAutomationRouter(mock_service)

        # 1. New command -> Preview
        _run_async(router.handle_input("Telegram pe Harshita ko message bhejo ki hi"))
        # 2. First confirmation -> Send
        res1 = _run_async(router.handle_input("haan bhej do"))
        assert res1.status == FlowStatus.SEND_KEY_DISPATCHED
        assert mock_service.send_current_draft.call_count == 1

        # 3. Duplicate confirmation -> Blocked
        res2 = _run_async(router.handle_input("haan bhej do"))
        # Second 'yes' is treated as NEW_COMMAND or ALREADY_EXECUTED/NOT_TELEGRAM
        # Since router mode was COMPLETED, input state becomes NEW_COMMAND.
        # "haan bhej do" is not a Telegram command.
        assert mock_service.send_current_draft.call_count == 1  # Still 1 call!

    def test_confirmation_without_pending_action_does_nothing(self, mock_service):
        router = TelegramAutomationRouter(mock_service)
        # Random "yes" in IDLE state
        res = _run_async(router.handle_input("yes"))
        assert res.status == FlowStatus.NOT_TELEGRAM
        mock_service.send_current_draft.assert_not_called()

    def test_preview_failure_prevents_send(self, mock_service):
        contact = TelegramContact(id=1, name="Harshita Sharma", username="harshita_s")
        mock_service.search_contacts.return_value = [contact]
        mock_service.open_preview.return_value = FlowStatus.ERROR

        router = TelegramAutomationRouter(mock_service)

        res = _run_async(router.handle_input("Telegram pe Harshita ko message bhejo ki hi"))
        assert res.status == FlowStatus.ERROR
        assert router.state.mode == TelegramFlowMode.ERROR
        mock_service.send_current_draft.assert_not_called()

    def test_open_telegram_command_rejected_by_router(self, mock_service):
        """Hard guard: 'open telegram' must NOT enter messaging flow."""
        router = TelegramAutomationRouter(mock_service)

        for open_cmd in ("open telegram", "open telegram desktop", "telegram kholo", "launch telegram", "start telegram"):
            res = _run_async(router.handle_input(open_cmd))
            assert res.status == FlowStatus.NOT_TELEGRAM
            assert router.state.mode == TelegramFlowMode.IDLE
            mock_service.search_contacts.assert_not_called()
            mock_service.open_preview.assert_not_called()
            mock_service.send_current_draft.assert_not_called()
