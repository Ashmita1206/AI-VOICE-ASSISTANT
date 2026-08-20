"""
Telegram NLU Parser
===================

State-aware Natural Language Understanding for Telegram messaging commands.

Supports three conversation states:
- ``NEW_COMMAND``    — extract app, recipient, message from voice input
- ``DISAMBIGUATION`` — resolve which contact the user selected
- ``CONFIRMATION``   — detect yes/no confirmation intent

Output is always **raw JSON** — no markdown, no explanations.

Includes:
- ``TELEGRAM_NLU_SYSTEM_PROMPT`` for LLM-based parsing
- ``parse_telegram_input()`` entry point (LLM with regex fallback)
- Deterministic regex fallback for testing without an LLM endpoint
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, Optional, Union

from automation.telegram.models import (
    ConfirmationResult,
    DisambiguationResult,
    NewCommandResult,
    NLUState,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM System Prompt (Sections 6–14 of the master prompt)
# ---------------------------------------------------------------------------

TELEGRAM_NLU_SYSTEM_PROMPT = r"""You are a strict JSON-only NLU parser for a voice assistant's Telegram messaging feature.

You receive two inputs:
  current_state  — one of: NEW_COMMAND, DISAMBIGUATION, CONFIRMATION
  user_text      — the transcribed voice input

You MUST use the supplied current_state. Do NOT reinterpret every input as a new command.

