"""
appt_agent.calendars.google_cal
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Google Calendar adapter via google-api-python-client.
pip install appt-agent[google]

Auth options
------------
1. Service account (server-to-server):
   GoogleCalendar.from_service_account("service_account.json", delegate="user@domain.com")

2. OAuth2 credentials file (for user-consent flow, CLI/desktop):
   GoogleCalendar.from_oauth2("credentials.json", token_path="token.json")

3. Pre-built credentials object:
   GoogleCalendar(credentials=my_credentials_obj)
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Any

from appt_agent.calendars.base import AbstractCalendar, register_calendar
from appt_agent.models import Appointment, TimeSlot


@register_calendar("google")
class GoogleCalendar(AbstractCalendar):
    provider = "google"

    def __init__(self, credentials: Any) -> None:
        try:
            from googleapiclient.discovery import build  # type: ignore[import]
        except ImportError:
            raise ImportError("pip install appt-agent[google]") from None
        self._service = build("calendar", "v3", credentials=credentials, cache_discovery=False)

    # ─── factory methods ──────────────────────────────────────────────────────

    @classmethod
    def from_service_account(
        cls,
        json_path: str,
        scopes: list[str] | None = None,
        delegate: str | None = None,
    ) -> "GoogleCalendar":
        from google.oauth2 import service_account  # type: ignore[import]

        scopes = scopes or ["https://www.googleapis.com/auth/calendar"]
        creds = service_account.Credentials.from_service_account_file(json_path, scopes=scopes)
        if delegate:
            creds = creds.with_subject(delegate)
        return cls(credentials=creds)

    @classmethod
    def from_oauth2(
        cls,
        credentials_path: str = "credentials.json",
        token_path: str = "token.json",
        scopes: list[str] | None = None,
    ) -> "GoogleCalendar":
        import os

        from google.auth.transport.requests import Request  # type: ignore[import]
        from google.oauth2.credentials import Credentials  # type: ignore[import]
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import]

        scopes = scopes or ["https://www.googleapis.com/auth/calendar"]
        creds: Any = None

        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, scopes)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, scopes)
                creds = flow.run_local_server(port=0)
            with open(token_path, "w") as token:
                token.write(creds.to_json())

        return cls(credentials=creds)

    # ─── AbstractCalendar implementation ──────────────────────────────────────

    async def get_available_slots(
        self,
        date_str: str,
        duration_minutes: int = 30,
        calendar_id: str = "primary",
    ) -> list[TimeSlot]:
        """Query freebusy API for the given day and return open slots."""
        from datetime import date

        day = datetime.strptime(date_str, "%Y-%m-%d")
        time_min = day.replace(hour=8, minute=0, second=0).isoformat() + "Z"
        time_max = day.replace(hour=18, minute=0, second=0).isoformat() + "Z"

        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": calendar_id}],
        }

        def _query() -> Any:
            return self._service.freebusy().query(body=body).execute()

        result = await asyncio.get_event_loop().run_in_executor(None, _query)
        busy_periods: list[dict[str, str]] = result.get("calendars", {}).get(calendar_id, {}).get("busy", [])

        # Build all potential slots (every 30 min from 08:00 to 18:00)
        slots: list[TimeSlot] = []
        current = day.replace(hour=8, minute=0, second=0)
        end_of_day = day.replace(hour=18, minute=0, second=0)

        while current + timedelta(minutes=duration_minutes) <= end_of_day:
            slot_end = current + timedelta(minutes=duration_minutes)
            is_busy = any(
                datetime.fromisoformat(b["start"].replace("Z", "+00:00")).replace(tzinfo=None) < slot_end
                and datetime.fromisoformat(b["end"].replace("Z", "+00:00")).replace(tzinfo=None) > current
                for b in busy_periods
            )
            slots.append(TimeSlot(start=current, end=slot_end, available=not is_busy))
            current = slot_end

        return [s for s in slots if s.available]

    async def create_event(self, appointment: Appointment) -> str:
        duration = int((appointment.end - appointment.start).total_seconds() / 60)
        event_body: dict[str, Any] = {
            "summary": appointment.service or f"Appointment — {appointment.attendee_name}",
            "description": appointment.notes or "",
            "start": {
                "dateTime": appointment.start.isoformat(),
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": appointment.end.isoformat(),
                "timeZone": "UTC",
            },
            "attendees": [],
        }
        if appointment.attendee_email:
            event_body["attendees"].append({"email": appointment.attendee_email})

        def _create() -> Any:
            return (
                self._service.events()
                .insert(calendarId="primary", body=event_body, sendUpdates="all")
                .execute()
            )

        result = await asyncio.get_event_loop().run_in_executor(None, _create)
        return result.get("id", "")

    async def delete_event(self, event_id: str, calendar_id: str = "primary") -> bool:
        def _delete() -> None:
            self._service.events().delete(calendarId=calendar_id, eventId=event_id).execute()

        try:
            await asyncio.get_event_loop().run_in_executor(None, _delete)
            return True
        except Exception:
            return False
