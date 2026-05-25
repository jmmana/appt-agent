"""
appt_agent.llm.meta_llm
~~~~~~~~~~~~~~~~~~~~~~~~
Ollama / Open WebUI — auto-detects which API path to use.
No extra pip install needed beyond httpx (already a core dep).

Usage:
    # Bare Ollama (local or remote)
    .with_llm("ollama", model="llama3.2", base_url="http://localhost:11434")

    # Open WebUI (add /api to the base URL, pass the WebUI API key)
    .with_llm("ollama", model="llama3.2",
              base_url="https://ollama.example.com/api",
              api_key="sk-xxx")
"""
from __future__ import annotations

from typing import Any

from appt_agent.llm.base import AbstractLLM, register_provider
from appt_agent.models import LLMResponse, Message, Role

# Paths tried in order (relative to base_url).
# Covers all common Ollama / Open WebUI layouts regardless of how much
# of the path the user included in base_url.
_CANDIDATE_PATHS = (
    "v1/chat/completions",       # bare Ollama ≥0.1.24 at root
    "api/v1/chat/completions",   # bare Ollama ≥0.1.24 at root (user omitted /api)
    "chat/completions",          # Open WebUI when base_url ends with /api
    "api/chat/completions",      # Open WebUI when base_url is the root domain
)
_RETRY_STATUSES  = {404, 405, 422}  # 400 may mean wrong model, not wrong path


@register_provider("ollama")
@register_provider("openwebui")
@register_provider("meta")
class OllamaLLM(AbstractLLM):
    """Ollama / Open WebUI — free, local/self-hosted, no cost estimate.

    Auto-detects whether the server is bare Ollama or Open WebUI:
      • bare Ollama  → tries /v1/chat/completions first
      • Open WebUI   → falls back to /chat/completions (relative to /api base)

    The first successful path is cached for the lifetime of the instance.

    If your server requires auth (OLLAMA_API_KEY or Open WebUI API key),
    pass api_key=<token> — sent as 'Authorization: Bearer <token>'.
    """
    provider = "ollama"

    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str = "http://localhost:11434",
        api_key: str = "",
        **kwargs: Any,
    ) -> None:
        import httpx

        self.model = model
        # Strip whitespace + collapse double-slashes (common paste mistakes)
        import re as _re
        clean = base_url.strip()
        clean = _re.sub(r'(?<!:)/{2,}', '/', clean)   # // → / except after scheme
        clean = clean.rstrip("/") + "/"                 # ensure exactly one trailing /
        self._base_url = clean
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=self._base_url, timeout=120.0, headers=headers
        )
        self._working_path: str | None = None  # cached after first successful call

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
            "model":       self.model,
            "messages":    oai_messages,
            "stream":      False,
            "temperature": temperature,
            "max_tokens":  max_tokens,
        }

        # Use cached path if already discovered
        if self._working_path:
            resp = await self._client.post(self._working_path, json=payload)
            resp.raise_for_status()
            return self._parse(resp.json())

        # Auto-detect: try each candidate path until one succeeds
        last_resp = None
        for path in _CANDIDATE_PATHS:
            resp = await self._client.post(path, json=payload)
            if resp.status_code not in _RETRY_STATUSES:
                resp.raise_for_status()
                self._working_path = path   # cache for next calls
                return self._parse(resp.json())
            last_resp = resp

        # All paths failed — raise the last error
        assert last_resp is not None
        last_resp.raise_for_status()
        return self._parse(last_resp.json())  # unreachable, satisfies type checker

    def _parse(self, data: dict[str, Any]) -> LLMResponse:
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
        return 0.0  # Local / self-hosted model — no cost
