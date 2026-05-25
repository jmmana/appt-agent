"""
appt_agent.calendars.base
~~~~~~~~~~~~~~~~~~~~~~~~~~
Abstract calendar protocol. All calendar adapters must implement this.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from appt_agent.models import Appointment, TimeSlot

_REGISTRY: dict[str, type["AbstractCalendar"]] = {}


def register_calendar(name: str):  # type: ignore[return]
    """Class decorator to register a calendar provider."""
    def decorator(cls: type["AbstractCalendar"]) -> type["AbstractCalendar"]:
        _REGISTRY[name] = cls
        return cls
    return decorator


def get_calendar_provider(name: str) -> type["AbstractCalendar"]:
    if name not in _REGISTRY:
        available = ", ".join(_REGISTRY.keys())
        raise ValueError(f"Calendar provider '{name}' not found. Available: {available}")
    return _REGISTRY[name]


class AbstractCalendar(ABC):
    """Base class for calendar adapters."""

    provider: str = "unknown"

    @abstractmethod
    async def get_available_slots(
        self,
        date_str: str,       # YYYY-MM-DD
        duration_minutes: int = 30,
        calendar_id: str = "primary",
    ) -> list[TimeSlot]:
        """Return available time slots for the given date."""
        ...

    @abstractmethod
    async def create_event(self, appointment: Appointment) -> str:
        """
        Create a calendar event for the appointment.
        Returns the created event ID.
        """
        ...

    @abstractmethod
    async def delete_event(self, event_id: str, calendar_id: str = "primary") -> bool:
        """Delete an event by ID. Returns True if successful."""
        ...

    async def find_event_by_attendee(
        self, attendee_email: str, date_str: str | None = None
    ) -> list[Appointment]:
        """Optional: search events by attendee email."""
        return []