## Rules
- Output RAW JSON ONLY.  No markdown.  No ```json.  No explanations.  No prefix/suffix text.
- Output must always be machine-parseable JSON.
- Preserve the user's intended message text.  Do NOT rewrite it grammatically.
- Do NOT invent a recipient if none is present.
- Do NOT invent message content if none is present.
- For usernames starting with @, normalise recipient_query by removing the @ prefix.

## NEW_COMMAND state
When current_state = NEW_COMMAND, extract the messaging intent:
{
  "state": "NEW_COMMAND",
  "app": "<telegram|gmail|whatsapp|unknown>",
  "recipient_query": "<extracted contact name or username, empty string if missing>",
  "message_text": "<extracted message body, empty string if missing>",
  "raw_command": "<original full user text>"
}

Understand commands in English, Hindi, and Hinglish such as:
- "Telegram pe Harshita ko message bhejo ki main aa rahi hu"
- "Telegram par Rahul ko bol do meeting 5 baje hai"
- "Send a telegram to Rahul saying happy birthday"
- "Telegram Rahul happy birthday bol do"
- "Message @rahul_99 on Telegram saying call me"
- "Tell Aman on Telegram that I am running late"

## DISAMBIGUATION state
When current_state = DISAMBIGUATION, the user is selecting from presented options:
{
  "state": "DISAMBIGUATION",
  "selected_option": <1-based integer or null>,
  "selected_name": <string or null>
}

Recognise: "option 1", "first one", "second", "number 3", "pehla wala", "dusra wala", "third one", or a spoken name.

## CONFIRMATION state
When current_state = CONFIRMATION, detect positive or negative intent:
{
  "state": "CONFIRMATION",
  "confirmed": <true|false>
}

Positive: yes, yeah, yep, haan, ha, bhej do, send it, kar do, yes send it, haan bhej do, confirm, go ahead
Negative: no, nahi, mat bhejo, cancel, cancel it, don't send, rehne do, stop

## Few-shot examples

Input: state=NEW_COMMAND, voice="Telegram pe Harshita ko message bhejo ki main 10 min me aa rhi hu"
Output: {"state":"NEW_COMMAND","app":"telegram","recipient_query":"Harshita","message_text":"main 10 min me aa rhi hu","raw_command":"Telegram pe Harshita ko message bhejo ki main 10 min me aa rhi hu"}

Input: state=NEW_COMMAND, voice="Send a telegram to @rahul_99 saying happy birthday bro"
Output: {"state":"NEW_COMMAND","app":"telegram","recipient_query":"rahul_99","message_text":"happy birthday bro","raw_command":"Send a telegram to @rahul_99 saying happy birthday bro"}

Input: state=DISAMBIGUATION, voice="option 2"
Output: {"state":"DISAMBIGUATION","selected_option":2,"selected_name":null}

Input: state=DISAMBIGUATION, voice="Harshita Sharma"
Output: {"state":"DISAMBIGUATION","selected_option":null,"selected_name":"Harshita Sharma"}

Input: state=CONFIRMATION, voice="haan bhej do"
Output: {"state":"CONFIRMATION","confirmed":true}

Input: state=CONFIRMATION, voice="nahi cancel kar do"
Output: {"state":"CONFIRMATION","confirmed":false}
"""


# ---------------------------------------------------------------------------
# Positive / Negative phrase patterns (Hindi + Hinglish + English)
# ---------------------------------------------------------------------------

_POSITIVE_PATTERNS = re.compile(
    r"^("
    r"yes|yeah|yep|yup|sure|okay|ok"
    r"|haan|ha|haa|han"
    r"|bhej\s*do|send\s*it|kar\s*do|kardo|bhejdo"
    r"|yes\s+send\s+it|haan\s+bhej\s*do"
    r"|confirm|go\s*ahead|proceed|do\s*it"
    r")$",
    re.IGNORECASE,
)

_NEGATIVE_PATTERNS = re.compile(
    r"^("
    r"no|nope|nah|don'?t\s*send"
    r"|nahi|nhi|nahin|mat\s*bhejo|mat\s*bhej"
    r"|cancel|cancel\s*it|cancel\s*kar\s*do"
    r"|rehne\s*do|ruk|stop|abort"
    r")$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Disambiguation option patterns
# ---------------------------------------------------------------------------

_OPTION_NUMBER_PATTERNS = [
    # "option 2", "number 3", "#1"
    re.compile(r"(?:option|number|#)\s*(\d+)", re.IGNORECASE),
    # "first one", "second one", "third one"
    re.compile(r"(first|second|third|fourth|fifth)\s*(?:one|wala)?", re.IGNORECASE),
    # "pehla wala", "dusra wala", "teesra wala"
    re.compile(r"(pehla|dusra|teesra|chautha|panchwa)\s*(?:wala)?", re.IGNORECASE),
    # bare number "1", "2", "3"
    re.compile(r"^(\d+)$"),
]

_ORDINAL_MAP = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "pehla": 1, "dusra": 2, "teesra": 3, "chautha": 4, "panchwa": 5,
}


# ---------------------------------------------------------------------------
# Telegram command extraction patterns (regex fallback)
# ---------------------------------------------------------------------------

# Pattern 1: "Telegram pe/par <name> ko message/bol/send bhejo/karo/do ki <message>"
_HINGLISH_CMD = re.compile(
    r"telegram\s+(?:pe|par|p)\s+"
    r"(.+?)\s+"
    r"(?:ko\s+)(?:message\s+)?(?:bhej(?:o|do)?|send\s*(?:kar(?:o|do)?)?|bol\s*(?:do|o)?)\s+"
    r"(?:ki\s+|that\s+)?(.+)",
    re.IGNORECASE,
)

# Pattern 1b: "Telegram pe <name> ko send karo <message>" or "Telegram pe <name> send karo <message>"
_HINGLISH_SEND_CMD = re.compile(
    r"telegram\s+(?:pe|par|p)\s+"
    r"(.+?)\s+"
    r"(?:ko\s+)?send\s+(?:karo|do|kar\s+do)\s+"
    r"(.+)",
    re.IGNORECASE,
)

# Pattern 1c: "Telegram pe/par <name> ko <message> bhejo/bol do/send karo" (message before verb)
_HINGLISH_MSG_BEFORE_VERB_CMD = re.compile(
    r"telegram\s+(?:pe|par|p)\s+"
    r"(.+?)\s+"
    r"(?:ko\s+)(.+?)\s+"
    r"(?:bhej(?:o|do)?|send\s*(?:kar(?:o|do)?)?|bol\s*(?:do|o)?)$",
    re.IGNORECASE,
)

# Pattern 1d: "<name> ko telegram pe/par bol do/message bhejo ki <message>"
_HINGLISH_RECIPIENT_FIRST_CMD = re.compile(
    r"(.+?)\s+ko\s+telegram\s+(?:pe|par|p)\s+"
    r"(?:bol\s*(?:do|o)?|bhej(?:o|do)?|message\s+(?:bhej(?:o|do)?|kar(?:o|do)?))\s+"
    r"(?:ki\s+|that\s+)?(.+)",
    re.IGNORECASE,
)

# Pattern 1e: "<name> ko telegram pe/par <message> bol do/bhejo"
_HINGLISH_RECIPIENT_FIRST_MSG_CMD = re.compile(
    r"(.+?)\s+ko\s+telegram\s+(?:pe|par|p)\s+"
    r"(.+?)\s+"
    r"(?:bol\s*(?:do|o)?|bhej(?:o|do)?|send\s*(?:kar(?:o|do)?)?)$",
    re.IGNORECASE,
)

# Pattern 2: "Send a telegram to <name> saying/that <message>"
_ENGLISH_CMD = re.compile(
    r"(?:send\s+(?:a\s+)?(?:telegram|message|telegram\s+message)\s+(?:to|(?:on|in)\s+telegram\s+to)\s+)"
    r"(@?\S+?(?:\s+\S+?)*?)\s+"
    r"(?:saying|that)\s+(.+)",
    re.IGNORECASE,
)

# Pattern 2b: "Send hello to Harshita on/in Telegram" or "Send a hello message to Harshita in Telegram"
_ENGLISH_SEND_TO_CMD = re.compile(
    r"send\s+(?:a\s+)?(.+?)\s+(?:message\s+)?to\s+(.+?)\s+(?:on|in)\s+telegram",
    re.IGNORECASE,
)

# Pattern 3: "Tell <name> on/in Telegram that <message>"
_TELL_CMD = re.compile(
    r"tell\s+"
    r"(.+?)\s+"
    r"(?:on|in)\s+telegram\s+"
    r"(?:that\s+|ki\s+)?(.+)",
    re.IGNORECASE,
)

# Pattern 4: "Message @username/name on/in Telegram saying <message>"
_MSG_USERNAME_CMD = re.compile(
    r"message\s+(@?\S+?(?:\s+\S+?)*?)\s+"
    r"(?:on|in)?\s*telegram\s+"
    r"(?:saying|that|ki)\s+(.+)",
    re.IGNORECASE,
)

# Pattern 5: "Telegram <name> <message> bol/bhej do"
_SHORT_HINGLISH_CMD = re.compile(
    r"telegram\s+"
    r"(@?\S+(?:\s+\S+)?)\s+"
    r"(.+?)\s+"
    r"(?:bol\s*do|bhej\s*do)",
    re.IGNORECASE,
)


# Fallback: detect if "telegram" is mentioned at all
_HAS_TELEGRAM = re.compile(r"\btelegram\b", re.IGNORECASE)


def _strip_at(name: str) -> str:
    """Remove leading @ from a username query."""
    return name.lstrip("@").strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_telegram_input(
    current_state: str,
    user_text: str,
    llm_fn: Optional[Callable[[str, str], str]] = None,
) -> Union[NewCommandResult, DisambiguationResult, ConfirmationResult]:
    """Parse user voice input according to the current conversation state.

    Parameters
    ----------
    current_state:
        One of ``"NEW_COMMAND"``, ``"DISAMBIGUATION"``, ``"CONFIRMATION"``.
    user_text:
        The raw transcribed voice text.
    llm_fn:
        Optional LLM callable ``(system_prompt, user_message) -> json_string``.
        If provided, the LLM is tried first; regex fallback is used on failure.
        If ``None``, the regex fallback is used directly.

    Returns
    -------
    One of ``NewCommandResult``, ``DisambiguationResult``, ``ConfirmationResult``.
    """
    state = current_state.upper().strip()
    text = user_text.strip()

    # Try LLM first if available
    if llm_fn is not None:
        try:
            result = _parse_with_llm(state, text, llm_fn)
            if result is not None:
                return result
        except Exception as exc:
            logger.warning("LLM NLU parse failed, falling back to regex: %s", exc)

    # Deterministic regex fallback
    return _regex_fallback_parse(state, text)


# ---------------------------------------------------------------------------
# LLM Path
# ---------------------------------------------------------------------------

def _parse_with_llm(
    state: str, text: str, llm_fn: Callable[[str, str], str]
) -> Optional[Union[NewCommandResult, DisambiguationResult, ConfirmationResult]]:
    """Attempt to parse using the LLM callable."""
    user_message = f"state: {state}\nvoice: {text}"
    raw_response = llm_fn(TELEGRAM_NLU_SYSTEM_PROMPT, user_message)

    # Strip markdown code fences if the LLM misbehaves
    cleaned = raw_response.strip()
    if cleaned.startswith("```"):
        # Remove opening fence
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1:]
        # Remove closing fence
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].rstrip()

    data: Dict[str, Any] = json.loads(cleaned)
    return _dict_to_result(data)


