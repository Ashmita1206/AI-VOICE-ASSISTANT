"""
Telegram Automation Router
==========================

Multi-turn state machine orchestrator for Telegram hybrid messaging automation.

Orchestrates the safety lifecycle:
Voice Command → NLU Parsing → Contact Search → Contact Disambiguation → Visual Draft Preview → Voice Confirmation → Send Execution

Safety Invariants Enforced:
1. NO CONTACT GUESSING — 0 matches returns CONTACT_NOT_FOUND.
2. NO SILENT SENDING — Visual preview deep link is ALWAYS launched before confirmation.
3. NO AUTO-SEND — Enter key is ONLY pressed after explicit positive confirmation.
4. NO RE-SEND / DUPLICATE SEND — Confirmations are consumed exactly once.
5. NO SEND AFTER CANCEL — Negative confirmation clears state with 0 side effects.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, List, Optional, Union

from automation.telegram.models import (
    ConfirmationResult,
    DisambiguationResult,
    FlowStatus,
    NewCommandResult,
    NLUState,
    TelegramContact,
    TelegramFlowMode,
    TelegramFlowResult,
    TelegramFlowState,
)
from automation.telegram.nlu import parse_telegram_input
from automation.telegram.telegram_automation import TelegramService

logger = logging.getLogger(__name__)


class TelegramAutomationRouter:
    """Stateful router for Telegram voice messaging workflows.

    Parameters
    ----------
    telegram_service:
        An instance of ``TelegramService`` (handles search, preview, send).
    nlu_fn:
        Optional LLM callable for NLU parsing. Passed to ``parse_telegram_input``.
    """

    def __init__(
        self,
        telegram_service: TelegramService,
        nlu_fn: Optional[Callable[[str, str], str]] = None,
    ) -> None:
        self.service = telegram_service
        self.nlu_fn = nlu_fn
        self.state = TelegramFlowState()

    def reset(self) -> None:
        """Reset internal flow state to IDLE."""
        self.state.reset()

    async def handle_input(self, user_text: str) -> TelegramFlowResult:
        """Process a user voice utterance according to current router state.

        Parameters
        ----------
        user_text:
            The raw transcribed user speech.

        Returns
        -------
        ``TelegramFlowResult`` containing status code, response message,
        and updated state.
        """
        # Determine NLU input state based on router mode
        if self.state.mode == TelegramFlowMode.DISAMBIGUATION:
            nlu_state = NLUState.DISAMBIGUATION.value
        elif self.state.mode == TelegramFlowMode.CONFIRMATION:
            nlu_state = NLUState.CONFIRMATION.value
        else:
            nlu_state = NLUState.NEW_COMMAND.value

        parsed = parse_telegram_input(nlu_state, user_text, llm_fn=self.nlu_fn)

        if nlu_state == NLUState.NEW_COMMAND.value:
            assert isinstance(parsed, NewCommandResult)
            return await self._handle_new_command(parsed)

        if nlu_state == NLUState.DISAMBIGUATION.value:
            assert isinstance(parsed, DisambiguationResult)
            return await self._handle_disambiguation(parsed)

        if nlu_state == NLUState.CONFIRMATION.value:
            assert isinstance(parsed, ConfirmationResult)
            return await self._handle_confirmation(parsed)

        return TelegramFlowResult(
            status=FlowStatus.ERROR,
            message="Internal routing state error.",
            state=self.state,
        )

    # ── State Handlers ──────────────────────────────────────────────────────

    async def _handle_new_command(self, parsed: NewCommandResult) -> TelegramFlowResult:
        """Process a NEW_COMMAND parse result."""
        # Hard Guard 1: Non-Telegram app requests are ignored by this router
        if parsed.app != "telegram":
            return TelegramFlowResult(
                status=FlowStatus.NOT_TELEGRAM,
                message=f"App '{parsed.app}' is not handled by Telegram router.",
                state=self.state,
            )

        # Hard Guard 2: Generic open/launch commands must NEVER trigger messaging flows
        import re
        raw_clean = re.sub(r"[.!?]+$", "", parsed.raw_command).strip()
        if (
            re.search(r"^(?:open|launch|start|check|kholo|chalao)\s+telegram(?:\s+desktop)?$", raw_clean, re.IGNORECASE)
            or re.search(r"^telegram(?:\s+desktop)?\s+(?:open|kholo|chalao|start|launch)(?:\s+karo|\s+kar\s+do)?$", raw_clean, re.IGNORECASE)
        ):
            return TelegramFlowResult(
                status=FlowStatus.NOT_TELEGRAM,
                message="Generic application opening commands are not handled by Telegram messaging router.",
                state=self.state,
            )

        # Validate recipient query
        if not parsed.recipient_query:
            return TelegramFlowResult(
                status=FlowStatus.MISSING_RECIPIENT,
                message="Please specify who you want to message on Telegram.",
                state=self.state,
            )

        # Validate message text
        if not parsed.message_text:
            return TelegramFlowResult(
                status=FlowStatus.MISSING_MESSAGE,
                message=f"What message would you like to send to {parsed.recipient_query}?",
                state=self.state,
            )

        # Initialize fresh state for new command
        self.state.reset()
        self.state.recipient_query = parsed.recipient_query
        self.state.message_text = parsed.message_text
        self.state.raw_command = parsed.raw_command

        # Contact search
        import inspect
        contacts_res = self.service.search_contacts(self.state.recipient_query)
        if inspect.isawaitable(contacts_res):
            contacts = await contacts_res
        else:
            contacts = contacts_res

        # Case 0: 0 matches
        if not contacts:
            self.state.mode = TelegramFlowMode.ERROR
            return TelegramFlowResult(
                status=FlowStatus.CONTACT_NOT_FOUND,
                message=f"I couldn't find a Telegram contact matching '{self.state.recipient_query}'.",
                state=self.state,
                data={"query": self.state.recipient_query},
            )

        # Case 1: Exactly 1 match
        if len(contacts) == 1:
            return self._select_contact_and_preview(contacts[0])

        # Case 2: Multiple matches -> DISAMBIGUATION
        self.state.candidates = contacts
        self.state.mode = TelegramFlowMode.DISAMBIGUATION

        options_text = []
        for i, c in enumerate(contacts, 1):
            options_text.append(f"Option {i}: {c.display_label()}")

        prompt = (
            f"I found multiple Telegram contacts matching '{self.state.recipient_query}'.\n"
            + "\n".join(options_text)
            + "\nWhich one do you want?"
        )

        return TelegramFlowResult(
            status=FlowStatus.DISAMBIGUATION_REQUIRED,
            message=prompt,
            state=self.state,
            data={"candidates": [c.display_label() for c in contacts]},
        )

    async def _handle_disambiguation(self, parsed: DisambiguationResult) -> TelegramFlowResult:
        """Process a DISAMBIGUATION parse result against stored candidates."""
        if self.state.mode != TelegramFlowMode.DISAMBIGUATION or not self.state.candidates:
            return TelegramFlowResult(
                status=FlowStatus.ERROR,
                message="No pending contact disambiguation in progress.",
                state=self.state,
            )

        selected: Optional[TelegramContact] = None

        # Try by 1-based option index
        if parsed.selected_option is not None:
            idx = parsed.selected_option - 1
            if 0 <= idx < len(self.state.candidates):
                selected = self.state.candidates[idx]

        # Try by spoken contact name matching pending candidates
        if selected is None and parsed.selected_name:
            q = parsed.selected_name.strip().lower()
            for c in self.state.candidates:
                c_name = c.name.lower()
                c_uname = (c.username or "").lower()
                if q == c_name or q == c_uname or q in c_name:
                    selected = c
                    break

        # If choice is invalid / unresolvable: ask again, DO NOT guess
        if selected is None:
            options_text = [
                f"Option {i}: {c.display_label()}"
                for i, c in enumerate(self.state.candidates, 1)
            ]
            msg = (
                "I didn't catch that choice. Please specify an option number or name:\n"
                + "\n".join(options_text)
            )
            return TelegramFlowResult(
                status=FlowStatus.INVALID_SELECTION,
                message=msg,
                state=self.state,
            )

        # Contact resolved successfully
        return self._select_contact_and_preview(selected)

    def _select_contact_and_preview(self, contact: TelegramContact) -> TelegramFlowResult:
        """Store selected contact, launch visual preview deep link, and move to CONFIRMATION state."""
        self.state.selected_contact = contact

        # Handle contact without username
        if not contact.username:
            self.state.mode = TelegramFlowMode.ERROR
            return TelegramFlowResult(
                status=FlowStatus.USERNAME_UNAVAILABLE,
                message=(
                    f"Contact '{contact.name}' does not have a Telegram username. "
                    "Cannot generate draft deep link."
                ),
                state=self.state,
                data={"contact_name": contact.name},
            )

        # Launch visual deep link
        preview_status = self.service.open_preview(contact.username, self.state.message_text)

        if preview_status in (FlowStatus.LINK_LAUNCH_REQUESTED, FlowStatus.PREVIEW_READY):
            self.state.preview_opened = True
            self.state.mode = TelegramFlowMode.CONFIRMATION
            self.state.generate_action_id()

            msg = (
                f"I've opened the Telegram chat for {contact.name} with your message ready.\n"
                f"Message: \"{self.state.message_text}\"\n"
                "Should I send it? Say Yes or No."
            )

            return TelegramFlowResult(
                status=FlowStatus.CONFIRMATION_REQUIRED,
                message=msg,
                state=self.state,
                data={
                    "pending_action_id": self.state.pending_action_id,
                    "recipient": contact.name,
                    "username": contact.username,
                    "message": self.state.message_text,
                },
            )

        # Preview opening failed
        self.state.mode = TelegramFlowMode.ERROR
        return TelegramFlowResult(
            status=FlowStatus.ERROR,
            message=f"Failed to open Telegram chat for {contact.name}.",
            state=self.state,
        )

    async def _handle_confirmation(self, parsed: ConfirmationResult) -> TelegramFlowResult:
        """Process a CONFIRMATION parse result."""
        # Ensure state invariant
        if (
            self.state.mode != TelegramFlowMode.CONFIRMATION
            or not self.state.preview_opened
            or not self.state.pending_action_id
        ):
            return TelegramFlowResult(
                status=FlowStatus.ERROR,
                message="No pending message awaiting confirmation.",
                state=self.state,
            )

        # Duplicate confirmation protection
        if self.state.executed:
            return TelegramFlowResult(
                status=FlowStatus.ALREADY_EXECUTED,
                message="Message has already been sent.",
                state=self.state,
            )

        # Case: Positive Confirmation -> Send
        if parsed.confirmed:
            send_status = self.service.send_current_draft()

            if send_status == FlowStatus.SEND_KEY_DISPATCHED:
                self.state.executed = True
                self.state.mode = TelegramFlowMode.COMPLETED
                recip = (
                    self.state.selected_contact.name
                    if self.state.selected_contact
                    else self.state.recipient_query
                )
                action_id = self.state.pending_action_id

                result = TelegramFlowResult(
                    status=FlowStatus.SEND_KEY_DISPATCHED,
                    message=f"Enter key dispatched to send message to {recip}.",
                    state=self.state,
                    data={"action_id": action_id, "recipient": recip},
                )
                return result

            # Send execution failure
            self.state.mode = TelegramFlowMode.ERROR
            return TelegramFlowResult(
                status=FlowStatus.ERROR,
                message="Failed to dispatch send key.",
                state=self.state,
            )

        # Case: Negative Confirmation -> Cancel
        self.state.reset()
        self.state.mode = TelegramFlowMode.CANCELLED
        return TelegramFlowResult(
            status=FlowStatus.CANCELLED,
            message="Telegram message cancelled.",
            state=self.state,
        )
