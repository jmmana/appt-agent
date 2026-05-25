"""
appt_agent.builder
~~~~~~~~~~~~~~~~~~~
Fluent builder API for creating a BookingAgent.

Example
-------
from appt_agent import BookingAgentBuilder, Intent

agent = (
    BookingAgentBuilder()
    .with_llm("anthropic", api_key="sk-ant-...", model="claude-sonnet-4-6")
    .with_calendar("google", credentials_path="credentials.json")
    .with_calendar("outlook", client_id="...", client_secret="...", tenant_id="...", user_email="...")
    .with_calendar("mcp", command=["npx", "google-calendar-mcp"])
    .with_intent(Intent("reservar_cita", "El usuario quiere agendar una cita", webhook="https://..."))
    .with_intent(Intent("cancelar_cita", "El usuario quiere cancelar su cita"))
    .with_token_tracking("tokens.db")
    .with_business_name("Clínica Santa María")
    .with_required_slots(["name", "date", "time", "service"])
    .with_appointment_duration(45)
    .build()
)
"""
from __future__ import annotations

from typing import Any

from appt_agent.calendars.base import AbstractCalendar
from appt_agent.llm.base import AbstractLLM
from appt_agent.models import Intent
from appt_agent.storage.tracker import TokenTracker


class BookingAgentBuilder:
    """Fluent builder for BookingAgent."""

    def __init__(self) -> None:
        self._llm: AbstractLLM | None = None
        self._calendars: list[AbstractCalendar] = []
        self._intents: list[Intent] = []
        self._tracker: TokenTracker | None = None
        self._business_name: str = "Appointment Booking"
        self._required_slots: list[str] = ["name", "date", "time"]
        self._duration: int = 30

    # ─── LLM ─────────────────────────────────────────────────────────────────

    def with_llm(self, provider: str, **kwargs: Any) -> "BookingAgentBuilder":
        """
        Configure the LLM provider.

        Parameters
        ----------
        provider : str
            One of: anthropic, openai, google, gemini, ollama, meta,
                    deepseek, xai, groq, mistral, cohere, bedrock
        **kwargs :
            Provider-specific arguments (api_key, model, base_url, etc.)
        """
        from appt_agent.llm.base import get_provider
        cls = get_provider(provider)
        self._llm = cls(**kwargs)
        return self

    def with_llm_instance(self, llm: AbstractLLM) -> "BookingAgentBuilder":
        """Use a pre-built AbstractLLM instance."""
        self._llm = llm
        return self

    # ─── Calendars ────────────────────────────────────────────────────────────

    def with_calendar(self, provider: str, **kwargs: Any) -> "BookingAgentBuilder":
        """
        Add a calendar provider.

        Parameters
        ----------
        provider : str
            One of: google, outlook, microsoft, mcp
        **kwargs :
            Provider-specific args.

            google   → credentials_path="..." | credentials=<obj>
            outlook  → client_id, client_secret, tenant_id, user_email
            mcp      → server_url="..." | command=[...]
        """
        from appt_agent.calendars.base import get_calendar_provider

        # Handle convenience shortcuts
        if provider == "google" and "credentials_path" in kwargs:
            from appt_agent.calendars.google_cal import GoogleCalendar
            cal = GoogleCalendar.from_oauth2(
                credentials_path=kwargs.pop("credentials_path"),
                token_path=kwargs.pop("token_path", "token.json"),
            )
        elif provider == "google" and "service_account_path" in kwargs:
            from appt_agent.calendars.google_cal import GoogleCalendar
            cal = GoogleCalendar.from_service_account(
                json_path=kwargs.pop("service_account_path"),
                delegate=kwargs.pop("delegate", None),
            )
        else:
            cls = get_calendar_provider(provider)
            cal = cls(**kwargs)

        self._calendars.append(cal)
        return self

    def with_calendar_instance(self, calendar: AbstractCalendar) -> "BookingAgentBuilder":
        """Use a pre-built AbstractCalendar instance."""
        self._calendars.append(calendar)
        return self

    # ─── Intents ──────────────────────────────────────────────────────────────

    def with_intent(self, intent: Intent) -> "BookingAgentBuilder":
        """Register an intent. Multiple intents can be added."""
        self._intents.append(intent)
        return self

    def with_intents(self, *intents: Intent) -> "BookingAgentBuilder":
        """Register multiple intents at once."""
        self._intents.extend(intents)
        return self

    # ─── Token tracking ───────────────────────────────────────────────────────

    def with_token_tracking(self, db_path: str = "appt_tokens.db") -> "BookingAgentBuilder":
        """Enable SQLite token tracking."""
        self._tracker = TokenTracker(db_path=db_path)
        return self

    def with_tracker_instance(self, tracker: TokenTracker) -> "BookingAgentBuilder":
        self._tracker = tracker
        return self

    # ─── Configuration ────────────────────────────────────────────────────────

    def with_business_name(self, name: str) -> "BookingAgentBuilder":
        """Set the business name shown in the assistant's persona."""
        self._business_name = name
        return self

    def with_required_slots(self, slots: list[str]) -> "BookingAgentBuilder":
        """
        Override which slots must be collected before confirmation.
        Default: ["name", "date", "time"]
        Available: name, date, time, service, email
        """
        self._required_slots = slots
        return self

    def with_appointment_duration(self, minutes: int) -> "BookingAgentBuilder":
        """Set default appointment duration in minutes (default: 30)."""
        self._duration = minutes
        return self

    # ─── Build ────────────────────────────────────────────────────────────────

    def build(self) -> "BookingAgent":  # type: ignore[name-defined]
        """Validate config and return a ready BookingAgent."""
        if self._llm is None:
            raise ValueError(
                "No LLM configured. Call .with_llm(provider, api_key=...) first."
            )

        from appt_agent.agent import BookingAgent

        return BookingAgent(
            llm=self._llm,
            calendars=self._calendars,
            intents=self._intents,
            tracker=self._tracker,
            business_name=self._business_name,
            required_slots=self._required_slots,
            default_duration_minutes=self._duration,
        )
