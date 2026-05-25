"""
appt_agent.calendars.mcp_cal
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
MCP-based calendar adapter.

Connects to any MCP server that exposes calendar tools:
  - get_available_slots(date, duration_minutes) → list[slot]
  - create_event(appointment) → event_id
  - delete_event(event_id) → bool

The adapter communicates via MCP JSON-RPC over stdio or HTTP/SSE.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from appt_agent.calendars.base import AbstractCalendar, register_calendar
from appt_agent.models import Appointment, TimeSlot


@register_calendar("mcp")
class MCPCalendar(AbstractCalendar):
    """
    Wraps an MCP server that exposes calendar tools.

    Parameters
    ----------
    server_url : str
        HTTP/SSE endpoint of the MCP server, e.g. "http://localhost:3000/mcp".
        Leave None to use stdio transport (command + args required).
    command : list[str] | None
        For stdio transport: command to launch the MCP server process,
        e.g. ["npx", "google-calendar-mcp"].
    env : dict | None
        Extra env vars passed to the subprocess.
    """
    provider = "mcp"

    def __init__(
        self,
        server_url: str | None = None,
        command: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not server_url and not command:
            raise ValueError("MCPCalendar requires either server_url or command")
        self._server_url = server_url
        self._command    = command
        self._env        = env or {}
        self._timeout    = timeout
        self._client: Any = None

    async def _ensure_client(self) -> Any:
        """Lazily initialize MCP client."""
        if self._client is not None:
            return self._client

        try:
            import httpx
        except ImportError:
            raise ImportError("httpx is required for MCPCalendar: pip install httpx") from None

        if self._server_url:
            # HTTP transport — send JSON-RPC requests directly
            self._client = httpx.AsyncClient(base_url=self._server_url, timeout=self._timeout)
        else:
            # Stdio transport — spawn subprocess, communicate via stdin/stdout
            self._client = await self._spawn_stdio()

        return self._client

    async def _spawn_stdio(self) -> Any:
        """Start MCP server as subprocess and return a simple stdio wrapper."""
        import asyncio
        import os

        env = {**os.environ, **self._env}
        proc = await asyncio.create_subprocess_exec(
            *self._command,  # type: ignore[arg-type]
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            env=env,
        )
        return _StdioMCPClient(proc)

    async def _call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        client = await self._ensure_client()

        if isinstance(client, _StdioMCPClient):
            return await client.call_tool(tool_name, arguments)

        # HTTP/SSE transport — plain JSON-RPC
        import httpx
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        resp = await client.post("/", json=payload)
        resp.raise_for_status()
        result = resp.json()
        if "error" in result:
            raise RuntimeError(f"MCP error: {result['error']}")
        return result.get("result", {})

    # ─── AbstractCalendar ──────────────────────────────────────────────────────

    async def get_available_slots(
        self,
        date_str: str,
        duration_minutes: int = 30,
        calendar_id: str = "primary",
    ) -> list[TimeSlot]:
        result = await self._call_tool("get_available_slots", {
            "date": date_str,
            "duration_minutes": duration_minutes,
            "calendar_id": calendar_id,
        })
        slots = []
        for item in result.get("slots", []):
            slots.append(TimeSlot(
                start=datetime.fromisoformat(item["start"]),
                end=datetime.fromisoformat(item["end"]),
                available=item.get("available", True),
            ))
        return slots

    async def create_event(self, appointment: Appointment) -> str:
        result = await self._call_tool("create_event", {
            "attendee_name":  appointment.attendee_name,
            "attendee_email": appointment.attendee_email,
            "service":        appointment.service,
            "start":          appointment.start.isoformat(),
            "end":            appointment.end.isoformat(),
            "notes":          appointment.notes,
        })
        return result.get("event_id", "")

    async def delete_event(self, event_id: str, calendar_id: str = "primary") -> bool:
        result = await self._call_tool("delete_event", {
            "event_id": event_id,
            "calendar_id": calendar_id,
        })
        return bool(result.get("success", False))


class _StdioMCPClient:
    """Minimal stdio JSON-RPC client for MCP subprocess."""

    def __init__(self, proc: Any) -> None:
        self._proc = proc
        self._id   = 0

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        import asyncio
        import json

        self._id += 1
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": self._id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }) + "\n"

        self._proc.stdin.write(payload.encode())
        await self._proc.stdin.drain()

        line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=30.0)
        result = json.loads(line.decode())
        if "error" in result:
            raise RuntimeError(f"MCP stdio error: {result['error']}")
        return result.get("result", {})
