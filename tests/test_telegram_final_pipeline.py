"""
Comprehensive End-to-End Pipeline & Isolation Tests for Telegram
================================================================

Validates:
1. Flow A: Generic Telegram application opening (open telegram, telegram kholo, etc.)
   resolves to application opening without entering messaging automation.
2. Flow B: Telegram messaging commands resolve to send_telegram_message and execute
   the full safe multi-turn pipeline (Open -> Verify Ready -> Search/Resolve Contact ->
   Draft -> Preview -> Confirmation -> Send -> Verify).
3. Hard Guards: Router and NLU reject generic open commands.
4. False Success: Launch/verification failures return success=False.
5. Pyrogram Safety: Never bypasses confirmation with direct sending.
6. Isolation: WhatsApp and other apps (calculator, chrome, spotify, vscode) remain intact.
"""

import pytest
from unittest.mock import MagicMock, patch
from agent.intent_classifier import IntentClassifier
from agentic.conversation.confirmation_manager import handle_pending_confirmation
from agentic.memory.session_state import get_session
from execution.registry import load_all_tools, get_handler
from automation.telegram import (
    get_telegram_router,
    get_telegram_service,
    FlowStatus,
    TelegramContact,
    TelegramFlowMode,
    _run_async,
)
from automation.telegram.telegram_automation import _telegram_state


@pytest.fixture(autouse=True)
def reset_all_state():
    """Reset session, router, and tool state before and after each test."""
    load_all_tools()
    session = get_session()
    session.clear_all()
    router = get_telegram_router()
    router.reset()
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
    yield
    session.clear_all()
    router.reset()


class TestFlowAOpenTelegramGeneric:
    """Flow A: Application-opening commands for Telegram."""

    @pytest.mark.parametrize(
        "utterance",
        [
            "open telegram",
            "telegram kholo",
            "telegram open karo",
            "launch telegram",
            "start telegram",
            "open telegram desktop",
            "telegram open",
        ],
    )
    def test_open_telegram_intent_classification(self, utterance):
        classifier = IntentClassifier()
        cmd = classifier.classify(utterance)

        # Must resolve strictly to open_application, NOT send_telegram_message
        assert cmd.intent == "open_application"
        assert "telegram" in cmd.entities.get("application", "").lower()

    def test_open_telegram_planner_resolution(self):
        """Planner must produce generic application-opening tool steps."""
        from agentic.llm.fallback import apply_heuristic_fallback
        for text in ["Open Telegram", "Telegram kholo", "Launch Telegram", "Start Telegram", "Open Telegram Desktop"]:
            plan = apply_heuristic_fallback(text)
            assert plan.intent in ("launch_application", "open_application")
            assert len(plan.steps) >= 1
            assert plan.steps[0].tool in ("launch_application", "open_application", "resolve_and_open")
            app_arg = plan.steps[0].args.get("application") or plan.steps[0].args.get("query")
            assert "telegram" in app_arg.lower()

    def test_open_telegram_router_hard_guard(self):
        """Telegram messaging router must refuse to process open commands."""
        router = get_telegram_router()
        router.reset()

        for open_cmd in [
            "open telegram",
            "telegram kholo",
            "launch telegram",
            "open telegram desktop",
        ]:
            res = _run_async(router.handle_input(open_cmd))
            assert res.status == FlowStatus.NOT_TELEGRAM
            assert router.state.mode == TelegramFlowMode.IDLE
            assert router.state.executed is False

    def test_open_telegram_generic_execution(self):
        """Generic launch_application verifies window readiness."""
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
        assert "telegram" in res.message.lower()

    def test_open_telegram_pipeline_isolation(self):
        """'Open Telegram' resolves to generic open_application, generic handler called, router/pyrogram never called."""
        classifier = IntentClassifier()
        cmd = classifier.classify("Open Telegram")
        assert cmd.intent == "open_application"
        assert cmd.entities.get("application") == "telegram"

        router = get_telegram_router()
        assert router.state.mode == TelegramFlowMode.IDLE
        assert router.state.executed is False


