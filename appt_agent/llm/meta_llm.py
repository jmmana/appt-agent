"""
appt_agent.llm.meta_llm
~~~~~~~~~~~~~~~~~~~~~~~~
Meta Llama via Ollama (local) — uses OpenAI-compatible API of Ollama.
No extra pip install needed beyond httpx (already a core dep).

Usage:
    .with_llm("ollama", model="llama3.3", base_url="http://localhost:11434")
"""
from __future__ import annotations

from typing import Any

from appt_agent.llm.base import AbstractLLM, register_provider
from appt_agent.models import LLMResponse, Message, Role


@register_provider("ollama")
@register_provider("meta")
class OllamaLLM(AbstractLLM):
    """Llama via Ollama — free, local, no cost estimate."""
    provider = "ollama"

    def __init__(
        self,
        model: str = "llama3.3",
        base_url: str = "http://localhost:11434",
        api_key: str = "ollama",  # Ollama ignores it but httpx needs something
        **kwargs: Any,
    ) -> None:
        import httpx

        self.model    = model
        self._base_url = base_url.rstrip("/")
        self._client  = httpx.AsyncClient(base_url=self._base_url, timeout=120.0)

    async def chat(
        self,
        messages: list[Message],
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> LLMResponse:
        oai_messages: list[dict[str, str]] = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        oai_messages += [
            {"role": m.role.value, "content": m.content}
            for m in messages
            if m.role in (Role.USER, Role.ASSISTANT)
        ]

        payload = {
            "model":      self.model,
            "messages":   oai_messages,
            "stream":     False,
            "options":    {"temperature": temperature, "num_predict": max_tokens},
        }
        resp = await self._client.post("/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()

        content = data.get("message", {}).get("content", "")
        # Ollama returns eval_count / prompt_eval_count
        return LLMResponse(
            content=content,
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            model=self.model,
            provider=self.provider,
        )

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return 0.0  # Local model — no cost
