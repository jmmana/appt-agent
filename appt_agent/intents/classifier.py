"""
appt_agent.intents.classifier
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
LLM-based intent classifier.
Returns the best matching intent name + confidence score (0-1).
"""
from __future__ import annotations

import json
import re

from appt_agent.llm.base import AbstractLLM
from appt_agent.models import Intent, Message, Role

_CLASSIFY_SYSTEM = """\
You are an intent classification assistant. Given a user message and a list of
possible intents, identify the best matching intent.

Return ONLY valid JSON (no markdown):
{
  "intent": "intent_name or null if none match",
  "confidence": 0.0-1.0
}

If confidence is below 0.4, use null for intent.
"""

_CLASSIFY_USER = """\
User message: "{message}"

Available intents:
{intents_block}

Classify the message. Return JSON only.
"""


async def classify_intent(
    llm: AbstractLLM,
    message: str,
    intents: list[Intent],
    threshold: float = 0.4,
) -> tuple[str | None, float]:
    """
    Returns (intent_name_or_None, confidence).
    Uses LLM to classify. Falls back to None if no intents configured.
    """
    if not intents:
        return None, 0.0

    intents_block = "\n".join(
        f'  - "{i.name}": {i.description}' for i in intents
    )
    user_content = _CLASSIFY_USER.format(
        message=message,
        intents_block=intents_block,
    )

    response = await llm.chat(
        messages=[Message(role=Role.USER, content=user_content)],
        system=_CLASSIFY_SYSTEM,
        temperature=0.0,
        max_tokens=128,
    )

    raw = response.content.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
        name = data.get("intent")
        conf = float(data.get("confidence", 0.0))
    except (json.JSONDecodeError, ValueError, TypeError):
        return None, 0.0

    if conf < threshold or not name:
        return None, conf

    # Validate name is in our known intents
    known = {i.name for i in intents}
    if name not in known:
        return None, 0.0

    return name, conf
