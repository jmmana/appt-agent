"""
python -m appt_agent --help

CLI entry point. Starts the FastAPI server from a config file or env vars.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="appt-agent",
        description="Start the appt-agent booking server",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable hot reload")
    parser.add_argument("--demo", action="store_true", help="Run with mock LLM (no API key needed)")

    args = parser.parse_args()

    if args.demo:
        _run_demo(args.host, args.port, args.reload)
    else:
        print(
            "appt-agent: build a BookingAgent in your code and call serve(agent).\n"
            "See: https://github.com/jmmana/appt-agent#quickstart\n"
            "Or run with --demo for a mock server."
        )
        sys.exit(0)


def _run_demo(host: str, port: int, reload: bool) -> None:
    """Launch a demo server with an echo LLM — no real API key required."""
    print("🗓️  appt-agent demo mode — using mock LLM (no calendar or API keys)")

    from appt_agent import BookingAgentBuilder, Intent
    from appt_agent.llm.base import AbstractLLM, register_provider
    from appt_agent.models import LLMResponse, Message

    @register_provider("mock")
    class MockLLM(AbstractLLM):
        provider = "mock"
        model    = "mock-1"

        def __init__(self, **kwargs: object) -> None: ...

        async def chat(self, messages: list[Message], **kwargs: object) -> LLMResponse:
            last = messages[-1].content if messages else ""
            return LLMResponse(
                content=f"[DEMO] I received: {last[:80]}... How can I help you book an appointment?",
                input_tokens=10,
                output_tokens=20,
                model=self.model,
                provider=self.provider,
            )

        def estimate_cost(self, i: int, o: int) -> float:
            return 0.0

    agent = (
        BookingAgentBuilder()
        .with_llm("mock")
        .with_intent(Intent("reservar_cita", "User wants to book an appointment", webhook=None))
        .with_intent(Intent("cancelar_cita", "User wants to cancel an appointment", webhook=None))
        .with_token_tracking("demo_tokens.db")
        .with_business_name("Demo Business")
        .build()
    )

    from appt_agent.server import serve
    print(f"🚀 Starting demo server at http://{host}:{port}")
    print("   POST /chat  →  {\"session_id\": \"test\", \"message\": \"Hola\"}")
    serve(agent, host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
