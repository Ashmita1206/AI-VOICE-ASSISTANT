"""
Unit Tests for Telegram NLU Parsing
====================================

Tests Hindi, Hinglish, English commands, username extraction, missing info,
disambiguation options, and positive/negative confirmation phrases.
"""

import pytest
from automation.telegram.models import (
    ConfirmationResult,
    DisambiguationResult,
    NewCommandResult,
    NLUState,
)
from automation.telegram.nlu import parse_telegram_input, _regex_fallback_parse


class TestTelegramNLUNewCommand:
    """Tests for NEW_COMMAND state parsing."""

    def test_hinglish_command(self):
        cmd = "Telegram pe Harshita ko message bhejo ki main 10 min me aa rhi hu"
        res = parse_telegram_input(NLUState.NEW_COMMAND.value, cmd)
        assert isinstance(res, NewCommandResult)
        assert res.app == "telegram"
        assert res.recipient_query.lower() == "harshita"
        assert "10 min" in res.message_text

    def test_hinglish_bol_do_command(self):
        cmd = "Telegram par Rahul ko bol do meeting 5 baje hai"
        res = parse_telegram_input(NLUState.NEW_COMMAND.value, cmd)
        assert isinstance(res, NewCommandResult)
        assert res.app == "telegram"
        assert res.recipient_query.lower() == "rahul"
        assert "meeting 5 baje" in res.message_text

    def test_english_command(self):
        cmd = "Send a telegram to Rahul saying happy birthday"
        res = parse_telegram_input(NLUState.NEW_COMMAND.value, cmd)
        assert isinstance(res, NewCommandResult)
        assert res.app == "telegram"
        assert res.recipient_query.lower() == "rahul"
        assert res.message_text.lower() == "happy birthday"

    def test_english_telegram_message_to_saying(self):
        cmd = "Send a telegram message to Harshita saying hello."
        res = parse_telegram_input(NLUState.NEW_COMMAND.value, cmd)
        assert isinstance(res, NewCommandResult)
        assert res.app == "telegram"
        assert res.recipient_query.lower() == "harshita"
        assert res.message_text.lower() == "hello"

    def test_english_hello_message_to_on_telegram(self):
        cmd = "Send a hello message to Harshita on Telegram"
        res = parse_telegram_input(NLUState.NEW_COMMAND.value, cmd)
        assert isinstance(res, NewCommandResult)
        assert res.app == "telegram"
        assert res.recipient_query.lower() == "harshita"
        assert res.message_text.lower() == "hello"

    def test_english_send_hello_to_on_telegram(self):
        cmd = "Send hello to Harshita on Telegram."
        res = parse_telegram_input(NLUState.NEW_COMMAND.value, cmd)
        assert isinstance(res, NewCommandResult)
        assert res.app == "telegram"
        assert res.recipient_query.lower() == "harshita"
        assert res.message_text.lower() == "hello"

    def test_english_tell_command(self):
        cmd = "Tell Aman on Telegram that I am running late"
        res = parse_telegram_input(NLUState.NEW_COMMAND.value, cmd)
        assert isinstance(res, NewCommandResult)
        assert res.app == "telegram"
        assert res.recipient_query.lower() == "aman"
        assert "running late" in res.message_text

    def test_username_command(self):
        cmd = "Message @rahul_99 on Telegram saying call me"
        res = parse_telegram_input(NLUState.NEW_COMMAND.value, cmd)
        assert isinstance(res, NewCommandResult)
        assert res.app == "telegram"
        assert res.recipient_query == "rahul_99"
        assert res.message_text.lower() == "call me"

    def test_send_karo_command(self):
        cmd = "Telegram pe Harshita Sharma ko send karo I'll reach soon"
        res = parse_telegram_input(NLUState.NEW_COMMAND.value, cmd)
        assert isinstance(res, NewCommandResult)
        assert res.app == "telegram"
        assert res.recipient_query.lower() == "harshita sharma"
        assert "reach soon" in res.message_text

    def test_missing_recipient(self):
        cmd = "Telegram pe hello send kar do"
        res = parse_telegram_input(NLUState.NEW_COMMAND.value, cmd)
        assert isinstance(res, NewCommandResult)
        assert res.app == "telegram"
        # Recipient not identifiable from regex pattern
        assert res.recipient_query == ""

    def test_missing_message(self):
        cmd = "Telegram pe Harshita ko message bhejo"
        res = parse_telegram_input(NLUState.NEW_COMMAND.value, cmd)
        assert isinstance(res, NewCommandResult)
        assert res.app == "telegram"
        # Message not present
        assert res.message_text == ""


class TestTelegramNLUDisambiguation:
    """Tests for DISAMBIGUATION state parsing."""

    def test_option_number(self):
        res = parse_telegram_input(NLUState.DISAMBIGUATION.value, "option 2")
        assert isinstance(res, DisambiguationResult)
        assert res.selected_option == 2

    def test_first_one(self):
        res = parse_telegram_input(NLUState.DISAMBIGUATION.value, "first one")
        assert isinstance(res, DisambiguationResult)
        assert res.selected_option == 1

    def test_second_one(self):
        res = parse_telegram_input(NLUState.DISAMBIGUATION.value, "second")
        assert isinstance(res, DisambiguationResult)
        assert res.selected_option == 2

    def test_pehla_wala(self):
        res = parse_telegram_input(NLUState.DISAMBIGUATION.value, "pehla wala")
        assert isinstance(res, DisambiguationResult)
        assert res.selected_option == 1

    def test_dusra_wala(self):
        res = parse_telegram_input(NLUState.DISAMBIGUATION.value, "dusra wala")
        assert isinstance(res, DisambiguationResult)
        assert res.selected_option == 2

    def test_spoken_contact_name(self):
        res = parse_telegram_input(NLUState.DISAMBIGUATION.value, "Harshita Sharma")
        assert isinstance(res, DisambiguationResult)
        assert res.selected_option is None
        assert res.selected_name == "Harshita Sharma"


