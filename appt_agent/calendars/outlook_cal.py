"""
appt_agent.calendars.outlook_cal
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Microsoft Outlook / Graph API adapter.
pip install appt-agent[outlook]

Auth: Client Credentials flow (app-only) or Delegated (user token).

Usage
-----
OutlookCalendar(
    client_id="...",
    client_secret="...",
    tenant_id="...",
    user_email="user@domain.com",  # whose calendar to manage
)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import httpx

from appt_agent.calendars.base import AbstractCalendar, register_calendar
from appt_agent.models import Appointment, TimeSlot

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"


@register_calendar("outlook")
@register_calendar("microsoft")
class OutlookCalendar(AbstractCalendar):
    provider = "outlook"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        tenant_id: str,
        user_email: str,
        scopes: list[str] | None = None,
    ) -> None:
        try:
            import msal  # type: ignore[import]
        except ImportError:
            raise ImportError("pip install appt-agent[outlook]") from None

        self._user_email = user_email
        self._scopes     = scopes or ["https://graph.microsoft.com/.default"]

        self._msal_app = msal.ConfidentialClientApplication(
            client_id=client_id,
            client_credential=client_secret,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
        )
        self._token: str | None = None

    async def _get_token(self) -> str:
        def _acquire() -> dict[str, Any]:
            result = self._msal_app.acquire_token_silent(self._scopes, account=None)
            if not result:
                result = self._msal_app.acquire_token_for_client(scopes=self._scopes)
            return result  # type: ignore[return-value]

        result = await asyncio.get_event_loop().run_in_executor(None, _acquire)
        if "access_token" not in result:
            raise RuntimeError(f"MSAL auth failed: {result.get('error_description')}")
        return result["access_token"]

    async def _headers(self) -> dict[str, str]:
        token = await self._get_token()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # ─── AbstractCalendar ──────────────────────────────────────────────────────

    async def get_available_slots(
        self,
        date_str: str,
        duration_minutes: int = 30,
        calendar_id: str = "primary",
    ) -> list[TimeSlot]:
        day = datetime.strptime(date_str, "%Y-%m-%d")
        start_dt = day.replace(hour=8, minute=0, second=0)
        end_dt   = day.replace(hour=18, minute=0, second=0)

        # Use /calendarView to get existing events
        url = f"{_GRAPH_BASE}/users/{self._user_email}/calendarView"
        params = {
            "startDateTime": start_dt.isoformat() + "Z",
            "endDateTime":   end_dt.isoformat() + "Z",
            "$select":       "start,end,subject",
        }

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=await self._headers(), params=params)
            resp.raise_for_status()
            events = resp.json().get("value", [])

        busy = [
            (
                datetime.fromisoformat(e["start"]["dateTime"].rstrip("Z")),
                datetime.fromisoformat(e["end"]["dateTime"].rstrip("Z")),
            )
            for e in events
        ]

        slots: list[TimeSlot] = []
        current = start_dt
        while current + timedelta(minutes=duration_minutes) <= end_dt:
            slot_end  = current + timedelta(minutes=duration_minutes)
            is_busy   = any(b[0] < slot_end and b[1] > current for b in busy)
            slots.append(TimeSlot(start=current, end=slot_end, available=not is_busy))
            current = slot_end

        return [s for s in slots if s.available]

    async def create_event(self, appointment: Appointment) -> str:
        url  = f"{_GRAPH_BASE}/users/{self._user_email}/events"
        body: dict[str, Any] = {
            "subject": appointment.service or f"Appointment — {appointment.attendee_name}",
            "body": {"contentType": "Text", "content": appointment.notes or ""},
            "start": {"dateTime": appointment.start.isoformat(), "timeZone": "UTC"},
            "end":   {"dateTime": appointment.end.isoformat(),   "timeZone": "UTC"},
            "attendees": [],
        }
        if appointment.attendee_email:
            body["attendees"].append({
                "emailAddress": {"address": appointment.attendee_email, "name": appointment.attendee_name},
                "type": "required",
            })

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=await self._headers(), json=body)
            resp.raise_for_status()
            return resp.json().get("id", "")

    async def delete_event(self, event_id: str, calendar_id: str = "primary") -> bool:
        url = f"{_GRAPH_BASE}/users/{self._user_email}/events/{event_id}"
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.delete(url, headers=await self._headers())
                return resp.status_code == 204
            except Exception:
                return False
