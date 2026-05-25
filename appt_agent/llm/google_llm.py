"""
appt_agent.llm.google_llm
~~~~~~~~~~~~~~~~~~~~~~~~~~
Google Gemini adapter.  pip install appt-agent[google]
"""
from __future__ import annotations

from typing import Any

from appt_agent.llm.base import AbstractLLM, register_provider
from appt_agent.models import LLMResponse, Message, Role

_PRICING: dict[str, tuple[float, float]] = {
    "gemini-2.0-flash":         (0.10,  0.40),
    "gemini-2.0-flash-lite":    (0.075, 0.30),
    "gemini-1.5-pro":           (1.25,  5.00),
    "gemini-1.5-flash":         (0.075, 0.30),
    "gemini-1.5-flash-8b":      (0.0375, 0.15),
}
_DEFAULT_MODEL = "gemini-2.0-flash"


@register_provider("google")
@register_provider("gemini")
class GoogleLLM(AbstractLLM):
    provider = "google"

    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL, **kwargs: Any) -> None:
        try:
            import google.generativeai as genai  # type: ignore[import]
        except ImportError:
            raise ImportError("Install google SDK: pip install appt-agent[google]") from None

        self.model = model
        genai.configure(api_key=api_key)
        self._genai = genai

    async def chat(
        self,
        messages: list[Message],
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> LLMResponse:
        import asyncio

        gen_model = self._genai.GenerativeModel(
            model_name=self.model,
            system_instruction=system,
            generation_config=self._genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )

        # Build history (all but last user message)
        history = []
        for m in messages[:-1]:
            if m.role in (Role.USER, Role.ASSISTANT):
                history.append({
                    "role": "user" if m.role == Role.USER else "model",
                    "parts": [m.content],
                })

        chat_session = gen_model.start_chat(history=history)
        last_msg = messages[-1].content if messages else ""

        # google-generativeai is sync; run in thread
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: chat_session.send_message(last_msg)
        )

        usage = response.usage_metadata
        return LLMResponse(
            content=response.text,
            input_tokens=usage.prompt_token_count if usage else 0,
            output_tokens=usage.candidates_token_count if usage else 0,
            model=self.model,
            provider=self.provider,
        )

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        in_price, out_price = _PRICING.get(self.model, (0.10, 0.40))
        return (input_tokens * in_price + output_tokens * out_price) / 1_000_000
