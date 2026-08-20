"""
Telegram Hybrid Automation — Models
====================================

Core data models for the Telegram messaging workflow:
state enums, contact structures, NLU result types, flow state, and result codes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TelegramFlowMode(str, Enum):
    """Internal execution-side state of the Telegram automation flow."""
    IDLE = "IDLE"
    DISAMBIGUATION = "DISAMBIGUATION"
    CONFIRMATION = "CONFIRMATION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class NLUState(str, Enum):
    """NLU-facing conversation states (what the parser sees)."""
    NEW_COMMAND = "NEW_COMMAND"
    DISAMBIGUATION = "DISAMBIGUATION"
    CONFIRMATION = "CONFIRMATION"


class FlowStatus(str, Enum):
    """Outcome codes returned by the router after each step."""
    CONTACT_NOT_FOUND = "CONTACT_NOT_FOUND"
    DISAMBIGUATION_REQUIRED = "DISAMBIGUATION_REQUIRED"
    PREVIEW_READY = "PREVIEW_READY"
    LINK_LAUNCH_REQUESTED = "LINK_LAUNCH_REQUESTED"
    SEND_KEY_DISPATCHED = "SEND_KEY_DISPATCHED"
    CANCELLED = "CANCELLED"
    USERNAME_UNAVAILABLE = "USERNAME_UNAVAILABLE"
    ERROR = "ERROR"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    ALREADY_EXECUTED = "ALREADY_EXECUTED"
    MISSING_RECIPIENT = "MISSING_RECIPIENT"
    MISSING_MESSAGE = "MISSING_MESSAGE"
    INVALID_SELECTION = "INVALID_SELECTION"
    NOT_TELEGRAM = "NOT_TELEGRAM"
    IDLE = "IDLE"


# ---------------------------------------------------------------------------
# Contact Model
# ---------------------------------------------------------------------------

@dataclass
class TelegramContact:
    """Normalised representation of a Telegram user/contact."""
    id: int
    name: str
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    contact_type: str = "user"  # "user", "group", "channel"

    def display_label(self) -> str:
        """Human-readable label for disambiguation lists."""
        if self.username:
            return f"{self.name} — @{self.username}"
        return self.name


# ---------------------------------------------------------------------------
# NLU Parse Results
# ---------------------------------------------------------------------------

@dataclass
class NewCommandResult:
    """Parsed output from NLU for a NEW_COMMAND state."""
    state: str = NLUState.NEW_COMMAND.value
    app: str = "unknown"
    recipient_query: str = ""
    message_text: str = ""
    raw_command: str = ""


@dataclass
class DisambiguationResult:
    """Parsed output from NLU for DISAMBIGUATION state."""
    state: str = NLUState.DISAMBIGUATION.value
    selected_option: Optional[int] = None  # 1-based
    selected_name: Optional[str] = None


@dataclass
class ConfirmationResult:
    """Parsed output from NLU for CONFIRMATION state."""
    state: str = NLUState.CONFIRMATION.value
    confirmed: bool = False


# ---------------------------------------------------------------------------
# Flow State
# ---------------------------------------------------------------------------

@dataclass
class TelegramFlowState:
    """Complete state of a Telegram messaging flow.

    Tracks every stage from initial command through contact resolution,
    disambiguation, preview, and final confirmation/send.
    """
    mode: TelegramFlowMode = TelegramFlowMode.IDLE
    recipient_query: str = ""
    message_text: str = ""
    raw_command: str = ""
    candidates: List[TelegramContact] = field(default_factory=list)
    selected_contact: Optional[TelegramContact] = None
    preview_opened: bool = False
    pending_action_id: Optional[str] = None
    executed: bool = False

    def generate_action_id(self) -> str:
        """Generate and store a unique pending action ID."""
        self.pending_action_id = uuid.uuid4().hex[:16]
        return self.pending_action_id

    def reset(self) -> None:
        """Reset all state to idle."""
        self.mode = TelegramFlowMode.IDLE
        self.recipient_query = ""
        self.message_text = ""
        self.raw_command = ""
        self.candidates.clear()
        self.selected_contact = None
        self.preview_opened = False
        self.pending_action_id = None
        self.executed = False


# ---------------------------------------------------------------------------
# Flow Result
# ---------------------------------------------------------------------------

@dataclass
class TelegramFlowResult:
    """Return value from the router after processing an input.

    Encapsulates the outcome status, a human-readable message,
    the current flow state snapshot, and optional extra data.
    """
    status: FlowStatus
    message: str = ""
    state: Optional[TelegramFlowState] = None
    data: Optional[Dict[str, Any]] = None
