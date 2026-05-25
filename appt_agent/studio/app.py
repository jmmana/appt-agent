"""
appt_agent.studio.app
~~~~~~~~~~~~~~~~~~~~~~
Full Studio FastAPI application:
  - /studio/* → web UI (Jinja2 config panel)
  - /chat, /stats, /conversations/* → booking API (re-used from appt_agent.server)
  - /docs → Swagger UI
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from appt_agent.studio.config_store import ConfigStore
from appt_agent.studio.routes import router as studio_router, _reload_agent
from appt_agent.studio.routes_calendar import router as cal_router


def create_studio_app(
    data_dir: str | Path = "/data",
    cors_origins: list[str] | None = None,
) -> FastAPI:
    """
    Create the full studio application.

    data_dir: directory for SQLite files and credential files.
              Set via env var APPT_DATA_DIR (default: /data).
    """
    data_dir   = Path(data_dir)
    studio_db  = str(data_dir / "studio.db")
    tokens_db  = str(data_dir / "tokens.db")
    store      = ConfigStore(db_path=studio_db)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        # Connect config store
        await store.connect()
        app.state.config_store = store
        app.state.tokens_db    = tokens_db
        app.state.live_agent   = None

        # Try to build agent from saved config
        class _FakeReq:
            def __init__(self, app: FastAPI) -> None: self.app = app
        fake = _FakeReq(app)
        await _reload_agent(fake)  # type: ignore[arg-type]

        yield

        # Shutdown
        if app.state.live_agent:
            await app.state.live_agent.shutdown()
        await store.close()

    app = FastAPI(
        title="appt-agent studio",
        description="Panel de configuración + API para agentes de citas",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Override /chat to use the live_agent from state (hot-reloadable)
    from fastapi import Depends
    from appt_agent.models import ChatRequest, ChatResponse

    @app.post("/chat", response_model=ChatResponse, tags=["Chat"])
    async def chat_dynamic(body: ChatRequest, request: Request) -> ChatResponse:
        agent = request.app.state.live_agent
        if not agent:
            return JSONResponse(
                status_code=503,
                content={"detail": "Agent not configured. Set your LLM API key in the studio panel."},
            )
        return await agent.chat(
            session_id=body.session_id,
            message=body.message,
            metadata=body.metadata,
        )

    # Stats and conversation routes use live_agent too
    from appt_agent.models import TokenUsage

    @app.get("/stats", tags=["Monitoring"])
    async def stats(request: Request) -> dict[str, Any]:
        agent = request.app.state.live_agent
        if not agent or not agent._tracker:
            return {"message": "Token tracking not enabled or agent not configured"}
        return await agent._tracker.get_global_stats()

    @app.get("/conversations/{session_id}", tags=["Monitoring"])
    async def get_conversation(session_id: str, request: Request) -> dict[str, Any]:
        agent = request.app.state.live_agent
        if not agent or not agent._tracker:
            return {"error": "Token tracking not enabled"}
        messages = await agent._tracker.get_messages(session_id)
        conv = agent.get_conversation(session_id)
        return {
            "session_id": session_id,
            "state":      conv.state.value if conv else "unknown",
            "slots":      conv.slots if conv else {},
            "messages":   messages,
        }

    @app.get("/conversations/{session_id}/tokens", tags=["Monitoring"])
    async def get_tokens(session_id: str, request: Request) -> Any:
        agent = request.app.state.live_agent
        if not agent or not agent._tracker:
            return {"error": "Token tracking not enabled"}
        summary = await agent._tracker.get_token_summary(session_id)
        return summary.model_dump() if summary else {"error": "No data"}

    @app.get("/health", tags=["Monitoring"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Mount studio UI + calendar routes
    app.include_router(studio_router)
    app.include_router(cal_router)

    return app


def serve(
    data_dir: str | Path | None = None,
    host: str = "0.0.0.0",
    port: int = 8000,
    reload: bool = False,
    **kwargs: Any,
) -> None:
    """Start the studio server."""
    try:
        import uvicorn
    except ImportError:
        raise ImportError("pip install appt-agent[server]") from None

    data_dir = data_dir or os.environ.get("APPT_DATA_DIR", "/data")
    app = create_studio_app(data_dir=data_dir)
    uvicorn.run(app, host=host, port=port, reload=reload, **kwargs)
