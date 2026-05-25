"""
appt_agent.llm.anthropic_llm
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Anthropic Claude adapter.  pip install appt-agent[anthropic]
"""
from __future__ import annotations

from typing import Any

from appt_agent.llm.base import AbstractLLM, register_provider
from appt_agent.models import LLMResponse, Message, Role

# Pricing per 1M tokens (USD) — updated 2025
_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-7":        (15.00, 75.00),
    "claude-sonnet-4-6":      (3.00,  15.00),
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    "claude-haiku-4-5":       (0.80,  4.00),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-5-haiku-20241022":  (0.80,  4.00),
}
_DEFAULT_MODEL = "claude-sonnet-4-6"


@register_provider("anthropic")
class AnthropicLLM(AbstractLLM):
    provider = "anthropic"

    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL, **kwargs: Any) -> None:
        try:
            import anthropic as sdk  # type: ignore[import]
        except ImportError:
            raise ImportError("Install anthropic SDK: pip install appt-agent[anthropic]") from None

        self.model   = model
        self._client = sdk.AsyncAnthropic(api_key=api_key)
        self._sdk    = sdk

    async def chat(
        self,
        messages: list[Message],
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> LLMResponse:
        sdk_messages = [
            {"role": m.role.value, "content": m.content}
            for m in messages
            if m.role in (Role.USER, Role.ASSISTANT)
        ]

        params: dict[str, Any] = dict(
            model=self.model,
            messages=sdk_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if system:
            params["system"] = system

        response = await self._client.messages.create(**params)
        content  = response.content[0].text
        usage    = response.usage

        return LLMResponse(
            content=content,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            model=self.model,
            provider=self.provider,
        )

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        in_price, out_price = _PRICING.get(self.model, (3.00, 15.00))
        return (input_tokens * in_price + output_tokens * out_price) / 1_000_000
