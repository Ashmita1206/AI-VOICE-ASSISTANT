"""Non-sending integration coverage for the decomposed Telegram SSE flow."""

import json

import pytest
from flask import Flask

from agentic.memory.pending_action import PendingActionManager
from agentic.memory.session_state import get_session
from automation.telegram.telegram_automation import (
    _parse_search_candidate,
    _telegram_state,
    handle_send_telegram_message,
    reset_telegram_state,
)
from execution.registry import _REGISTRY, load_all_tools
from execution.schemas import ExecutionResult
from execution.verifier import VerifyResult
from web.stream_service import _sse, run_confirmation_stream


def _payloads(events):
    payloads = []
    for event in events:
        for line in event.splitlines():
            if line.startswith("data:"):
                payloads.append(json.loads(line[5:].strip()))
    return payloads


def _confirmation(payloads):
    event = next(
        payload
        for payload in payloads
        if payload.get("stage") == "done"
        and payload.get("status") == "requires_confirmation"
    )
    return event["data"]["confirmation"]


@pytest.fixture(autouse=True)
def _clean_pending_state():
    load_all_tools()
    PendingActionManager.clear()
    get_session().clear_all()
    reset_telegram_state()
    yield
    PendingActionManager.clear()
    get_session().clear_all()


def test_three_phase_confirmation_resumes_remaining_plan_once(monkeypatch):
    calls = []
    send_count = {"value": 0}

    def success(tool, data=None):
        def handler(args):
            calls.append(tool)
            return ExecutionResult(success=True, tool=tool, message=f"{tool} ok", data=data)
        return handler

    def contact_gate(args):
        calls.append("verify_telegram_contact")
        return ExecutionResult(
            success=True,
            tool="verify_telegram_contact",
            requires_confirmation=True,
            message="Confirm Harshita",
            data={
                "confirmation_type": "telegram_contact_confirmation",
                "contact": "Harshita",
            },
        )

    def draft_gate(args):
        calls.append("type_telegram_message")
        return ExecutionResult(
            success=True,
            tool="type_telegram_message",
            requires_confirmation=True,
            message="Send hello to Harshita?",
            data={
                "confirmation_type": "telegram_send_confirmation",
                "contact": "Harshita",
                "message": "hello",
                "message_prompt": "Send 'hello' to Harshita?",
            },
        )

    def send(args):
        calls.append("send_telegram_message")
        send_count["value"] += 1
        return ExecutionResult(success=True, tool="send_telegram_message", message="sent once")

    handlers = {
        "open_telegram": success("open_telegram"),
        "search_telegram_contact": success("search_telegram_contact"),
        "verify_telegram_contact": contact_gate,
        "open_telegram_chat": success("open_telegram_chat"),
        "verify_telegram_chat_header": success("verify_telegram_chat_header"),
        "focus_telegram_composer": success("focus_telegram_composer"),
        "type_telegram_message": draft_gate,
        "send_telegram_message": send,
        "verify_telegram_message_sent": success("verify_telegram_message_sent"),
        "close_telegram_tab": success("close_telegram_tab"),
    }
    for name, handler in handlers.items():
        monkeypatch.setitem(_REGISTRY, name, handler)

    monkeypatch.setattr(
        "execution.executor.dispatch_verify",
        lambda tool, args, result: VerifyResult(True, f"{tool} verified"),
    )
    monkeypatch.setattr("web.stream_service.generate_response", lambda results: "completed")
    monkeypatch.setattr("web.stream_service._generate_tts_file", lambda text: None)
    monkeypatch.setattr("web.stream_service.save_session", lambda result: None)

    steps = [
        {"tool": "open_telegram", "args": {}},
        {"tool": "search_telegram_contact", "args": {"contact": "Harshita"}},
        {"tool": "verify_telegram_contact", "args": {"contact": "Harshita"}},
        {"tool": "open_telegram_chat", "args": {"contact": "Harshita"}},
        {"tool": "verify_telegram_chat_header", "args": {"contact": "Harshita"}},
        {"tool": "focus_telegram_composer", "args": {}},
        {"tool": "type_telegram_message", "args": {"message": "hello"}},
        {"tool": "send_telegram_message", "args": {"contact": "Harshita", "message": "hello"}},
        {"tool": "verify_telegram_message_sent", "args": {"message": "hello"}},
        {"tool": "close_telegram_tab", "args": {}},
    ]
    plan_id = PendingActionManager.save({
        "intent": "send_telegram_message",
        "thought": "Send hello to Harshita",
        "confirmation_type": "execution_plan",
        "phase": "execution_plan",
        "steps": steps,
    })

    first_payloads = _payloads(list(run_confirmation_stream(plan_id)))
    contact_confirmation = _confirmation(first_payloads)
    assert contact_confirmation["confirmation_type"] == "telegram_contact_confirmation"
    assert calls == ["open_telegram", "search_telegram_contact", "verify_telegram_contact"]
    assert send_count["value"] == 0

    second_payloads = _payloads(list(run_confirmation_stream(contact_confirmation["id"])))
    send_confirmation = _confirmation(second_payloads)
    assert send_confirmation["confirmation_type"] == "telegram_send_confirmation"
    assert calls[-4:] == [
        "open_telegram_chat",
        "verify_telegram_chat_header",
        "focus_telegram_composer",
        "type_telegram_message",
    ]
    assert _telegram_state["contact_confirmed"] is True
    assert send_count["value"] == 0

    final_payloads = _payloads(list(run_confirmation_stream(send_confirmation["id"])))
    assert any(
        payload.get("stage") == "done" and payload.get("status") == "success"
        for payload in final_payloads
    )
    assert calls[-3:] == [
        "send_telegram_message",
        "verify_telegram_message_sent",
        "close_telegram_tab",
    ]
    assert _telegram_state["send_confirmed"] is True
    assert send_count["value"] == 1

    replay_payloads = _payloads(list(run_confirmation_stream(send_confirmation["id"])))
    assert any(
        payload.get("stage") == "done" and payload.get("status") == "error"
        for payload in replay_payloads
    )
    assert send_count["value"] == 1


