"""
appt-agent
~~~~~~~~~~
Framework for building conversational appointment booking agents.

Quick start
-----------
from appt_agent import BookingAgentBuilder, Intent

agent = (
    BookingAgentBuilder()
    .with_llm("anthropic", api_key="sk-ant-...", model="claude-sonnet-4-6")
    .with_calendar("google", credentials_path="credentials.json")
    .with_intent(Intent("reservar_cita", "User wants to book", webhook="https://..."))
    .with_token_tracking("tokens.db")
    .build()
)
response = await agent.chat("user-123", "Quiero una cita el martes a las 3pm")
"""

__version__ = "0.1.0"
__author__  = "Juan Manuel Castillo Pinto"

from appt_agent.agent import BookingAgent
from appt_agent.builder import BookingAgentBuilder
from appt_agent.models import (
    Appointment,
    ChatRequest,
    ChatResponse,
    Conversation,
    ConversationState,
    Intent,
    LLMResponse,
    Message,
    Role,
    TimeSlot,
    TokenUsage,
    WebhookPayload,
)

__all__ = [
    "__version__",
    # Main API
    "BookingAgentBuilder",
    "BookingAgent",
    # Models
    "Intent",
    "Appointment",
    "TimeSlot",
    "Conversation",
    "ConversationState",
    "ChatRequest",
    "ChatResponse",
    "LLMResponse",
    "Message",
    "Role",
    "TokenUsage",
    "WebhookPayload",
]