class TestTelegramNLUConfirmation:
    """Tests for CONFIRMATION state parsing."""

    @pytest.mark.parametrize(
        "phrase",
        [
            "yes",
            "yeah",
            "yep",
            "haan",
            "ha",
            "bhej do",
            "send it",
            "kar do",
            "yes send it",
            "haan bhej do",
            "confirm",
            "go ahead",
        ],
    )
    def test_positive_confirmations(self, phrase):
        res = parse_telegram_input(NLUState.CONFIRMATION.value, phrase)
        assert isinstance(res, ConfirmationResult)
        assert res.confirmed is True

    @pytest.mark.parametrize(
        "phrase",
        [
            "no",
            "nahi",
            "mat bhejo",
            "cancel",
            "cancel it",
            "don't send",
            "rehne do",
            "stop",
        ],
    )
    def test_negative_confirmations(self, phrase):
        res = parse_telegram_input(NLUState.CONFIRMATION.value, phrase)
        assert isinstance(res, ConfirmationResult)
        assert res.confirmed is False


class TestTelegramNLUWithMockLLM:
    """Tests for LLM-backed NLU parsing path."""

    def test_llm_parsing_success(self):
        mock_llm_json = '{"state":"NEW_COMMAND","app":"telegram","recipient_query":"Harshita","message_text":"main aa rahi hu","raw_command":"test"}'

        def mock_llm(prompt, user_msg):
            return mock_llm_json

        res = parse_telegram_input(NLUState.NEW_COMMAND.value, "test text", llm_fn=mock_llm)
        assert isinstance(res, NewCommandResult)
        assert res.recipient_query == "Harshita"

    def test_llm_code_fence_cleaning(self):
        mock_llm_json = '```json\n{"state":"CONFIRMATION","confirmed":true}\n```'

        def mock_llm(prompt, user_msg):
            return mock_llm_json

        res = parse_telegram_input(NLUState.CONFIRMATION.value, "haan bhej do", llm_fn=mock_llm)
        assert isinstance(res, ConfirmationResult)
        assert res.confirmed is True


class TestTelegramNLURegressionSuite:
    """Explicit regression tests for master prompt requirements."""

    def test_in_telegram_hello_harshita(self):
        res = parse_telegram_input("NEW_COMMAND", "Send a hello message to Harshita in Telegram.")
        assert res.recipient_query == "Harshita"
        assert res.message_text == "hello"

    def test_on_telegram_good_morning_neeraj(self):
        res = parse_telegram_input("NEW_COMMAND", "Send a good morning message to Neeraj on Telegram.")
        assert res.recipient_query == "Neeraj"
        assert res.message_text == "good morning"

    def test_on_telegram_bye_rahul(self):
        res = parse_telegram_input("NEW_COMMAND", "Send bye to Rahul on Telegram.")
        assert res.recipient_query == "Rahul"
        assert res.message_text == "bye"

    def test_open_telegram_only(self):
        from agent.intent_classifier import IntentClassifier
        classifier = IntentClassifier()
        cmd = classifier.classify("Open Telegram.")
        assert cmd.intent in ("open_application", "open_telegram")

    def test_missing_contact_does_not_use_placeholder(self):
        from agentic.llm.fallback import apply_heuristic_fallback
        plan = apply_heuristic_fallback("Send hello on Telegram.")
        assert len(plan.steps) == 0 or plan.confidence == 0.0
        for step in plan.steps:
            assert step.args.get("contact") not in ("contact", "recipient", "{name}", "{contact}")

    def test_planner_never_outputs_literal_contact_placeholder(self):
        from agentic.llm.fallback import apply_heuristic_fallback
        for text in [
            "Send a hello message to Harshita in Telegram.",
            "Send a good morning message to Neeraj on Telegram.",
            "Send bye to Rahul on Telegram.",
        ]:
            plan = apply_heuristic_fallback(text)
            for step in plan.steps:
                assert step.args.get("contact") not in ("contact", "recipient", "{name}", "{contact}")

    def test_open_telegram_web_mode_no_desktop_process_check(self):
        from execution.registry import get_handler
        from unittest.mock import patch
        handler = get_handler("open_telegram_web")
        with patch("automation.browser.find_and_focus_browser_tab", return_value=True), \
             patch("execution.verifier._is_window_visible", return_value=True):
            res = handler({})
        assert res.success is True
        assert res.data["client"] in ("web", "telegram_web")

    def test_planner_does_not_contain_verify_telegram_web_logged_in(self):
        from agentic.llm.fallback import apply_heuristic_fallback
        plan = apply_heuristic_fallback("Send a hello message to Harshita on Telegram.")
        step_tools = [s.tool for s in plan.steps]
        assert "verify_telegram_web_logged_in" not in step_tools
        assert step_tools[0] == "open_telegram"
        assert step_tools[1] == "search_telegram_contact"

