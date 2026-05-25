"""
appt_agent.server.routes
~~~~~~~~~~~~~~~~~~~~~~~~~
FastAPI route definitions for the appt-agent server.

Endpoints
---------
POST /chat                          — send a user message
GET  /conversations/{id}            — get conversation history
GET  /conversations/{id}/tokens     — token usage for a session
GET  /stats                         — global aggregate stats
POST /webhooks/test                 — manually trigger a webhook
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from appt_agent.models import ChatRequest, ChatResponse, Intent, WebhookPayload

router = APIRouter()


def _get_agent(request: Request) -> Any:
    """Retrieve the BookingAgent stored in app.state."""
    return request.app.state.agent


# ─── Chat ─────────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse, summary="Send a user message")
async def chat(body: ChatRequest, agent: Any = Depends(_get_agent)) -> ChatResponse:
    """
    Process a user message within a session.

    - `session_id`: unique identifier for the conversation (e.g. user ID, phone number)
    - `message`: the user's natural-language message
    """
    return await agent.chat(
        session_id=body.session_id,
        message=body.message,
        metadata=body.metadata,
    )


# ─── Conversations ────────────────────────────────────────────────────────────

@router.get("/conversations/{session_id}", summary="Get conversation history")
async def get_conversation(session_id: str, agent: Any = Depends(_get_agent)) -> dict[str, Any]:
    """Return full message history and current state for a session."""
    tracker = agent._tracker
    if not tracker:
        raise HTTPException(status_code=404, detail="Token tracking not enabled")

    messages = await tracker.get_messages(session_id)
    conv     = agent.get_conversation(session_id)
    return {
        "session_id": session_id,
        "state":      conv.state.value if conv else "unknown",
        "slots":      conv.slots if conv else {},
        "messages":   messages,
    }


@router.get("/conversations/{session_id}/tokens", summary="Token usage for a session")
async def get_token_usage(session_id: str, agent: Any = Depends(_get_agent)) -> dict[str, Any]:
    """Return token consumption and cost estimate for a specific conversation."""
    tracker = agent._tracker
    if not tracker:
        raise HTTPException(status_code=404, detail="Token tracking not enabled")

    summary = await tracker.get_token_summary(session_id)
    if not summary:
        raise HTTPException(status_code=404, detail=f"No data for session '{session_id}'")

    return summary.model_dump()


# ─── Stats ────────────────────────────────────────────────────────────────────

@router.get("/stats", summary="Global aggregate stats")
async def get_stats(agent: Any = Depends(_get_agent)) -> dict[str, Any]:
    """Return aggregate token usage and appointment counts across all sessions."""
    tracker = agent._tracker
    if not tracker:
        return {"message": "Token tracking not enabled"}
    return await tracker.get_global_stats()


# ─── Webhooks ─────────────────────────────────────────────────────────────────

class WebhookTestRequest(BaseModel):
    session_id: str
    intent_name: str
    webhook_url: str
    webhook_secret: str | None = None


@router.post("/webhooks/test", summary="Manually trigger a webhook")
async def test_webhook(
    body: WebhookTestRequest,
    agent: Any = Depends(_get_agent),
) -> dict[str, Any]:
    """
    Send a test webhook payload to a URL.
    Useful for verifying your endpoint handles the payload correctly.
    """
    from appt_agent.webhooks.dispatcher import WebhookDispatcher

    payload = WebhookPayload(
        event=f"intent.{body.intent_name}",
        intent_name=body.intent_name,
        session_id=body.session_id,
    )
    dispatcher = WebhookDispatcher()
    success = await dispatcher.dispatch(
        payload=payload,
        webhook_url=body.webhook_url,
        secret=body.webhook_secret,
    )
    return {"success": success, "webhook_url": body.webhook_url}


# ─── Health ───────────────────────────────────────────────────────────────────

@router.get("/health", summary="Health check")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "appt-agent"}
