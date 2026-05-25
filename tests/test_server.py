"""Tests for FastAPI server endpoints."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from appt_agent import BookingAgentBuilder, Intent
from appt_agent.server.app import create_app
from tests.conftest import MockLLM


@pytest.fixture
def client(tmp_path):  # type: ignore[no-untyped-def]
    db = str(tmp_path / "server_test.db")
    agent = (
        BookingAgentBuilder()
        .with_llm_instance(MockLLM("Hi! Let me help you book."))
        .with_intent(Intent("reservar_cita", "Book"))
        .with_token_tracking(db)
        .build()
    )
    app = create_app(agent)
    # Use TestClient with lifespan=True so startup/shutdown are called automatically
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_chat_endpoint(client: TestClient) -> None:
    resp = client.post("/chat", json={"session_id": "u1", "message": "Hola"})
    assert resp.status_code == 200
    data = resp.json()
    assert "reply" in data
    assert data["session_id"] == "u1"


def test_get_conversation(client: TestClient) -> None:
    # Create a conversation first
    client.post("/chat", json={"session_id": "u2", "message": "Quiero cita"})
    resp = client.get("/conversations/u2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "u2"
    assert "messages" in data


def test_get_tokens(client: TestClient) -> None:
    client.post("/chat", json={"session_id": "u3", "message": "Cita por favor"})
    resp = client.get("/conversations/u3/tokens")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_input_tokens" in data


def test_get_stats(client: TestClient) -> None:
    resp = client.get("/stats")
    assert resp.status_code == 200
    assert "total_conversations" in resp.json()


def test_chat_multiple_turns(client: TestClient) -> None:
    for msg in ["Hola", "Soy Carlos", "Mañana", "10am", "sí"]:
        resp = client.post("/chat", json={"session_id": "u4", "message": msg})
        assert resp.status_code == 200
