"""Tests for WebhookDispatcher."""
import hashlib
import hmac
import json

import pytest
import respx
import httpx

from appt_agent.models import WebhookPayload
from appt_agent.webhooks.dispatcher import WebhookDispatcher


@pytest.fixture
def dispatcher() -> WebhookDispatcher:
    return WebhookDispatcher(timeout=5.0)


@pytest.fixture
def payload() -> WebhookPayload:
    return WebhookPayload(
        event="intent.reservar_cita",
        intent_name="reservar_cita",
        session_id="test-session",
        slots={"name": "Juan", "date": "2026-06-01", "time": "15:00"},
    )


@pytest.mark.asyncio
@respx.mock
async def test_dispatch_success(dispatcher: WebhookDispatcher, payload: WebhookPayload) -> None:
    url = "https://example.com/webhook"
    respx.post(url).mock(return_value=httpx.Response(200))

    success = await dispatcher.dispatch(payload, url)
    assert success is True


@pytest.mark.asyncio
@respx.mock
async def test_dispatch_non_2xx_retries(dispatcher: WebhookDispatcher, payload: WebhookPayload) -> None:
    url = "https://example.com/webhook"
    # Always 500
    respx.post(url).mock(return_value=httpx.Response(500))

    success = await dispatcher.dispatch(payload, url)
    # All retries failed → False
    assert success is False
    assert respx.calls.call_count == 3  # _MAX_RETRIES


@pytest.mark.asyncio
@respx.mock
async def test_dispatch_with_hmac(dispatcher: WebhookDispatcher, payload: WebhookPayload) -> None:
    url    = "https://example.com/webhook"
    secret = "my-secret-key"
    captured_headers: dict = {}

    def capture(request: httpx.Request) -> httpx.Response:
        captured_headers.update(dict(request.headers))
        return httpx.Response(200)

    respx.post(url).mock(side_effect=capture)
    await dispatcher.dispatch(payload, url, secret=secret)

    sig = captured_headers.get("x-signature-256", "")
    assert sig.startswith("sha256=")

    # Verify manually
    body = payload.model_dump_json().encode()
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert sig == expected


def test_verify_signature_valid(dispatcher: WebhookDispatcher) -> None:
    secret = "abc"
    body   = b'{"event": "test"}'
    sig    = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert WebhookDispatcher.verify_signature(body, sig, secret) is True


def test_verify_signature_invalid(dispatcher: WebhookDispatcher) -> None:
    assert WebhookDispatcher.verify_signature(b"body", "sha256=wrong", "secret") is False
