"""
appt_agent.agent
~~~~~~~~~~~~~~~~
BookingAgent — the main orchestrator.
Assembled by BookingAgentBuilder; not instantiated directly.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from appt_agent.calendars.base import AbstractCalendar
from appt_agent.engine.conversation import ConversationEngine
from appt_agent.intents.classifier import classify_intent
from appt_agent.llm.base import AbstractLLM
from appt_agent.models import (
    Appointment,
    ChatRequest,
    ChatResponse,
    Conversation,
    ConversationState,
    Intent,
    WebhookPayload,
)
from appt_agent.storage.tracker import TokenTracker
from appt_agent.webhooks.dispatcher import WebhookDispatcher


class BookingAgent:
    """
    Conversational appointment booking agent.

    Do not instantiate directly — use BookingAgentBuilder.
    """

    def __init__(
        self,
        llm: AbstractLLM,
        calendars: list[AbstractCalendar],
        intents: list[Intent],
        tracker: TokenTracker | None,
        business_name: str,
        required_slots: list[str],
        default_duration_minutes: int,
    ) -> None:
        self._llm      = llm
        self._calendars = calendars
        self._intents   = intents
        self._tracker   = tracker
        self._business  = business_name
        self._required  = required_slots
        self._duration  = default_duration_minutes
        self._webhook   = WebhookDispatcher()
        self._engine    = ConversationEngine(
            llm=llm,
            business_name=business_name,
            required_slots=required_slots,
            intents=intents,
        )
        # In-memory conversation store (keyed by session_id)
        self._conversations: dict[str, Conversation] = {}

    # ─── public API ───────────────────────────────────────────────────────────

    async def chat(self, session_id: str, message: str, metadata: dict[str, Any] | None = None) -> ChatResponse:
        """Process one user message and return a ChatResponse."""
        conv = self._get_or_create(session_id)

        # 1. Classify intent from the user message
        detected_intent, confidence = await classify_intent(
            llm=self._llm,
            message=message,
            intents=self._intents,
        )
        if detected_intent:
            conv.detected_intent = detected_intent

        # 2. Advance conversation state machine
        reply, llm_resp = await self._engine.process(conv, message)

        # 3. Track tokens
        input_tokens  = llm_resp.input_tokens  if llm_resp else 0
        output_tokens = llm_resp.output_tokens if llm_resp else 0
        cost          = self._llm.estimate_cost(input_tokens, output_tokens) if llm_resp else 0.0

        if self._tracker:
            await self._tracker.save_message(
                conversation_id=session_id,
                role="user",
                content=message,
            )
            await self._tracker.save_message(
                conversation_id=session_id,
                role="assistant",
                content=reply,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model=self._llm.model,
                cost_usd=cost,
            )
            await self._tracker.update_state(session_id, conv.state.value)

            if detected_intent:
                intent_obj = next((i for i in self._intents if i.name == detected_intent), None)
                await self._tracker.log_intent(
                    conversation_id=session_id,
                    intent_name=detected_intent,
                    confidence=confidence,
                    webhook_url=intent_obj.webhook if intent_obj else None,
                )

        # 4. If BOOKED → create calendar event + fire webhook
        appointment = None
        if conv.state == ConversationState.BOOKED and conv.appointment is None:
            appointment = await self._create_appointment(conv, session_id)
            conv.appointment = appointment

        # 5. Fire webhooks for detected intent
        if detected_intent:
            await self._dispatch_webhooks(
                session_id=session_id,
                intent_name=detected_intent,
                slots=conv.slots,
                appointment=appointment or conv.appointment,
            )

        # 6. Build token summary
        token_summary = None
        if self._tracker:
            token_summary = await self._tracker.get_token_summary(session_id)

        return ChatResponse(
            session_id=session_id,
            reply=reply,
            state=conv.state,
            intent=detected_intent,
            appointment=appointment or conv.appointment,
            tokens_used=token_summary,
            slots=conv.slots,
        )

    async def startup(self) -> None:
        """Call this on app startup to connect the tracker."""
        if self._tracker:
            await self._tracker.connect()

    async def shutdown(self) -> None:
        """Call this on app shutdown to close the tracker."""
        if self._tracker:
            await self._tracker.close()

    def get_conversation(self, session_id: str) -> Conversation | None:
        return self._conversations.get(session_id)

    # ─── internals ────────────────────────────────────────────────────────────

    def _get_or_create(self, session_id: str) -> Conversation:
        if session_id not in self._conversations:
            self._conversations[session_id] = Conversation(id=session_id)
        return self._conversations[session_id]

    async def _create_appointment(self, conv: Conversation, session_id: str) -> Appointment | None:
        if not self._calendars or not conv.slots.get("date") or not conv.slots.get("time"):
            return None

        try:
            date_str  = conv.slots["date"]
            time_str  = conv.slots["time"]
            start_str = f"{date_str}T{time_str}:00"
            start_dt  = datetime.fromisoformat(start_str)
            end_dt    = start_dt + timedelta(minutes=self._duration)

            appt = Appointment(
                id=str(uuid.uuid4()),
                attendee_name=conv.slots.get("name") or "Guest",
                attendee_email=conv.slots.get("email"),
                service=conv.slots.get("service"),
                start=start_dt,
                end=end_dt,
                calendar_provider=self._calendars[0].provider,
            )

            # Use first calendar provider
            cal = self._calendars[0]
            event_id = await cal.create_event(appt)
            appt.calendar_event_id = event_id
            return appt

        except Exception as exc:
            import logging
            logging.getLogger("appt_agent").error("Failed to create calendar event: %s", exc)
            return None

    async def _dispatch_webhooks(
        self,
        session_id: str,
        intent_name: str,
        slots: dict[str, Any],
        appointment: Appointment | None,
    ) -> None:
        intent_obj = next((i for i in self._intents if i.name == intent_name), None)
        if not intent_obj or not intent_obj.webhook:
            return

        payload = WebhookPayload(
            event=f"intent.{intent_name}",
            intent_name=intent_name,
            session_id=session_id,
            appointment=appointment,
            slots=slots,
            metadata=intent_obj.metadata,
        )

        success = await self._webhook.dispatch(
            payload=payload,
            webhook_url=intent_obj.webhook,
            secret=intent_obj.webhook_secret,
        )

        if success and self._tracker:
            await self._tracker.mark_webhook_sent(session_id, intent_name)
