"""
appt_agent.llm.bedrock_llm
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Amazon Bedrock adapter (Converse API — model-agnostic).
pip install appt-agent[bedrock]

Supports: Claude on Bedrock, Llama on Bedrock, Titan, Mistral on Bedrock, etc.
"""
from __future__ import annotations

import json
from typing import Any

from appt_agent.llm.base import AbstractLLM, register_provider
from appt_agent.models import LLMResponse, Message, Role

# Cross-region inference profiles (recommended)
_DEFAULT_MODEL = "us.anthropic.claude-3-5-sonnet-20241022-v2:0"

_PRICING: dict[str, tuple[float, float]] = {
    "us.anthropic.claude-3-5-sonnet-20241022-v2:0": (3.00,  15.00),
    "us.anthropic.claude-3-5-haiku-20241022-v1:0":  (0.80,   4.00),
    "us.meta.llama3-3-70b-instruct-v1:0":           (0.72,   0.72),
    "us.mistral.mistral-large-2407-v1:0":           (3.00,   9.00),
    "amazon.titan-text-express-v1":                 (0.20,   0.60),
}


@register_provider("bedrock")
class BedrockLLM(AbstractLLM):
    provider = "bedrock"

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        region_name: str = "us-east-1",
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            import boto3  # type: ignore[import]
        except ImportError:
            raise ImportError("Install boto3: pip install appt-agent[bedrock]") from None

        self.model    = model
        session_kwargs: dict[str, Any] = {"region_name": region_name}
        if aws_access_key_id:
            session_kwargs["aws_access_key_id"]     = aws_access_key_id
            session_kwargs["aws_secret_access_key"] = aws_secret_access_key
        # Use run_in_executor for sync boto3 client
        self._session = boto3.Session(**session_kwargs)
        self._client  = self._session.client("bedrock-runtime")

    async def chat(
        self,
        messages: list[Message],
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> LLMResponse:
        import asyncio

        sdk_messages = [
            {"role": m.role.value, "content": [{"text": m.content}]}
            for m in messages
            if m.role in (Role.USER, Role.ASSISTANT)
        ]
        params: dict[str, Any] = dict(
            modelId=self.model,
            messages=sdk_messages,
            inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
        )
        if system:
            params["system"] = [{"text": system}]

        def _call() -> Any:
            return self._client.converse(**params)

        response = await asyncio.get_event_loop().run_in_executor(None, _call)

        content = response["output"]["message"]["content"][0]["text"]
        usage   = response.get("usage", {})
        return LLMResponse(
            content=content,
            input_tokens=usage.get("inputTokens", 0),
            output_tokens=usage.get("outputTokens", 0),
            model=self.model,
            provider=self.provider,
        )

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        in_price, out_price = _PRICING.get(self.model, (3.00, 15.00))
        return (input_tokens * in_price + output_tokens * out_price) / 1_000_000