def _dict_to_result(
    data: Dict[str, Any],
) -> Union[NewCommandResult, DisambiguationResult, ConfirmationResult]:
    """Convert a parsed JSON dict into the appropriate result dataclass."""
    state_val = data.get("state", "").upper()

    if state_val == NLUState.NEW_COMMAND.value:
        recipient = data.get("recipient_query", "")
        return NewCommandResult(
            state=NLUState.NEW_COMMAND.value,
            app=data.get("app", "unknown").lower(),
            recipient_query=_strip_at(recipient) if recipient else "",
            message_text=data.get("message_text", ""),
            raw_command=data.get("raw_command", ""),
        )

    if state_val == NLUState.DISAMBIGUATION.value:
        return DisambiguationResult(
            state=NLUState.DISAMBIGUATION.value,
            selected_option=data.get("selected_option"),
            selected_name=data.get("selected_name"),
        )

    if state_val == NLUState.CONFIRMATION.value:
        return ConfirmationResult(
            state=NLUState.CONFIRMATION.value,
            confirmed=bool(data.get("confirmed", False)),
        )

    raise ValueError(f"Unknown NLU state in response: {state_val}")


# ---------------------------------------------------------------------------
# Regex Fallback Parser
# ---------------------------------------------------------------------------

def _regex_fallback_parse(
    state: str, text: str
) -> Union[NewCommandResult, DisambiguationResult, ConfirmationResult]:
    """Deterministic regex-based parser — used when no LLM is available."""
    if state == NLUState.NEW_COMMAND.value:
        return _parse_new_command(text)
    if state == NLUState.DISAMBIGUATION.value:
        return _parse_disambiguation(text)
    if state == NLUState.CONFIRMATION.value:
        return _parse_confirmation(text)

    # Default: treat as new command
    logger.warning("Unknown NLU state '%s', treating as NEW_COMMAND", state)
    return _parse_new_command(text)


