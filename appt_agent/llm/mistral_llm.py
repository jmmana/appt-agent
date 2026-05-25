"""
appt_agent.llm.mistral_llm
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Mistral AI adapter.  pip install appt-agent[mistral]
"""
from __future__ import annotations

from typing import Any

from appt_agent.llm.base import AbstractLLM, register_provider
from appt_agent.models import LLMResponse, Message, Role

_PRICING: dict[str, tuple[float, float]] = {
    "mistral-large-latest":  (2.00,  6.00),
    "mistral-small-latest":  (0.20,  0.60),
    "open-mistral-nemo":     (0.15,  0.15),
    "codestral-latest":      (0.20,  0.60),
}
_DEFAULT_MODEL = "mistral-small-latest"


@register_provider("mistral")
class MistralLLM(AbstractLLM):
    provider = "mistral"

    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL, **kwargs: Any) -> None:
        try:
            from mistralai import Mistral  # type: ignore[import]
        except ImportError:
            raise ImportError("Install mistral SDK: pip install appt-agent[mistral]") from None

        self.model   = model
        self._client = Mistral(api_key=api_key)

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

        response = await self._client.chat.complete_async(
            model=self.model,
            messages=sdk_messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
        )
        usage   = response.usage
        content = response.choices[0].message.content or ""
        return LLMResponse(
            content=content,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=self.model,
            provider=self.provider,
        )

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        in_price, out_price = _PRICING.get(self.model, (0.20, 0.60))
        return (input_tokens * in_price + output_tokens * out_price) / 1_000_000
