"""
Shared fixtures for all tests.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from appt_agent import BookingAgentBuilder, Intent
from appt_agent.llm.base import AbstractLLM, register_provider
from appt_agent.models import LLMResponse, Message


# ─── Mock LLM ─────────────────────────────────────────────────────────────────

class MockLLM(AbstractLLM):
    """Deterministic LLM for tests — returns a configurable canned response."""
    provider = "mock"
    model    = "mock-1"

    def __init__(self, response: str = "Hello! How can I help?") -> None:
        self._response = response
        self.calls: list[list[Message]] = []

    async def chat(self, messages: list[Message], **kwargs: object) -> LLMResponse:
        self.calls.append(messages)
        return LLMResponse(
            content=self._response,
            input_tokens=10,
            output_tokens=20,
            model=self.model,
            provider=self.provider,
        )

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return 0.0


# ─── Slot-extracting mock ──────────────────────────────────────────────────────

class SlotLLM(AbstractLLM):
    """Returns a JSON slot payload to simulate extraction."""
    provider = "mock-slot"
    model    = "mock-slot-1"

    def __init__(self, slots_json: str) -> None:
        self._slots_json = slots_json

    async def chat(self, messages: list[Message], **kwargs: object) -> LLMResponse:
        return LLMResponse(
            content=self._slots_json,
            input_tokens=5,
            output_tokens=15,
            model=self.model,
            provider=self.provider,
        )

    def estimate_cost(self, i: int, o: int) -> float:
        return 0.0


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_llm() -> MockLLM:
    return MockLLM("I can help you book an appointment!")


@pytest.fixture
def basic_intents() -> list[Intent]:
    return [
        Intent("reservar_cita",  "User wants to book an appointment"),
        Intent("cancelar_cita",  "User wants to cancel an appointment"),
        Intent("consultar_cita", "User wants to check their appointment"),
    ]


@pytest.fixture
def basic_agent(mock_llm: MockLLM, basic_intents: list[Intent], tmp_path):  # type: ignore[no-untyped-def]
    db = str(tmp_path / "test_tokens.db")
    return (
        BookingAgentBuilder()
        .with_llm_instance(mock_llm)
        .with_intents(*basic_intents)
        .with_token_tracking(db)
        .with_business_name("Test Clinic")
        .build()
    )