def _clean_message_text(msg: str) -> str:
    """Clean speech translation artifacts and trailing punctuation from extracted message."""
    if not msg:
        return ""
    cleaned = msg.strip().rstrip(".!?")
    # Clean leading speech fillers like "out ", "out a ", "a ", "the " when extracting messages
    cleaned = re.sub(r"^(?:out\s+a\s+|out\s+the\s+|out\s+|a\s+|the\s+)", "", cleaned, flags=re.IGNORECASE).strip()
    if cleaned.lower() in ("message", "text", "msg", "a message", "ek message"):
        return ""
    return cleaned


def _parse_new_command(text: str) -> NewCommandResult:
    """Extract app, recipient, and message from a voice command."""

    text_clean = re.sub(r"[.!?]+$", "", text).strip()

    # 0. HARD GUARD: Generic application launch commands are NEVER messaging commands
    if (
        re.search(r"^(?:open|launch|start|check|kholo|chalao)\s+telegram(?:\s+desktop)?$", text_clean, re.IGNORECASE)
        or re.search(r"^telegram(?:\s+desktop)?\s+(?:open|kholo|chalao|start|launch)(?:\s+karo|\s+kar\s+do)?$", text_clean, re.IGNORECASE)
    ):
        return NewCommandResult(
            state=NLUState.NEW_COMMAND.value,
            app="unknown",
            recipient_query="",
            message_text="",
            raw_command=text,
        )

    # Try each pattern in order of specificity
    for pattern in [
        _HINGLISH_CMD,
        _HINGLISH_SEND_CMD,
        _HINGLISH_MSG_BEFORE_VERB_CMD,
        _HINGLISH_RECIPIENT_FIRST_CMD,
        _HINGLISH_RECIPIENT_FIRST_MSG_CMD,
        _ENGLISH_CMD,
        _TELL_CMD,
        _MSG_USERNAME_CMD,
        _SHORT_HINGLISH_CMD,
    ]:
        m = pattern.search(text_clean)
        if m:
            recipient = _strip_at(m.group(1).strip())
            message = _clean_message_text(m.group(2))
            return NewCommandResult(
                state=NLUState.NEW_COMMAND.value,
                app="telegram",
                recipient_query=recipient,
                message_text=message,
                raw_command=text,
            )

    m = _ENGLISH_SEND_TO_CMD.search(text_clean)
    if m:
        message = _clean_message_text(m.group(1))
        recipient = _strip_at(m.group(2).strip())
        return NewCommandResult(
            state=NLUState.NEW_COMMAND.value,
            app="telegram",
            recipient_query=recipient,
            message_text=message,
            raw_command=text,
        )

    # Check if telegram is mentioned with explicit communication intent
    if _HAS_TELEGRAM.search(text_clean) and re.search(
        r"\b(send|message|bhejo|bol|tell|text|msg)\b", text_clean, re.IGNORECASE
    ):
        return NewCommandResult(
            state=NLUState.NEW_COMMAND.value,
            app="telegram",
            recipient_query="",
            message_text="",
            raw_command=text,
        )

    # Not a telegram messaging command
    return NewCommandResult(
        state=NLUState.NEW_COMMAND.value,
        app="unknown",
        recipient_query="",
        message_text="",
        raw_command=text,
    )


