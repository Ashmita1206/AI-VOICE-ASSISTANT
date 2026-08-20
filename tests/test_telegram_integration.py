"""
Integration Tests for Telegram Hybrid Automation
=================================================

Tests complete integration into IntentClassifier, CommandRegistry, ToolRegistry,
ExecutionRegistry, persistent router state across turns, follow-up routing,
and non-hijacking of global yes/no commands.
"""

import pytest
from unittest.mock import MagicMock
from agent.intent_classifier import IntentClassifier
from agent.command_registry import get_intent, get_all_intents
from agentic.tool_registry import _TOOLS
from execution.registry import get_handler, load_all_tools
from agentic.memory.session_state import get_session
from agentic.conversation.confirmation_manager import handle_pending_confirmation
from automation.telegram import (
    get_telegram_router,
    get_telegram_service,
    FlowStatus,
    TelegramContact,
    TelegramFlowMode,
)


@pytest.fixture(autouse=True)
def reset_state():
    """Reset session state and Telegram router before each test."""
    session = get_session()
    session.clear_all()
    router = get_telegram_router()
    router.reset()
    yield
    session.clear_all()
    router.reset()


class TestTelegramIntentIntegration:
    """Tests intent classification for Telegram commands."""

    def test_send_telegram_message_intent_registered(self):
        intent = get_intent("send_telegram_message")
        assert intent is not None
        assert intent.name == "send_telegram_message"
        assert "telegram" in intent.keywords

    def test_intent_classification_hinglish(self):
        classifier = IntentClassifier()
        cmd = classifier.classify("Telegram pe Harshita ko message bhejo ki main 10 min me aa rhi hu")
        assert cmd.intent == "send_telegram_message"
        assert cmd.entities.get("contact", "").lower() == "harshita"
        assert "10 min" in cmd.entities.get("message", "")

    def test_no_collision_with_whatsapp(self):
        classifier = IntentClassifier()
        cmd = classifier.classify("WhatsApp pe Rahul ko message bhejo ki hello")
        assert cmd.intent != "send_telegram_message"

    def test_no_collision_with_open_telegram(self):
        classifier = IntentClassifier()
        cmd = classifier.classify("Open Telegram")
        assert cmd.intent in ("open_application", "open_telegram")
        assert cmd.intent != "send_telegram_message"


class TestTelegramPlannerToolIntegration:
    """Tests planner tool registry for Telegram."""

    def test_tool_definition_registered(self):
        tools = {t.name: t for t in _TOOLS}
        assert "send_telegram_message" in tools
        tdef = tools["send_telegram_message"]
        assert "send" in tdef.description.lower()
        # Verify decomposed tools also registered
        for tool_name in ("open_telegram_web", "search_telegram_contact", "verify_telegram_contact",
                          "open_telegram_chat", "type_telegram_message",
                          "verify_telegram_message_sent", "close_telegram"):
            assert tool_name in tools, f"Missing decomposed tool: {tool_name}"


class TestTelegramExecutionRegistryIntegration:
    """Tests execution layer registration and handler execution."""

    def test_handler_registered(self):
        load_all_tools()
        handler = get_handler("send_telegram_message")
        assert handler is not None

    def test_decomposed_handlers_all_registered(self):
        load_all_tools()
        for name in ("open_telegram", "search_telegram_contact", "verify_telegram_contact",
                      "open_telegram_chat", "type_telegram_message", "send_telegram_message",
                      "verify_telegram_message_sent", "close_telegram"):
            assert get_handler(name) is not None, f"Handler missing: {name}"

    def test_handler_execution_single_match(self):
        """Test that decomposed search + verify produces correct contact."""
        load_all_tools()
        from automation.telegram.telegram_automation import _telegram_state
        from unittest.mock import patch
        _telegram_state["ready"] = True
        _telegram_state["client"] = "telegram_web"

        search_handler = get_handler("search_telegram_contact")
        verify_handler = get_handler("verify_telegram_contact")

        with patch("automation.browser.find_and_focus_browser_tab", return_value=True), \
             patch("execution.verifier._is_window_visible", return_value=True):
            res1 = search_handler({"contact": "Harshita"})
        assert res1.success is True

        res2 = verify_handler({"contact": "Harshita"})
        assert res2.success is True
        assert res2.data["contact"] == "Harshita"


