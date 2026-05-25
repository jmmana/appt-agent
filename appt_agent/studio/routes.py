"""
appt_agent.studio.routes
~~~~~~~~~~~~~~~~~~~~~~~~~
Web UI routes for the studio panel (Jinja2 pages + config API endpoints).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from appt_agent.studio.config_store import ConfigStore

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter()


def _render(name: str, ctx: dict[str, Any]):  # type: ignore[return]
    """Starlette 0.41+ TemplateResponse adapter.
    Old API: TemplateResponse(name, {"request": req, ...}) is broken in 0.41+.
    New API: TemplateResponse(request=req, name=name, context={...}).
    """
    req = ctx.get("request")
    context = {k: v for k, v in ctx.items() if k != "request"}
    return templates.TemplateResponse(request=req, name=name, context=context)


def _get_store(request: Request) -> ConfigStore:
    return request.app.state.config_store


def _get_agent(request: Request) -> Any:
    return request.app.state.live_agent


def _agent_ready(config: dict[str, Any]) -> bool:
    return bool(config["llm"].get("api_key") or config["llm"]["provider"] == "ollama")


def _base_ctx(request: Request, config: dict[str, Any], page: str) -> dict[str, Any]:
    return {
        "request":     request,
        "active_page": page,
        "config":      config,
        "agent_ready": _agent_ready(config),
        "flash":       None,
    }


# ─── Dashboard ────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    store  = _get_store(request)
    config = await store.to_agent_config()

    agent  = _get_agent(request)
    if agent and agent._tracker:
        stats = await agent._tracker.get_global_stats()
    else:
        stats = {"total_conversations": 0, "total_appointments": 0,
                 "total_input_tokens": 0, "total_output_tokens": 0,
                 "total_cost_usd": 0.0, "total_messages": 0}

    ctx = _base_ctx(request, config, "dashboard")
    ctx["stats"] = stats
    return _render("dashboard.html", ctx)


# ─── LLM config ───────────────────────────────────────────────────────────────

@router.get("/studio/llm", response_class=HTMLResponse)
async def llm_page(request: Request) -> HTMLResponse:
    store  = _get_store(request)
    config = await store.to_agent_config()
    ctx    = _base_ctx(request, config, "llm")
    return _render("llm.html", ctx)


@router.post("/studio/llm")
async def save_llm(request: Request) -> JSONResponse:
    body     = await request.json()
    provider = body.get("provider", "anthropic")
    model    = body.get("model", "")
    api_key  = body.get("api_key", "")
    # Normalize base_url: strip whitespace + collapse double slashes after scheme
    raw_url  = body.get("base_url", "").strip()
    import re as _re
    base_url = _re.sub(r'(?<!:)/{2,}', '/', raw_url)  # fix //foo → /foo (not https://)
    base_url = base_url.rstrip("/")
    store    = _get_store(request)
    data: dict[str, str] = {"llm_provider": provider, "llm_base_url": base_url, "llm_model": model}
    if api_key:
        data["llm_api_key"] = api_key
    await store.set_many(data)
    # Reload agent with new config
    await _reload_agent(request)
    return JSONResponse({"ok": True})


@router.post("/studio/llm/test")
async def test_llm(request: Request) -> JSONResponse:
    body = await request.json()
    provider = body.get("provider", "anthropic")
    model    = body.get("model", "")
    api_key  = body.get("api_key", "")
    base_url = body.get("base_url", "") or None

    try:
        from appt_agent.llm.base import get_provider
        cls = get_provider(provider)
        kwargs: dict[str, Any] = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        if model:
            kwargs["model"] = model

        llm = cls(**kwargs)
        from appt_agent.models import Message, Role
        resp = await llm.chat(
            [Message(role=Role.USER, content="Say 'OK' in one word.")],
            max_tokens=10,
        )
        return JSONResponse({"ok": True, "model": llm.model, "reply": resp.content[:50]})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)})


# ─── Business config ──────────────────────────────────────────────────────────

@router.get("/studio/business", response_class=HTMLResponse)
async def business_page(request: Request) -> HTMLResponse:
    store  = _get_store(request)
    config = await store.to_agent_config()
    ctx    = _base_ctx(request, config, "business")
    return _render("business.html", ctx)


@router.post("/studio/business")
async def save_business(request: Request) -> JSONResponse:
    body = await request.json()
    store = _get_store(request)
    await store.set_many({
        "business_name":      body.get("business_name", ""),
        "appointment_duration": str(body.get("appointment_duration", 30)),
        "required_slots":     json.dumps(body.get("required_slots", ["name", "date", "time"])),
    })
    await _reload_agent(request)
    return JSONResponse({"ok": True})


# ─── Intents CRUD ─────────────────────────────────────────────────────────────

@router.get("/studio/intents", response_class=HTMLResponse)
async def intents_page(request: Request) -> HTMLResponse:
    store   = _get_store(request)
    config  = await store.to_agent_config()
    intents = await store.list_intents()
    ctx     = _base_ctx(request, config, "intents")
    ctx["intents"] = intents
    return _render("intents.html", ctx)


@router.post("/studio/intents")
async def create_intent(request: Request) -> JSONResponse:
    body  = await request.json()
    store = _get_store(request)
    await store.upsert_intent(
        name=body["name"],
        description=body.get("description", ""),
        webhook=body.get("webhook") or None,
        webhook_secret=body.get("webhook_secret") or None,
        active=body.get("active", True),
    )
    await _reload_agent(request)
    return JSONResponse({"ok": True})


@router.post("/studio/intents/{intent_id}")
async def update_intent(intent_id: int, request: Request) -> JSONResponse:
    body  = await request.json()
    store = _get_store(request)
    await store.upsert_intent(
        name=body["name"],
        description=body.get("description", ""),
        webhook=body.get("webhook") or None,
        webhook_secret=body.get("webhook_secret") or None,
        active=body.get("active", True),
        intent_id=intent_id,
    )
    await _reload_agent(request)
    return JSONResponse({"ok": True})


@router.delete("/studio/intents/{intent_id}")
async def delete_intent(intent_id: int, request: Request) -> JSONResponse:
    store = _get_store(request)
    await store.delete_intent(intent_id)
    await _reload_agent(request)
    return JSONResponse({"ok": True})


# ─── Test chat ────────────────────────────────────────────────────────────────

@router.get("/studio/chat", response_class=HTMLResponse)
async def chat_page(request: Request) -> HTMLResponse:
    store  = _get_store(request)
    config = await store.to_agent_config()
    ctx    = _base_ctx(request, config, "chat")
    return _render("chat.html", ctx)


@router.get("/test", response_class=HTMLResponse)
async def test_chat_page() -> HTMLResponse:
    """Standalone test chat — network picker + chat UI, no sidebar.
    Served as raw HTML (no Jinja2 processing needed — no template variables).
    """
    html_path = _TEMPLATES_DIR / "test_chat.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


# ─── Logs ────────────────────────────────────────────────────────────────────

@router.get("/studio/logs", response_class=HTMLResponse)
async def logs_page(request: Request) -> HTMLResponse:
    store  = _get_store(request)
    config = await store.to_agent_config()
    agent  = _get_agent(request)

    stats = {"total_conversations": 0, "total_appointments": 0,
             "total_input_tokens": 0, "total_output_tokens": 0, "total_cost_usd": 0.0}
    conversations: list[dict[str, Any]] = []

    if agent and agent._tracker:
        stats = await agent._tracker.get_global_stats()
        async with agent._tracker._conn.execute(
            "SELECT * FROM token_summary ORDER BY last_updated DESC LIMIT 100"
        ) as cur:
            rows = await cur.fetchall()
        conversations = [dict(r) for r in rows]

    ctx = _base_ctx(request, config, "logs")
    ctx["stats"] = stats
    ctx["conversations"] = conversations
    return _render("logs.html", ctx)


# ─── Agent hot-reload ────────────────────────────────────────────────────────

async def _reload_agent(request: Request) -> None:
    """Rebuild the BookingAgent from current stored config and attach to app.state."""
    store  = _get_store(request)
    config = await store.to_agent_config()

    if not config["llm"]["api_key"] and config["llm"]["provider"] != "ollama":
        return  # Can't build without credentials

    try:
        from appt_agent import BookingAgentBuilder, Intent
        from appt_agent.llm.base import get_provider
        from pathlib import Path

        llm_cfg  = config["llm"]
        data_dir = Path(request.app.state.tokens_db).parent

        kwargs: dict[str, Any] = {}
        if llm_cfg.get("api_key"):
            kwargs["api_key"] = llm_cfg["api_key"]
        if llm_cfg.get("base_url"):
            kwargs["base_url"] = llm_cfg["base_url"]
        if llm_cfg.get("model"):
            kwargs["model"] = llm_cfg["model"]

        builder = (
            BookingAgentBuilder()
            .with_llm(llm_cfg["provider"], **kwargs)
            .with_business_name(config["business_name"])
            .with_appointment_duration(config["appointment_duration"])
            .with_required_slots(config["required_slots"])
            .with_token_tracking(request.app.state.tokens_db)
        )

        # ── Attach saved calendar ──────────────────────────────────────────
        token_file   = data_dir / "google_token.json"
        service_file = data_dir / "google_service_account.json"
        creds_file   = data_dir / "google_credentials.json"

        if token_file.exists() and creds_file.exists():
            # Google OAuth2 already authorized
            try:
                from appt_agent.calendars.google_cal import GoogleCalendar
                builder.with_calendar_instance(
                    GoogleCalendar.from_oauth2(
                        credentials_path=str(creds_file),
                        token_path=str(token_file),
                    )
                )
            except Exception as _e:
                pass

        elif service_file.exists():
            try:
                from appt_agent.calendars.google_cal import GoogleCalendar
                delegate = await store.get("google_service_delegate")
                builder.with_calendar_instance(
                    GoogleCalendar.from_service_account(
                        json_path=str(service_file),
                        delegate=delegate or None,
                    )
                )
            except Exception as _e:
                pass

        # Outlook
        oc_id  = await store.get("outlook_client_id")
        oc_sec = await store.get("outlook_client_secret")
        oc_tid = await store.get("outlook_tenant_id")
        oc_em  = await store.get("outlook_user_email")
        if oc_id and oc_sec and oc_tid and oc_em:
            try:
                from appt_agent.calendars.outlook_cal import OutlookCalendar
                builder.with_calendar_instance(
                    OutlookCalendar(client_id=oc_id, client_secret=oc_sec,
                                    tenant_id=oc_tid, user_email=oc_em)
                )
            except Exception as _e:
                pass

        # MCP
        mcp_url = await store.get("mcp_server_url")
        mcp_cmd = await store.get("mcp_command")
        if mcp_url or mcp_cmd:
            try:
                from appt_agent.calendars.mcp_cal import MCPCalendar
                env_str = await store.get("mcp_env", "{}")
                mcp_env = json.loads(env_str) if env_str else {}
                if mcp_url:
                    builder.with_calendar_instance(MCPCalendar(server_url=mcp_url))
                else:
                    builder.with_calendar_instance(
                        MCPCalendar(command=mcp_cmd.split(), env=mcp_env)
                    )
            except Exception as _e:
                pass
        # ──────────────────────────────────────────────────────────────────

        for intent in config["intents"]:
            builder.with_intent(Intent(
                name=intent["name"],
                description=intent["description"],
                webhook=intent.get("webhook"),
                webhook_secret=intent.get("webhook_secret"),
            ))

        old_agent = request.app.state.live_agent
        if old_agent:
            await old_agent.shutdown()

        new_agent = builder.build()
        await new_agent.startup()
        request.app.state.live_agent = new_agent

    except Exception as exc:
        import logging
        logging.getLogger("appt_agent.studio").warning("Agent reload failed: %s", exc)
