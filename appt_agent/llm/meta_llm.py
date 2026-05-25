"""
appt_agent.llm.meta_llm
~~~~~~~~~~~~~~~~~~~~~~~~
Meta Llama via Ollama — uses Ollama's OpenAI-compatible API.
No extra pip install needed beyond httpx (already a core dep).

Usage:
    .with_llm("ollama", model="llama3.2", base_url="https://ollama.example.com")
    .with_llm("ollama", model="llama3.2", base_url="https://ollama.example.com",
              api_key="sk-xxx")   # if server uses OLLAMA_API_KEY auth
"""
from __future__ import annotations

from typing import Any

from appt_agent.llm.base import AbstractLLM, register_provider
from appt_agent.models import LLMResponse, Message, Role


@register_provider("ollama")
@register_provider("meta")
class OllamaLLM(AbstractLLM):
    """Llama via Ollama — free, local, no cost estimate.

    Uses Ollama's OpenAI-compatible endpoint (/v1/chat/completions) which
    works correctly through HTTPS reverse-proxies (avoids 405 on /api/chat).
    If your Ollama server has auth enabled (OLLAMA_API_KEY env var), pass
    api_key=<token> — it will be sent as 'Authorization: Bearer <token>'.
    """
    provider = "ollama"

    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str = "http://localhost:11434",
        api_key: str = "",   # Optional: Bearer token for protected Ollama servers
        **kwargs: Any,
    ) -> None:
        import httpx

        self.model     = model
        self._base_url = base_url.rstrip("/")
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=self._base_url, timeout=120.0, headers=headers
        )

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

        # OpenAI-compatible endpoint — supported by Ollama ≥0.1.24
        # Works through HTTPS proxies; avoids 405 that /api/chat can trigger.
        payload = {
            "model":       self.model,
            "messages":    oai_messages,
            "stream":      False,
            "temperature": temperature,
            "max_tokens":  max_tokens,
        }
        resp = await self._client.post("/v1/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()

        content = data["choices"][0]["message"]["content"]
        usage   = data.get("usage", {})
        return LLMResponse(
            content=content,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            model=data.get("model", self.model),
            provider=self.provider,
        )

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return 0.0  # Local model — no cost
