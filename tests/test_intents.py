"""Tests for intent classifier."""
import pytest

from appt_agent.intents.classifier import classify_intent
from appt_agent.models import Intent
from tests.conftest import MockLLM


@pytest.mark.asyncio
async def test_classify_no_intents() -> None:
    llm  = MockLLM()
    name, conf = await classify_intent(llm, "Quiero una cita", intents=[])
    assert name is None
    assert conf == 0.0


@pytest.mark.asyncio
async def test_classify_valid_intent() -> None:
    # LLM returns JSON with known intent
    llm = MockLLM('{"intent": "reservar_cita", "confidence": 0.95}')
    intents = [
        Intent("reservar_cita", "Book appointment"),
        Intent("cancelar_cita", "Cancel appointment"),
    ]
    name, conf = await classify_intent(llm, "Quiero agendar una cita", intents=intents)
    assert name == "reservar_cita"
    assert conf == pytest.approx(0.95)


@pytest.mark.asyncio
async def test_classify_low_confidence() -> None:
    llm = MockLLM('{"intent": "reservar_cita", "confidence": 0.2}')
    intents = [Intent("reservar_cita", "Book appointment")]
    name, conf = await classify_intent(llm, "...", intents=intents)
    assert name is None   # below threshold


@pytest.mark.asyncio
async def test_classify_unknown_intent() -> None:
    llm = MockLLM('{"intent": "unknown_thing", "confidence": 0.99}')
    intents = [Intent("reservar_cita", "Book appointment")]
    name, conf = await classify_intent(llm, "...", intents=intents)
    assert name is None   # not in known intents


@pytest.mark.asyncio
async def test_classify_malformed_json() -> None:
    llm  = MockLLM("not json at all")
    intents = [Intent("reservar_cita", "Book")]
    name, conf = await classify_intent(llm, "Hola", intents=intents)
    assert name is None