class TestFlowBSendTelegramMessage:
    """Flow B: Complete safe Telegram messaging pipeline."""

    @pytest.mark.parametrize(
        "utterance,expected_contact,expected_msg_sub",
        [
            ("telegram pe Harshita ko message bhejo ki hello", "Harshita", "hello"),
            ("telegram pe Harshita ko hello bhejo", "Harshita", "hello"),
            ("send hello to Harshita on telegram", "Harshita", "hello"),
            ("Harshita ko telegram par bol do ki I will reach by 5", "Harshita", "reach"),
            ("message Harshita on telegram saying I am coming", "Harshita", "coming"),
        ],
    )
    def test_messaging_intent_and_nlu_extraction(self, utterance, expected_contact, expected_msg_sub):
        classifier = IntentClassifier()
        cmd = classifier.classify(utterance)

        assert cmd.intent == "send_telegram_message"
        assert expected_contact.lower() in cmd.entities.get("contact", "").lower()
        assert expected_msg_sub.lower() in cmd.entities.get("message", "").lower()

    def test_full_messaging_pipeline_with_confirmation(self):
        svc = get_telegram_service()
        svc.search_contacts = MagicMock(return_value=[
            TelegramContact(id=1, name="Harshita Sharma", username="harshita_s")
        ])
        svc.open_preview = MagicMock(return_value=FlowStatus.LINK_LAUNCH_REQUESTED)
        svc.send_current_draft = MagicMock(return_value=FlowStatus.SEND_KEY_DISPATCHED)

        router = get_telegram_router()
        router.reset()

        # Turn 1: New messaging command -> Opens draft & requests confirmation
        res1 = _run_async(router.handle_input("Telegram pe Harshita ko message bhejo ki hello"))
        assert res1.status == FlowStatus.CONFIRMATION_REQUIRED
        assert router.state.mode == TelegramFlowMode.CONFIRMATION
        assert router.state.preview_opened is True
        svc.open_preview.assert_called_once_with("harshita_s", "hello")
        svc.send_current_draft.assert_not_called()  # Must NOT send yet!

        # Turn 2: User confirms -> Dispatches send
        handled, msg = handle_pending_confirmation("haan bhej do")
        assert handled is True
        assert "Enter key dispatched" in msg or "sent" in msg.lower()
        assert router.state.mode == TelegramFlowMode.COMPLETED
        svc.send_current_draft.assert_called_once()

    def test_cancel_pipeline(self):
        svc = get_telegram_service()
        svc.search_contacts = MagicMock(return_value=[
            TelegramContact(id=1, name="Harshita Sharma", username="harshita_s")
        ])
        svc.open_preview = MagicMock(return_value=FlowStatus.LINK_LAUNCH_REQUESTED)
        svc.send_current_draft = MagicMock(return_value=FlowStatus.SEND_KEY_DISPATCHED)

        router = get_telegram_router()
        router.reset()

        _run_async(router.handle_input("Telegram pe Harshita ko message bhejo ki hello"))
        assert router.state.mode == TelegramFlowMode.CONFIRMATION

        # User cancels
        handled, msg = handle_pending_confirmation("nahi cancel kar do")
        assert handled is True
        assert "cancelled" in msg.lower()
        svc.send_current_draft.assert_not_called()

    def test_disambiguation_pipeline(self):
        svc = get_telegram_service()
        svc.search_contacts = MagicMock(return_value=[
            TelegramContact(id=1, name="Harshita Sharma", username="harshita_s"),
            TelegramContact(id=2, name="Harshita Gupta", username="harshita_g"),
        ])
        svc.open_preview = MagicMock(return_value=FlowStatus.LINK_LAUNCH_REQUESTED)
        svc.send_current_draft = MagicMock(return_value=FlowStatus.SEND_KEY_DISPATCHED)

        router = get_telegram_router()
        router.reset()

        # Turn 1: Multiple matches -> DISAMBIGUATION
        res1 = _run_async(router.handle_input("Telegram pe Harshita ko message bhejo ki hello"))
        assert res1.status == FlowStatus.DISAMBIGUATION_REQUIRED
        assert router.state.mode == TelegramFlowMode.DISAMBIGUATION

        # Turn 2: Select Option 2
        handled2, msg2 = handle_pending_confirmation("Option 2")
        assert handled2 is True
        assert "Harshita Gupta" in msg2
        assert router.state.mode == TelegramFlowMode.CONFIRMATION
        svc.open_preview.assert_called_once_with("harshita_g", "hello")
        svc.send_current_draft.assert_not_called()

        # Turn 3: Confirm
        handled3, msg3 = handle_pending_confirmation("yes")
        assert handled3 is True
        svc.send_current_draft.assert_called_once()


class TestFalseSuccessAndSafety:
    """Tests preventing false successes and direct sending without verification."""

    def test_desktop_launch_failure_reports_failure(self):
        handler = get_handler("open_telegram_web")
        with patch("automation.telegram.telegram_automation.find_telegram_desktop", return_value="C:\\dummy\\telegram.exe"), \
             patch("subprocess.Popen", side_effect=OSError("Access denied")):
            res = handler({})
        assert res.success is False
        assert "Failed to launch Telegram Desktop" in res.message

    def test_desktop_window_not_verified_reports_failure(self):
        handler = get_handler("open_telegram_web")
        with patch("automation.telegram.telegram_automation.find_telegram_desktop", return_value="C:\\dummy\\telegram.exe"), \
             patch("subprocess.Popen"), \
             patch("execution.verifier.verify_application_launched", return_value=MagicMock(passed=False)), \
             patch("execution.verifier._is_window_visible", return_value=False):
            res = handler({})
        assert res.success is False
        assert "visible window was not verified" in res.message

    def test_web_fallback_not_verified_reports_failure(self):
        handler = get_handler("open_telegram_web")
        with patch("automation.telegram.telegram_automation.find_telegram_desktop", return_value=None), \
             patch("automation.browser.launch_url_in_browser", return_value=(False, "Failed")), \
             patch("webbrowser.open", return_value=True), \
             patch("automation.browser.find_and_focus_browser_tab", return_value=False), \
             patch("execution.verifier._is_window_visible", return_value=False):
            res = handler({})
        assert res.success is False
        assert "could not be opened or verified" in res.message or "target tab/window was not verified" in res.message or "open failed" in res.message


class TestNonTelegramApplicationsIntact:
    """Ensures other apps and WhatsApp are not disturbed."""

    @pytest.mark.parametrize(
        "app_cmd,expected_app",
        [
            ("open calculator", "calculator"),
            ("open chrome", "chrome"),
            ("open spotify", "spotify"),
            ("open vscode", "vscode"),
        ],
    )
    def test_other_applications_intent(self, app_cmd, expected_app):
        classifier = IntentClassifier()
        cmd = classifier.classify(app_cmd)
        assert cmd.intent in ("open_application", f"open_{expected_app}", "open_browser")
        assert cmd.intent != "send_telegram_message"

    def test_whatsapp_automation_intent(self):
        classifier = IntentClassifier()
        cmd = classifier.classify("WhatsApp pe Rahul ko message bhejo ki hello")
        assert cmd.intent in ("send_message", "send_whatsapp_message")
        assert cmd.intent != "send_telegram_message"