def _parse_disambiguation(text: str) -> DisambiguationResult:
    """Extract the user's selection from a disambiguation prompt."""
    cleaned = text.strip()

    # Try numeric/ordinal patterns
    for pattern in _OPTION_NUMBER_PATTERNS:
        m = pattern.search(cleaned)
        if m:
            val = m.group(1)
            if val.isdigit():
                return DisambiguationResult(
                    selected_option=int(val),
                    selected_name=None,
                )
            # Ordinal word
            lower_val = val.lower()
            if lower_val in _ORDINAL_MAP:
                return DisambiguationResult(
                    selected_option=_ORDINAL_MAP[lower_val],
                    selected_name=None,
                )

    # Treat the entire input as a spoken contact name
    if cleaned:
        return DisambiguationResult(
            selected_option=None,
            selected_name=cleaned,
        )

    return DisambiguationResult()


def _parse_confirmation(text: str) -> ConfirmationResult:
    """Detect positive or negative confirmation intent."""
    cleaned = re.sub(r"[^\w\s']", "", text).strip()

    if _POSITIVE_PATTERNS.match(cleaned):
        return ConfirmationResult(confirmed=True)

    if _NEGATIVE_PATTERNS.match(cleaned):
        return ConfirmationResult(confirmed=False)

    # Partial match: check if key positive/negative words appear anywhere
    if re.search(r"\b(haan|yes|bhej\s*do|send|confirm|go\s*ahead)\b", cleaned, re.IGNORECASE):
        return ConfirmationResult(confirmed=True)

    if re.search(r"\b(nahi|no|cancel|mat|rehne\s*do|stop)\b", cleaned, re.IGNORECASE):
        return ConfirmationResult(confirmed=False)

    # Ambiguous — default to not confirmed (safe)
    return ConfirmationResult(confirmed=False)