class TestTelegramMultiTurnStateAndFollowUpRouting:
    """Tests persistent state across turns and follow-up utterance routing via the router."""

    def test_multi_turn_disambiguation_and_confirmation_flow(self):
        load_all_tools()
        svc = get_telegram_service()
        svc.search_contacts = MagicMock(return_value=[
            TelegramContact(id=1, name="Harshita Sharma", username="harshita_s"),
            TelegramContact(id=2, name="Harshita Gupta", username="harshita_g"),
        ])
        svc.open_preview = MagicMock(return_value=FlowStatus.LINK_LAUNCH_REQUESTED)
        svc.send_current_draft = MagicMock(return_value=FlowStatus.SEND_KEY_DISPATCHED)

        router = get_telegram_router()
        router.reset()

        from automation.telegram import _run_async

        # Turn 1: New Command -> 2 contacts found -> DISAMBIGUATION
        res1 = _run_async(router.handle_input("Telegram pe Harshita ko message bhejo ki hello"))
        assert res1.status == FlowStatus.DISAMBIGUATION_REQUIRED
        assert router.state.mode == TelegramFlowMode.DISAMBIGUATION

        # Turn 2: Follow-up utterance "Option 2" routed through confirmation_manager
        handled2, msg2 = handle_pending_confirmation("Option 2")
        assert handled2 is True
        assert "Harshita Gupta" in msg2
        assert router.state.mode == TelegramFlowMode.CONFIRMATION
        svc.open_preview.assert_called_once_with("harshita_g", "hello")
        svc.send_current_draft.assert_not_called()

        # Turn 3: Follow-up utterance "haan bhej do" -> SEND
        handled3, msg3 = handle_pending_confirmation("haan bhej do")
        assert handled3 is True
        assert "Enter key dispatched" in msg3
        assert router.state.mode == TelegramFlowMode.COMPLETED
        svc.send_current_draft.assert_called_once()

    def test_cancel_flow(self):
        load_all_tools()
        svc = get_telegram_service()
        svc.search_contacts = MagicMock(return_value=[
            TelegramContact(id=1, name="Harshita Sharma", username="harshita_s")
        ])
        svc.open_preview = MagicMock(return_value=FlowStatus.LINK_LAUNCH_REQUESTED)
        svc.send_current_draft = MagicMock(return_value=FlowStatus.SEND_KEY_DISPATCHED)

        router = get_telegram_router()
        router.reset()

        from automation.telegram import _run_async

        # Turn 1: New Command -> CONFIRMATION
        _run_async(router.handle_input("Telegram pe Harshita ko message bhejo ki hello"))
        assert router.state.mode == TelegramFlowMode.CONFIRMATION

        # Turn 2: Follow-up utterance "nahi cancel kar do"
        handled2, msg2 = handle_pending_confirmation("nahi cancel kar do")
        assert handled2 is True
        assert "cancelled" in msg2.lower()
        svc.send_current_draft.assert_not_called()

    def test_no_global_yes_hijacking_when_idle(self):
        """Verify that saying 'yes' or 'Option 1' when Telegram is IDLE does NOT send anything."""
        svc = get_telegram_service()
        svc.send_current_draft = MagicMock()

        router = get_telegram_router()
        router.reset()
        assert router.state.mode == TelegramFlowMode.IDLE

        handled, msg = handle_pending_confirmation("yes")
        assert handled is False
        svc.send_current_draft.assert_not_called()

        handled_opt, msg_opt = handle_pending_confirmation("Option 1")
        assert handled_opt is False
        svc.send_current_draft.assert_not_called()

    def test_duplicate_confirmation_does_not_send_twice(self):
        load_all_tools()
        svc = get_telegram_service()
        svc.search_contacts = MagicMock(return_value=[
            TelegramContact(id=1, name="Harshita Sharma", username="harshita_s")
        ])
        svc.open_preview = MagicMock(return_value=FlowStatus.LINK_LAUNCH_REQUESTED)
        svc.send_current_draft = MagicMock(return_value=FlowStatus.SEND_KEY_DISPATCHED)

        router = get_telegram_router()
        router.reset()

        from automation.telegram import _run_async

        # Turn 1 -> CONFIRMATION
        _run_async(router.handle_input("Telegram pe Harshita ko message bhejo ki hello"))

        # Turn 2 -> Send
        handle_pending_confirmation("haan bhej do")
        assert svc.send_current_draft.call_count == 1

        # Turn 3 (Duplicate confirmation) -> Ignored / cleared
        handled3, msg3 = handle_pending_confirmation("haan bhej do")
        assert svc.send_current_draft.call_count == 1

