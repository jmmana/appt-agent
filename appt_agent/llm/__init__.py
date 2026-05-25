"""
appt_agent.llm
~~~~~~~~~~~~~~
LLM provider adapters. Import all adapters here so the @register_provider
decorators run and populate the registry when this package is imported.
"""
from appt_agent.llm.base import AbstractLLM, get_provider, register_provider

# Eager imports register all built-in providers
from appt_agent.llm.anthropic_llm import AnthropicLLM  # noqa: F401
from appt_agent.llm.openai_llm import (    # noqa: F401
    DeepSeekLLM,
    GroqLLM,
    OpenAILLM,
    XaiLLM,
)
from appt_agent.llm.google_llm import GoogleLLM    # noqa: F401
from appt_agent.llm.meta_llm import OllamaLLM      # noqa: F401
from appt_agent.llm.mistral_llm import MistralLLM  # noqa: F401
from appt_agent.llm.cohere_llm import CohereLLM    # noqa: F401
from appt_agent.llm.bedrock_llm import BedrockLLM  # noqa: F401

__all__ = [
    "AbstractLLM",
    "get_provider",
    "register_provider",
    "AnthropicLLM",
    "OpenAILLM",
    "DeepSeekLLM",
    "XaiLLM",
    "GroqLLM",
    "GoogleLLM",
    "OllamaLLM",
    "MistralLLM",
    "CohereLLM",
    "BedrockLLM",
]
