"""
appt_agent.llm.openai_llm
~~~~~~~~~~~~~~~~~~~~~~~~~~
OpenAI GPT adapter — also covers OpenAI-compatible APIs:
  deepseek  → base_url="https://api.deepseek.com"
  xai       → base_url="https://api.x.ai/v1"
  groq      → base_url="https://api.groq.com/openai/v1"

pip install appt-agent[openai]
"""
from __future__ import annotations

from typing import Any

from appt_agent.llm.base import AbstractLLM, register_provider
from appt_agent.models import LLMResponse, Message, Role

_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o":              (2.50,  10.00),
    "gpt-4o-mini":         (0.15,   0.60),
    "gpt-4-turbo":         (10.00, 30.00),
    "gpt-3.5-turbo":       (0.50,   1.50),
    # DeepSeek
    "deepseek-chat":       (0.14,   0.28),
    "deepseek-reasoner":   (0.55,   2.19),
    # Groq (Llama on Groq infra)
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "mixtral-8x7b-32768":      (0.24, 0.24),
    # xAI Grok
    "grok-2-1212":         (2.00,  10.00),
    "grok-beta":           (5.00,  15.00),
}
_DEFAULT_MODEL = "gpt-4o-mini"


def _make_provider_class(
    key: str,
    default_model: str,
    default_base_url: str | None = None,
) -> type[AbstractLLM]:
    """Factory that generates a registered provider class for OpenAI-compatible APIs."""

    @register_provider(key)
    class _OAICompatLLM(AbstractLLM):
        provider = key

        def __init__(
            self,
            api_key: str,
            model: str = default_model,
            base_url: str | None = default_base_url,
            **kwargs: Any,
        ) -> None:
            try:
                from openai import AsyncOpenAI  # type: ignore[import]
            except ImportError:
                raise ImportError("Install openai SDK: pip install appt-agent[openai]") from None

            self.model   = model
            self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

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

            response = await self._client.chat.completions.create(
                model=self.model,
                messages=sdk_messages,  # type: ignore[arg-type]
                temperature=temperature,
                max_tokens=max_tokens,
            )
            usage = response.usage
            return LLMResponse(
                content=response.choices[0].message.content or "",
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
                model=self.model,
                provider=self.provider,
            )

        def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
            in_price, out_price = _PRICING.get(self.model, (1.00, 2.00))
            return (input_tokens * in_price + output_tokens * out_price) / 1_000_000

    _OAICompatLLM.__name__ = f"{key.capitalize()}LLM"
    return _OAICompatLLM


# Register all OpenAI-compatible providers
OpenAILLM   = _make_provider_class("openai",   "gpt-4o-mini")
DeepSeekLLM = _make_provider_class("deepseek", "deepseek-chat",       "https://api.deepseek.com")
XaiLLM      = _make_provider_class("xai",      "grok-2-1212",         "https://api.x.ai/v1")
GroqLLM     = _make_provider_class("groq",     "llama-3.3-70b-versatile", "https://api.groq.com/openai/v1")
