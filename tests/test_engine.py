"""Tests for ConversationEngine (state machine + slot filler)."""
import pytest

from appt_agent.engine.conversation import ConversationEngine
from appt_agent.engine.slot_filler import extract_slots, missing_slots
from appt_agent.models import Conversation, ConversationState, Message, Role
from tests.conftest import MockLLM, SlotLLM


# ─── slot_filler ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_slots_full() -> None:
    llm = SlotLLM('{"name":"Juan","date":"2026-06-01","time":"15:00","service":"Consulta","email":null}')
    slots = await extract_slots(llm, "Soy Juan, quiero el 1 de junio a las 3pm", [], "2026-05-25")
    assert slots["name"]    == "Juan"
    assert slots["date"]    == "2026-06-01"
    assert slots["time"]    == "15:00"
    assert slots["service"] == "Consulta"


@pytest.mark.asyncio
async def test_extract_slots_partial() -> None:
    llm = SlotLLM('{"name":"Maria","date":null,"time":null,"service":null,"email":null}')
    slots = await extract_slots(llm, "Soy Maria", [], "2026-05-25")
    assert slots["name"] == "Maria"
    assert slots["date"] is None


@pytest.mark.asyncio
async def test_extract_slots_merges_existing() -> None:
    llm = SlotLLM('{"name":null,"date":"2026-06-05","time":"10:00","service":null,"email":null}')
    slots = await extract_slots(
        llm, "El viernes a las 10", [], "2026-05-25",
        existing_slots={"name": "Pedro", "date": None, "time": None}
    )
    assert slots["name"] == "Pedro"      # kept from existing
    assert slots["date"] == "2026-06-05" # new


def test_missing_slots_all_present() -> None:
    assert missing_slots({"name": "X", "date": "2026-01-01", "time": "09:00"}) == []


def test_missing_slots_partial() -> None:
    missing = missing_slots({"name": "X", "date": None, "time": "09:00"})
    assert "date" in missing


# ─── ConversationEngine ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_engine_greeting_to_collect() -> None:
    llm    = MockLLM("¿A nombre de quién?")
    engine = ConversationEngine(llm=llm)
    conv   = Conversation(id="s1")
    reply, _ = await engine.process(conv, "Quiero una cita")
    assert conv.state == ConversationState.COLLECT_INFO


@pytest.mark.asyncio
async def test_engine_full_flow_to_booked() -> None:
    """Simulate a full conversation: info → confirm → booked."""
    # LLM 1: slot extraction (full JSON)
    # LLM 2: confirmation (any string; engine checks user message, not LLM)
    slot_llm = SlotLLM('{"name":"Ana","date":"2026-06-10","time":"14:00","service":"Consulta","email":null}')
    engine   = ConversationEngine(llm=slot_llm)
    conv     = Conversation(id="s2")

    # Turn 1: user provides all info
    reply, _ = await engine.process(conv, "Soy Ana, quiero el 10 de junio a las 2pm")
    assert conv.state == ConversationState.CONFIRM
    assert "Ana" in reply

    # Turn 2: user confirms
    reply, _ = await engine.process(conv, "yes")
    assert conv.state == ConversationState.BOOKED
    assert "confirmed" in reply.lower() or "✅" in reply


@pytest.mark.asyncio
async def test_engine_cancel_flow() -> None:
    slot_llm = SlotLLM('{"name":"Luis","date":"2026-06-12","time":"10:00","service":null,"email":null}')
    engine   = ConversationEngine(llm=slot_llm)
    conv     = Conversation(id="s3")

    await engine.process(conv, "Soy Luis, el 12 de junio a las 10")
    assert conv.state == ConversationState.CONFIRM

    reply, _ = await engine.process(conv, "no")
    assert conv.state == ConversationState.CANCELLED
    assert not conv.slots  # slots cleared


@pytest.mark.asyncio
async def test_engine_booked_is_terminal() -> None:
    llm  = MockLLM()
    engine = ConversationEngine(llm=llm)
    conv   = Conversation(id="s4", state=ConversationState.BOOKED)
    reply, _ = await engine.process(conv, "anything")
    assert conv.state == ConversationState.BOOKED
    assert "already booked" in reply.lower()
