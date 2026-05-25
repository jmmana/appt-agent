"""Tests for SQLite TokenTracker."""
import pytest
import pytest_asyncio

from appt_agent.storage.tracker import TokenTracker


@pytest_asyncio.fixture
async def tracker(tmp_path):  # type: ignore[no-untyped-def]
    db = str(tmp_path / "test_tokens.db")
    async with TokenTracker(db) as t:
        yield t


@pytest.mark.asyncio
async def test_ensure_conversation(tracker: TokenTracker) -> None:
    await tracker.ensure_conversation("sess-1", metadata={"user": "juan"})
    # Second call must not raise (INSERT OR IGNORE)
    await tracker.ensure_conversation("sess-1")


@pytest.mark.asyncio
async def test_save_message_and_summary(tracker: TokenTracker) -> None:
    await tracker.save_message("sess-2", "user",      "Hola",         input_tokens=5)
    await tracker.save_message("sess-2", "assistant", "¿En qué ayudo?", input_tokens=10, output_tokens=20, cost_usd=0.0005)

    summary = await tracker.get_token_summary("sess-2")
    assert summary is not None
    assert summary.total_input_tokens  == 15
    assert summary.total_output_tokens == 20
    assert summary.message_count       == 2


@pytest.mark.asyncio
async def test_get_messages(tracker: TokenTracker) -> None:
    await tracker.save_message("sess-3", "user", "Primera")
    await tracker.save_message("sess-3", "assistant", "Respuesta")
    msgs = await tracker.get_messages("sess-3")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"


@pytest.mark.asyncio
async def test_log_intent(tracker: TokenTracker) -> None:
    await tracker.ensure_conversation("sess-4")
    await tracker.log_intent("sess-4", "reservar_cita", confidence=0.9, webhook_url="https://x.com/hook")
    await tracker.mark_webhook_sent("sess-4", "reservar_cita")


@pytest.mark.asyncio
async def test_global_stats_empty(tracker: TokenTracker) -> None:
    stats = await tracker.get_global_stats()
    assert "total_conversations" in stats
    assert stats["total_cost_usd"] == 0.0


@pytest.mark.asyncio
async def test_update_state(tracker: TokenTracker) -> None:
    await tracker.ensure_conversation("sess-5")
    await tracker.update_state("sess-5", "booked")
