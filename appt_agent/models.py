"""
appt_agent.models
~~~~~~~~~~~~~~~~~
Pydantic v2 shared data models used across the library.
"""
from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ─── Appointment state machine ────────────────────────────────────────────────

class ConversationState(str, Enum):
    GREETING      = "greeting"
    COLLECT_INFO  = "collect_info"
    CONFIRM       = "confirm"
    BOOKED        = "booked"
    CANCELLED     = "cancelled"
    ERROR         = "error"


# ─── Calendar primitives ──────────────────────────────────────────────────────

class TimeSlot(BaseModel):
    start: datetime
    end: datetime
    available: bool = True
    title: str | None = None

    model_config = {}


class Appointment(BaseModel):
    id: str | None = None
    calendar_event_id: str | None = None
    attendee_name: str
    attendee_email: str | None = None
    service: str | None = None
    start: datetime
    end: datetime
    notes: str | None = None
    calendar_provider: str | None = None  # "google" | "outlook" | "mcp"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = {}


# ─── Intent ───────────────────────────────────────────────────────────────────

class Intent(BaseModel):
    """Represents a configurable intent with optional webhook."""
    name: str
    description: str
    webhook: str | None = None
    webhook_secret: str | None = None  # HMAC secret for webhook signing
    metadata: dict[str, Any] = Field(default_factory=dict)

    def __init__(
        self,
        name: str,
        description: str,
        webhook: str | None = None,
        webhook_secret: str | None = None,
        **metadata: Any,
    ) -> None:
        super().__init__(
            name=name,
            description=description,
            webhook=webhook,
            webhook_secret=webhook_secret,
            metadata=metadata,
        )


# ─── Conversation / message ───────────────────────────────────────────────────

class Role(str, Enum):
    USER      = "user"
    ASSISTANT = "assistant"
    SYSTEM    = "system"


class Message(BaseModel):
    role: Role
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Conversation(BaseModel):
    id: str
    state: ConversationState = ConversationState.GREETING
    messages: list[Message] = Field(default_factory=list)
    slots: dict[str, Any] = Field(default_factory=dict)   # name, date, time, service
    appointment: Appointment | None = None
    detected_intent: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ─── LLM response ─────────────────────────────────────────────────────────────

class LLMResponse(BaseModel):
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str
    provider: str


# ─── Chat API request/response ────────────────────────────────────────────────

class ChatRequest(BaseModel):
    session_id: str = Field(..., description="Unique conversation/session identifier")
    message: str    = Field(..., description="User message")
    metadata: dict[str, Any] = Field(default_factory=dict)


class TokenUsage(BaseModel):
    conversation_id: str
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    message_count: int


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    state: ConversationState
    intent: str | None = None
    appointment: Appointment | None = None
    tokens_used: TokenUsage | None = None
    slots: dict[str, Any] = Field(default_factory=dict)


# ─── Webhook payload ──────────────────────────────────────────────────────────

class WebhookPayload(BaseModel):
    event: str                          # e.g. "intent.reservar_cita"
    intent_name: str
    session_id: str
    appointment: Appointment | None = None
    slots: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)
