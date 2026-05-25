"""
appt_agent.engine.conversation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Multi-turn conversation engine with state machine.

States
------
GREETING     → initial state, detect intent
COLLECT_INFO → gather name/date/time/service via slot filler
CONFIRM      → show summary and ask for confirmation
BOOKED       → appointment created in calendar
CANCELLED    → user cancelled or intent=cancelar_cita
ERROR        → something went wrong
"""
from __future__ import annotations

from datetime import date
from typing import Any

from appt_agent.engine.slot_filler import extract_slots, missing_slots
from appt_agent.llm.base import AbstractLLM
from appt_agent.models import (
    Conversation,
    ConversationState,
    LLMResponse,
    Message,
    Role,
)

# ─── Prompt templates ─────────────────────────────────────────────────────────

_BASE_SYSTEM = """\
You are a friendly appointment booking assistant. Your job is to help users
schedule appointments by collecting their name, preferred date, time, and
service type. Always be concise and professional. Respond in the same language
the user writes in.

Current date: {today}
Business name: {business_name}
{intents_block}
"""

_CONFIRM_TEMPLATE = """\
Please confirm your appointment:
- **Name**: {name}
- **Date**: {date}
- **Time**: {time}
- **Service**: {service}

Reply "yes" / "confirm" to book, or "no" / "cancel" to start over.
"""

_POSITIVE_CONFIRMATIONS = {"yes", "si", "sí", "confirm", "ok", "okay", "sure", "yep", "dale"}
_NEGATIVE_CONFIRMATIONS = {"no", "cancel", "cancelar", "nope", "start over", "restart"}


class ConversationEngine:
    """Manages conversation state for a single session."""

    def __init__(
        self,
        llm: AbstractLLM,
        business_name: str = "Our Business",
        required_slots: list[str] | None = None,
        intents: list[Any] | None = None,  # list[Intent] — avoid circular import
    ) -> None:
        self._llm           = llm
        self._business_name = business_name
        self._required      = required_slots or ["name", "date", "time"]
        self._intents       = intents or []

    # ─── public API ──────────────────────────────────────────────────────────

    async def process(
        self,
        conversation: Conversation,
        user_message: str,
    ) -> tuple[str, LLMResponse | None]:
        """
        Advance the conversation by one user turn.
        Returns (reply_text, llm_response_or_None).
        Mutates conversation in-place.
        """
        conversation.messages.append(Message(role=Role.USER, content=user_message))
        today = date.today().isoformat()

        state = conversation.state

        if state == ConversationState.BOOKED:
            reply = "Your appointment is already booked! Is there anything else I can help you with?"
            conversation.messages.append(Message(role=Role.ASSISTANT, content=reply))
            return reply, None

        if state == ConversationState.CANCELLED:
            # Allow restart
            conversation.state = ConversationState.GREETING
            conversation.slots = {}

        if state in (ConversationState.GREETING, ConversationState.COLLECT_INFO):
            return await self._handle_collect(conversation, user_message, today)

        if state == ConversationState.CONFIRM:
            return await self._handle_confirm(conversation, user_message)

        # Fallback
        return await self._llm_reply(conversation, today), None

    # ─── state handlers ───────────────────────────────────────────────────────

    async def _handle_collect(
        self, conv: Conversation, user_message: str, today: str
    ) -> tuple[str, LLMResponse | None]:
        # Extract / merge slots
        conv.slots = await extract_slots(
            llm=self._llm,
            message=user_message,
            history=conv.messages[:-1],
            today=today,
            existing_slots=conv.slots,
        )
        conv.state = ConversationState.COLLECT_INFO

        missing = missing_slots(conv.slots, self._required)
        if not missing:
            # All slots collected → move to confirm
            conv.state = ConversationState.CONFIRM
            reply = _CONFIRM_TEMPLATE.format(
                name=conv.slots.get("name", "—"),
                date=conv.slots.get("date", "—"),
                time=conv.slots.get("time", "—"),
                service=conv.slots.get("service") or "General",
            )
            conv.messages.append(Message(role=Role.ASSISTANT, content=reply))
            return reply, None

        # Ask LLM to generate follow-up question for missing slots
        llm_resp = await self._llm_reply(conv, today, extra_context=f"Still need: {missing}")
        conv.messages.append(Message(role=Role.ASSISTANT, content=llm_resp))
        return llm_resp, None

    async def _handle_confirm(
        self, conv: Conversation, user_message: str
    ) -> tuple[str, LLMResponse | None]:
        normalized = user_message.strip().lower()

        if any(word in normalized for word in _POSITIVE_CONFIRMATIONS):
            # Signal caller to create calendar event — engine doesn't call calendar directly
            conv.state = ConversationState.BOOKED
            reply = (
                f"✅ Your appointment has been confirmed!\n"
                f"- **{conv.slots.get('name')}** on {conv.slots.get('date')} at {conv.slots.get('time')}\n"
                f"You'll receive a confirmation shortly."
            )
        elif any(word in normalized for word in _NEGATIVE_CONFIRMATIONS):
            conv.state  = ConversationState.CANCELLED
            conv.slots  = {}
            reply = "No problem! Your appointment has been cancelled. Feel free to start a new request."
        else:
            # Neither yes nor no — re-ask
            reply = (
                "Please reply **yes** to confirm the appointment or **no** to cancel."
            )

        conv.messages.append(Message(role=Role.ASSISTANT, content=reply))
        return reply, None

    # ─── helpers ──────────────────────────────────────────────────────────────

    async def _llm_reply(
        self,
        conv: Conversation,
        today: str,
        extra_context: str | None = None,
    ) -> str:
        intents_block = ""
        if self._intents:
            desc_list = "\n".join(f"  - {i.name}: {i.description}" for i in self._intents)
            intents_block = f"Configurable intents:\n{desc_list}"

        system = _BASE_SYSTEM.format(
            today=today,
            business_name=self._business_name,
            intents_block=intents_block,
        )
        if extra_context:
            system += f"\n\n{extra_context}"

        # Pass last 10 messages to LLM
        llm_resp = await self._llm.chat(
            messages=conv.messages[-10:],
            system=system,
            temperature=0.3,
            max_tokens=512,
        )
        return llm_resp.content
