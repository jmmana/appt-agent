"""
appt_agent.studio.app
~~~~~~~~~~~~~~~~~~~~~~
Multi-tenant Studio FastAPI application.

  - /studio/* → web UI (Jinja2 config panel), scoped via ?b=<business_id>
  - /chat      → booking API, accepts business_id in body or ?b= query param
  - /docs      → Swagger UI
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from appt_agent.models import ChatRequest, ChatResponse
from appt_agent.studio.config_store import ConfigStore, DEFAULT_BUSINESS_ID
from appt_agent.studio.routes import router as studio_router, _reload_agent
from appt_agent.studio.routes_calendar import router as cal_router


def create_studio_app(
    data_dir: str | Path = "/data",
    cors_origins: list[str] | None = None,
) -> FastAPI:
    data_dir  = Path(data_dir)
    studio_db = str(data_dir / "studio.db")
    store     = ConfigStore(db_path=studio_db)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        await store.connect()
        app.state.config_store = store
        app.state.data_dir     = str(data_dir)
        app.state.agents       = {}   # dict[business_id, BookingAgent]

        # Build agents for all configured businesses
        class _FakeReq:
            def __init__(self, a: FastAPI) -> None: self.app = a
        fake = _FakeReq(app)
        businesses = await store.list_businesses()
        for biz in businesses:
            await _reload_agent(fake, biz["id"])  # type: ignore[arg-type]

        yield

        for agent in app.state.agents.values():
            await agent.shutdown()
        await store.close()

    app = FastAPI(
        title="appt-agent studio",
        description="Panel de configuración multi-negocio + API para agentes de citas",
        version="0.2.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Chat endpoint (multi-business) ───────────────────────────────
    @app.post("/chat", response_model=ChatResponse, tags=["Chat"])
    async def chat_dynamic(body: ChatRequest, request: Request) -> ChatResponse:
        # business_id from: body field > ?b= query param > default
        bid = (
            getattr(body, "business_id", None)
            or request.query_params.get("b")
            or DEFAULT_BUSINESS_ID
        )
        agent = request.app.state.agents.get(bid)
        if not agent:
            return JSONResponse(
                status_code=503,
                content={"detail": f"Agente '{bid}' no configurado. Configura el LLM en /studio/llm?b={bid}"},
            )
        return await agent.chat(
            session_id=body.session_id,
            message=body.message,
            metadata=body.metadata,
        )

    # ── Stats / monitoring (per business) ───────────────────────────
    @app.get("/stats", tags=["Monitoring"])
    async def stats(request: Request, b: str = DEFAULT_BUSINESS_ID) -> dict[str, Any]:
        agent = request.app.state.agents.get(b)
        if not agent or not agent._tracker:
            return {"message": "Agente no configurado o tracking deshabilitado"}
        return await agent._tracker.get_global_stats()

    @app.get("/conversations/{session_id}", tags=["Monitoring"])
    async def get_conversation(
        session_id: str, request: Request, b: str = DEFAULT_BUSINESS_ID
    ) -> dict[str, Any]:
        agent = request.app.state.agents.get(b)
        if not agent or not agent._tracker:
            return {"error": "Token tracking no habilitado"}
        messages = await agent._tracker.get_messages(session_id)
        conv     = agent.get_conversation(session_id)
        return {
            "session_id": session_id,
            "state":      conv.state.value if conv else "unknown",
            "slots":      conv.slots if conv else {},
            "messages":   messages,
        }

    @app.get("/conversations/{session_id}/tokens", tags=["Monitoring"])
    async def get_tokens(
        session_id: str, request: Request, b: str = DEFAULT_BUSINESS_ID
    ) -> Any:
        agent = request.app.state.agents.get(b)
        if not agent or not agent._tracker:
            return {"error": "Token tracking no habilitado"}
        summary = await agent._tracker.get_token_summary(session_id)
        return summary.model_dump() if summary else {"error": "Sin datos"}

    @app.get("/health", tags=["Monitoring"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/agent-status", tags=["Monitoring"])
    async def agent_status(request: Request, b: str = DEFAULT_BUSINESS_ID) -> dict[str, Any]:
        agent = request.app.state.agents.get(b)
        businesses = await store.list_businesses()
        return {
            "ready":      bool(agent),
            "business_id": b,
            "businesses": [biz["id"] for biz in businesses],
            "active_agents": list(request.app.state.agents.keys()),
        }

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
    try:
        import uvicorn
    except ImportError:
        raise ImportError("pip install appt-agent[server]") from None
    data_dir = data_dir or os.environ.get("APPT_DATA_DIR", "/data")
    app = create_studio_app(data_dir=data_dir)
    uvicorn.run(app, host=host, port=port, reload=reload, **kwargs)
