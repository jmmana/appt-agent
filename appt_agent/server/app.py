"""
appt_agent.server.app
~~~~~~~~~~~~~~~~~~~~~~
FastAPI application factory.

Usage
-----
# In your code:
from appt_agent.server import create_app, serve
app = create_app(agent)

# Or run directly:
from appt_agent.server import serve
serve(agent, port=8000)
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from appt_agent.server.routes import router

if TYPE_CHECKING:
    from appt_agent.agent import BookingAgent


def create_app(agent: "BookingAgent", cors_origins: list[str] | None = None) -> FastAPI:
    """
    Create and configure a FastAPI app wrapping the given BookingAgent.

    Parameters
    ----------
    agent : BookingAgent
        A fully configured BookingAgent (from BookingAgentBuilder.build()).
    cors_origins : list[str] | None
        CORS allowed origins. Defaults to ["*"] for development.
    """
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        await agent.startup()
        yield
        await agent.shutdown()

    app = FastAPI(
        title="appt-agent",
        description=(
            "Conversational appointment booking agent API. "
            "POST /chat to interact, GET /stats for token usage."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # Store agent on app state so routes can access it
    app.state.agent = agent

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router, prefix="")
    return app


def serve(
    agent: "BookingAgent",
    host: str = "0.0.0.0",
    port: int = 8000,
    reload: bool = False,
    cors_origins: list[str] | None = None,
    **uvicorn_kwargs: Any,
) -> None:
    """
    Start a uvicorn server with the BookingAgent.

    Parameters
    ----------
    agent : BookingAgent
    host  : str        default "0.0.0.0"
    port  : int        default 8000
    reload: bool       enable hot reload (dev mode)
    """
    try:
        import uvicorn  # type: ignore[import]
    except ImportError:
        raise ImportError("Install server deps: pip install appt-agent[server]") from None

    app = create_app(agent, cors_origins=cors_origins)
    uvicorn.run(app, host=host, port=port, reload=reload, **uvicorn_kwargs)
