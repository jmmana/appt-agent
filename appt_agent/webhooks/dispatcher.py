"""
appt_agent.webhooks.dispatcher
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Async webhook dispatcher with HMAC-SHA256 signing and exponential backoff retry.

The payload is posted as JSON to the configured webhook URL.
The X-Signature-256 header contains: sha256=<hmac_hex>
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from appt_agent.models import WebhookPayload

logger = logging.getLogger("appt_agent.webhooks")

_MAX_RETRIES   = 3
_RETRY_BACKOFF = [1, 3, 10]   # seconds between retries


class WebhookDispatcher:
    """Dispatches webhook POST requests with optional HMAC signing."""

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout

    async def dispatch(
        self,
        payload: WebhookPayload,
        webhook_url: str,
        secret: str | None = None,
    ) -> bool:
        """
        Send payload to webhook_url.
        Returns True if the request succeeded (2xx), False otherwise.
        Retries up to _MAX_RETRIES times with exponential backoff.
        """
        body = payload.model_dump_json()
        headers = self._build_headers(body.encode(), secret)

        for attempt in range(_MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(
                        webhook_url,
                        content=body,
                        headers=headers,
                    )
                    if 200 <= resp.status_code < 300:
                        logger.info(
                            "Webhook delivered: intent=%s url=%s status=%d attempt=%d",
                            payload.intent_name,
                            webhook_url,
                            resp.status_code,
                            attempt + 1,
                        )
                        return True
                    else:
                        logger.warning(
                            "Webhook non-2xx: intent=%s url=%s status=%d attempt=%d",
                            payload.intent_name,
                            webhook_url,
                            resp.status_code,
                            attempt + 1,
                        )
            except httpx.RequestError as exc:
                logger.warning(
                    "Webhook request error: intent=%s url=%s error=%s attempt=%d",
                    payload.intent_name,
                    webhook_url,
                    str(exc),
                    attempt + 1,
                )

            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(_RETRY_BACKOFF[attempt])

        logger.error(
            "Webhook failed after %d attempts: intent=%s url=%s",
            _MAX_RETRIES,
            payload.intent_name,
            webhook_url,
        )
        return False

    def _build_headers(self, body: bytes, secret: str | None) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent":   "appt-agent/0.1.0",
            "X-Timestamp":  datetime.now(UTC).isoformat(),
        }
        if secret:
            sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            headers["X-Signature-256"] = f"sha256={sig}"
        return headers

    @staticmethod
    def verify_signature(body: bytes, signature_header: str, secret: str) -> bool:
        """
        Helper for webhook receivers to verify incoming signatures.
        Use this in your endpoint to validate payloads.
        """
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature_header)
