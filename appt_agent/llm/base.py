"""
appt_agent.llm.base
~~~~~~~~~~~~~~~~~~~
Abstract protocol that all LLM adapters must implement.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from appt_agent.models import LLMResponse, Message


class AbstractLLM(ABC):
    """Base class for all LLM provider adapters."""

    provider: str = "unknown"
    model: str    = "unknown"

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a chat request and return a structured response with token counts."""
        ...

    @abstractmethod
    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Return estimated cost in USD for the given token counts."""
        ...

    def build_system_prompt(self, base: str, intents: list[str]) -> str:
        """Helper to inject intent descriptions into system prompt."""
        if not intents:
            return base
        intent_block = "\n".join(f"  - {i}" for i in intents)
        return f"{base}\n\nIntents you must recognize:\n{intent_block}"


# ─── Registry ─────────────────────────────────────────────────────────────────

_REGISTRY: dict[str, type[AbstractLLM]] = {}


def register_provider(name: str) -> Any:
    """Class decorator to register an LLM provider by key name."""
    def decorator(cls: type[AbstractLLM]) -> type[AbstractLLM]:
        _REGISTRY[name] = cls
        return cls
    return decorator


def get_provider(name: str) -> type[AbstractLLM]:
    if name not in _REGISTRY:
        available = ", ".join(_REGISTRY.keys())
        raise ValueError(
            f"LLM provider '{name}' not found. Available: {available}\n"
            f"Make sure you installed the optional dependency, e.g. pip install appt-agent[{name}]"
        )
    return _REGISTRY[name]
