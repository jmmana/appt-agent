"""
appt_agent.engine.slot_filler
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Uses the LLM to extract appointment slots from the user message.
Returns a dict with any of: name, date, time, service, email.
Missing fields are None.
"""
from __future__ import annotations

import json
import re
from typing import Any

from appt_agent.llm.base import AbstractLLM
from appt_agent.models import Message, Role

_EXTRACT_SYSTEM = """\
You are a data extraction assistant. The user wants to book an appointment.
Extract the following fields from the conversation (return JSON only, no explanation):

{{
  "name":    "Full name of the person, or null",
  "date":    "Date in ISO format YYYY-MM-DD, or null",
  "time":    "Time in HH:MM 24h format, or null",
  "service": "Type of service/appointment requested, or null",
  "email":   "Email address, or null"
}}

Rules:
- Return ONLY valid JSON. No markdown fences.
- If a field cannot be determined, use null.
- For relative dates like "tomorrow", "next Tuesday", resolve them relative to today: {today}.
- For times like "3pm" -> "15:00", "morning" -> null (too vague).
"""

_EXTRACT_USER = """\
Conversation so far:
{history}

Latest user message: {message}

Extract the fields. Return JSON only.
"""


async def extract_slots(
    llm: AbstractLLM,
    message: str,
    history: list[Message],
    today: str,
    existing_slots: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Extract appointment slots from the current message + history.
    Merges with existing_slots (existing non-null values win unless user corrects them).
    """
    history_text = "\n".join(
        f"{m.role.value.upper()}: {m.content}"
        for m in history[-6:]  # last 3 turns
        if m.role in (Role.USER, Role.ASSISTANT)
    )

    system = _EXTRACT_SYSTEM.format(today=today)
    user_msg = _EXTRACT_USER.format(history=history_text, message=message)

    response = await llm.chat(
        messages=[Message(role=Role.USER, content=user_msg)],
        system=system,
        temperature=0.0,
        max_tokens=256,
    )

    raw = response.content.strip()
    # Strip markdown fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        extracted: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        extracted = {}

    # Merge: new non-null values override; keep existing if new is null
    merged = dict(existing_slots or {})
    for key in ("name", "date", "time", "service", "email"):
        new_val = extracted.get(key)
        if new_val is not None:
            merged[key] = new_val
        elif key not in merged:
            merged[key] = None

    return merged


def missing_slots(slots: dict[str, Any], required: list[str] | None = None) -> list[str]:
    """Return list of required slot names that are still None."""
    required = required or ["name", "date", "time"]
    return [k for k in required if not slots.get(k)]