def test_duplicate_send_attempt_is_blocked_before_keyboard_dispatch():
    _telegram_state["send_attempted"] = True
    result = handle_send_telegram_message({"contact": "Harshita", "message": "hello"})
    assert result.success is True
    assert result.data["already_dispatched"] is True


@pytest.mark.parametrize(
    "accessible_name, expected",
    [
        ("Harshita, Pinned, GIF, Received, yesterday", ("Harshita", "user")),
        ("Shrishti Harshita Friend", ("Shrishti Harshita Friend", "user")),
        ("Channel, Harshita Goyal AIR 2 UPSC", ("Harshita Goyal AIR 2 UPSC", "channel")),
    ],
)
def test_real_search_row_parser(accessible_name, expected):
    assert _parse_search_candidate(accessible_name) == expected


def test_utf8_sse_routes_stream_unicode_without_console_workarounds(monkeypatch):
    from web import routes

    app = Flask(__name__)
    app.register_blueprint(routes.api)
    unicode_event = _sse("execution", "running", message="▶ Telegram ready — café")
    monkeypatch.setattr(routes, "run_pipeline_stream", lambda **kwargs: iter([unicode_event]))
    monkeypatch.setattr(routes, "run_confirmation_stream", lambda *args, **kwargs: iter([unicode_event]))

    client = app.test_client()
    transcribe = client.post("/transcribe_stream", data={"text": "hello"})
    assert transcribe.status_code == 200
    assert transcribe.content_type == "text/event-stream; charset=utf-8"
    assert "▶ Telegram ready — café" in transcribe.data.decode("utf-8")

    confirm = client.post(
        "/confirm?stream=true",
        json={"confirmation_id": "test-id", "decision": "proceed"},
        headers={"Accept": "text/event-stream"},
    )
    assert confirm.status_code == 200
    assert confirm.content_type == "text/event-stream; charset=utf-8"
    assert "▶ Telegram ready — café" in confirm.data.decode("utf-8")
