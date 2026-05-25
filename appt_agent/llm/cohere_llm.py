"""
appt_agent.llm.cohere_llm
~~~~~~~~~~~~~~~~~~~~~~~~~~
Cohere Command R adapter.  pip install appt-agent[cohere]
"""
from __future__ import annotations

from typing import Any

from appt_agent.llm.base import AbstractLLM, register_provider
from appt_agent.models import LLMResponse, Message, Role

_PRICING: dict[str, tuple[float, float]] = {
    "command-r-plus-08-2024": (2.50,  10.00),
    "command-r-08-2024":      (0.15,   0.60),
    "command-r7b-12-2024":    (0.0375, 0.15),
}
_DEFAULT_MODEL = "command-r-08-2024"


@register_provider("cohere")
class CohereLLM(AbstractLLM):
    provider = "cohere"

    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL, **kwargs: Any) -> None:
        try:
            import cohere  # type: ignore[import]
        except ImportError:
            raise ImportError("Install cohere SDK: pip install appt-agent[cohere]") from None

        self.model   = model
        self._client = cohere.AsyncClientV2(api_key=api_key)

    async def chat(
        self,
        messages: list[Message],
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> LLMResponse:
        sdk_messages: list[dict[str, str]] = []
        if system:
            sdk_messages.append({"role": "system", "content": system})
        sdk_messages += [
            {"role": m.role.value, "content": m.content}
            for m in messages
            if m.role in (Role.USER, Role.ASSISTANT)
        ]

        response = await self._client.chat(
            model=self.model,
            messages=sdk_messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
        )
        usage   = response.usage
        content = response.message.content[0].text if response.message.content else ""
        return LLMResponse(
            content=content,
            input_tokens=usage.tokens.input_tokens if usage and usage.tokens else 0,
            output_tokens=usage.tokens.output_tokens if usage and usage.tokens else 0,
            model=self.model,
            provider=self.provider,
        )

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        in_price, out_price = _PRICING.get(self.model, (0.15, 0.60))
        return (input_tokens * in_price + output_tokens * out_price) / 1_000_000
