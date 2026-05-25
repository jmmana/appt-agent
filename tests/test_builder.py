"""Tests for BookingAgentBuilder."""
import pytest

from appt_agent import BookingAgentBuilder, Intent
from appt_agent.agent import BookingAgent
from tests.conftest import MockLLM


def test_build_minimal() -> None:
    agent = BookingAgentBuilder().with_llm_instance(MockLLM()).build()
    assert isinstance(agent, BookingAgent)


def test_build_requires_llm() -> None:
    with pytest.raises(ValueError, match="No LLM configured"):
        BookingAgentBuilder().build()


def test_with_intents() -> None:
    agent = (
        BookingAgentBuilder()
        .with_llm_instance(MockLLM())
        .with_intent(Intent("reservar", "Book an appointment"))
        .with_intent(Intent("cancelar", "Cancel"))
        .build()
    )
    assert len(agent._intents) == 2
    assert agent._intents[0].name == "reservar"


def test_with_business_name() -> None:
    agent = (
        BookingAgentBuilder()
        .with_llm_instance(MockLLM())
        .with_business_name("My Clinic")
        .build()
    )
    assert agent._business == "My Clinic"


def test_with_required_slots() -> None:
    agent = (
        BookingAgentBuilder()
        .with_llm_instance(MockLLM())
        .with_required_slots(["name", "date", "time", "service"])
        .build()
    )
    assert "service" in agent._required


def test_with_appointment_duration() -> None:
    agent = (
        BookingAgentBuilder()
        .with_llm_instance(MockLLM())
        .with_appointment_duration(60)
        .build()
    )
    assert agent._duration == 60


def test_with_token_tracking(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db = str(tmp_path / "test.db")
    agent = (
        BookingAgentBuilder()
        .with_llm_instance(MockLLM())
        .with_token_tracking(db)
        .build()
    )
    assert agent._tracker is not None
