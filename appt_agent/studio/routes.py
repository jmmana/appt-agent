"""
appt_agent.studio.routes
~~~~~~~~~~~~~~~~~~~~~~~~~
Web UI routes for the studio panel (Jinja2 pages + config API endpoints).
All studio pages are scoped to a business via ?b=<business_id>.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from appt_agent.studio.config_store import ConfigStore, DEFAULT_BUSINESS_ID

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _render(name: str, ctx: dict[str, Any]):  # type: ignore[return]
    req = ctx.get("request")
    context = {k: v for k, v in ctx.items() if k != "request"}
    return templates.TemplateResponse(request=req, name=name, context=context)


def _get_store(request: Request) -> ConfigStore:
    return request.app.state.config_store


def _get_agent(request: Request, business_id: str) -> Any:
    return request.app.state.agents.get(business_id)


def _bid(request: Request) -> str:
    """Extract business_id from query param ?b=, default to 'default'."""
    return request.query_params.get("b", DEFAULT_BUSINESS_ID)


def _agent_ready(config: dict[str, Any]) -> bool:
    return bool(config["llm"].get("api_key") or config["llm"]["provider"] == "ollama")


async def _base_ctx(request: Request, business_id: str, page: str) -> dict[str, Any]:
    store = _get_store(request)
    config = await store.to_agent_config(business_id)
    businesses = await store.list_businesses()
    current_biz = await store.get_business(business_id) or {"id": business_id, "name": "?"}
    return {
        "request":            request,
        "active_page":        page,
        "config":             config,
        "agent_ready":        _agent_ready(config),
        "flash":              None,
        "business_id":        business_id,
        "current_business":   current_biz,
        "businesses":         businesses,
    }


# ─── Dashboard ────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    bid    = _bid(request)
    store  = _get_store(request)
    agent  = _get_agent(request, bid)

    if agent and agent._tracker:
        stats = await agent._tracker.get_global_stats()
    else:
        stats = {"total_conversations": 0, "total_appointments": 0,
                 "total_input_tokens": 0, "total_output_tokens": 0,
                 "total_cost_usd": 0.0, "total_messages": 0}

    ctx = await _base_ctx(request, bid, "dashboard")
    ctx["stats"] = stats
    return _render("dashboard.html", ctx)


# ─── Businesses CRUD ─────────────────────────────────────────────────────────

@router.get("/studio/businesses", response_class=HTMLResponse)
async def businesses_page(request: Request) -> HTMLResponse:
    bid = _bid(request)
    ctx = await _base_ctx(request, bid, "businesses")
    return _render("businesses.html", ctx)


@router.post("/studio/businesses")
async def create_business(request: Request) -> JSONResponse:
    body  = await request.json()
    name  = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"ok": False, "error": "Nombre requerido"}, status_code=400)
    store = _get_store(request)
    bid   = await store.create_business(name)
    return JSONResponse({"ok": True, "business_id": bid})


@router.patch("/studio/businesses/{business_id}")
async def rename_business(business_id: str, request: Request) -> JSONResponse:
    body  = await request.json()
    name  = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"ok": False, "error": "Nombre requerido"}, status_code=400)
    store = _get_store(request)
    await store.rename_business(business_id, name)
    await _reload_agent(request, business_id)
    return JSONResponse({"ok": True})


@router.delete("/studio/businesses/{business_id}")
async def delete_business(business_id: str, request: Request) -> JSONResponse:
    if business_id == DEFAULT_BUSINESS_ID:
        return JSONResponse({"ok": False, "error": "No se puede eliminar el negocio por defecto"}, status_code=400)
    store = _get_store(request)
    await store.delete_business(business_id)
    # Shutdown agent if running
    agent = request.app.state.agents.pop(business_id, None)
    if agent:
        await agent.shutdown()
    return JSONResponse({"ok": True})


# ─── LLM config ───────────────────────────────────────────────────────────────

@router.get("/studio/llm", response_class=HTMLResponse)
async def llm_page(request: Request) -> HTMLResponse:
    bid = _bid(request)
    ctx = await _base_ctx(request, bid, "llm")
    return _render("llm.html", ctx)


@router.post("/studio/llm")
async def save_llm(request: Request) -> JSONResponse:
    bid      = _bid(request)
    body     = await request.json()
    provider = body.get("provider", "anthropic")
    model    = body.get("model", "")
    api_key  = body.get("api_key", "")
    import re as _re
    raw_url  = body.get("base_url", "").strip()
    base_url = _re.sub(r'(?<!:)/{2,}', '/', raw_url).rstrip("/")
    store    = _get_store(request)
    data: dict[str, str] = {"llm_provider": provider, "llm_base_url": base_url, "llm_model": model}
    if api_key:
        data["llm_api_key"] = api_key
    await store.set_many(bid, data)
    await _reload_agent(request, bid)
    return JSONResponse({"ok": True})


@router.post("/studio/llm/test")
async def test_llm(request: Request) -> JSONResponse:
    body     = await request.json()
    provider = body.get("provider", "anthropic")
    model    = body.get("model", "")
    api_key  = body.get("api_key", "")
    base_url = body.get("base_url", "") or None
    try:
        from appt_agent.llm.base import get_provider
        cls = get_provider(provider)
        kwargs: dict[str, Any] = {}
        if api_key:  kwargs["api_key"]  = api_key
        if base_url: kwargs["base_url"] = base_url
        if model:    kwargs["model"]    = model
        llm  = cls(**kwargs)
        from appt_agent.models import Message, Role
        resp = await llm.chat(
            [Message(role=Role.USER, content="Say 'OK' in one word.")],
            max_tokens=10,
        )
        return JSONResponse({"ok": True, "model": llm.model, "reply": resp.content[:50]})
    except Exception as exc:
        error_msg = str(exc)
        try:
            import httpx as _httpx
            if isinstance(exc, _httpx.HTTPStatusError):
                body_text   = exc.response.text
                try:
                    import json as _json
                    body_data   = _json.loads(body_text)
                    body_detail = body_data.get("detail") or body_data.get("message") or body_text
                except Exception:
                    body_detail = body_text
                error_msg = f"{exc.response.status_code} {exc.response.reason_phrase}: {body_detail}"
        except Exception:
            pass
        return JSONResponse({"ok": False, "error": error_msg})


@router.post("/studio/llm/models")
async def list_models(request: Request) -> JSONResponse:
    import httpx as _httpx
    import re as _re
    body     = await request.json()
    base_url = (body.get("base_url", "") or "").strip()
    api_key  = body.get("api_key", "") or ""
    if not base_url:
        return JSONResponse({"ok": False, "error": "base_url requerida"})
    base_url = _re.sub(r'(?<!:)/{2,}', '/', base_url).rstrip("/")
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    base = base_url.rstrip("/")
    endpoints = [
        (base + "/ollama/api/tags",  "ollama"),
        (base + "/api/models",       "openwebui"),
        (base + "/api/tags",         "ollama"),
        (base + "/models",           "openwebui"),
        (base + "/tags",             "ollama"),
    ]
    async with _httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        for url, kind in endpoints:
            try:
                r = await client.get(url)
                if r.status_code == 200:
                    data = r.json()
                    if kind == "openwebui" and "data" in data:
                        names = [m.get("id") or m.get("name") for m in data["data"]]
                    elif kind == "ollama" and "models" in data:
                        names = [m.get("name") for m in data["models"]]
                    else:
                        names = []
                    names = [n for n in names if n]
                    return JSONResponse({"ok": True, "models": sorted(names), "endpoint": url})
                if r.status_code == 401:
                    return JSONResponse({"ok": False, "error": "401 Unauthorized — verifica el API key"})
            except Exception:
                continue
    return JSONResponse({"ok": False, "error": "No se pudo listar modelos — verifica la URL"})


# ─── Business config ──────────────────────────────────────────────────────────

@router.get("/studio/business", response_class=HTMLResponse)
async def business_page(request: Request) -> HTMLResponse:
    bid = _bid(request)
    ctx = await _base_ctx(request, bid, "business")
    return _render("business.html", ctx)


@router.post("/studio/business")
async def save_business(request: Request) -> JSONResponse:
    bid   = _bid(request)
    body  = await request.json()
    store = _get_store(request)
    await store.set_many(bid, {
        "business_name":        body.get("business_name", ""),
        "appointment_duration": str(body.get("appointment_duration", 30)),
        "required_slots":       json.dumps(body.get("required_slots", ["name", "date", "time"])),
    })
    # Also rename the business record
    if name := body.get("business_name", "").strip():
        await store.rename_business(bid, name)
    await _reload_agent(request, bid)
    return JSONResponse({"ok": True})


# ─── Intents CRUD ─────────────────────────────────────────────────────────────

@router.get("/studio/intents", response_class=HTMLResponse)
async def intents_page(request: Request) -> HTMLResponse:
    bid     = _bid(request)
    store   = _get_store(request)
    intents = await store.list_intents(bid)
    ctx     = await _base_ctx(request, bid, "intents")
    ctx["intents"] = intents
    return _render("intents.html", ctx)


@router.post("/studio/intents")
async def create_intent(request: Request) -> JSONResponse:
    bid   = _bid(request)
    body  = await request.json()
    store = _get_store(request)
    await store.upsert_intent(
        business_id=bid,
        name=body["name"],
        description=body.get("description", ""),
        webhook=body.get("webhook") or None,
        webhook_secret=body.get("webhook_secret") or None,
        active=body.get("active", True),
    )
    await _reload_agent(request, bid)
    return JSONResponse({"ok": True})


@router.post("/studio/intents/{intent_id}")
async def update_intent(intent_id: int, request: Request) -> JSONResponse:
    bid   = _bid(request)
    body  = await request.json()
    store = _get_store(request)
    await store.upsert_intent(
        business_id=bid,
        name=body["name"],
        description=body.get("description", ""),
        webhook=body.get("webhook") or None,
        webhook_secret=body.get("webhook_secret") or None,
        active=body.get("active", True),
        intent_id=intent_id,
    )
    await _reload_agent(request, bid)
    return JSONResponse({"ok": True})


@router.delete("/studio/intents/{intent_id}")
async def delete_intent(intent_id: int, request: Request) -> JSONResponse:
    bid   = _bid(request)
    store = _get_store(request)
    await store.delete_intent(bid, intent_id)
    await _reload_agent(request, bid)
    return JSONResponse({"ok": True})


# ─── Test chat ────────────────────────────────────────────────────────────────

@router.get("/studio/chat", response_class=HTMLResponse)
async def chat_page(request: Request) -> HTMLResponse:
    bid = _bid(request)
    ctx = await _base_ctx(request, bid, "chat")
    return _render("chat.html", ctx)


@router.get("/test", response_class=HTMLResponse)
async def test_chat_page() -> HTMLResponse:
    html_path = _TEMPLATES_DIR / "test_chat.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


# ─── Logs ─────────────────────────────────────────────────────────────────────

@router.get("/studio/logs", response_class=HTMLResponse)
async def logs_page(request: Request) -> HTMLResponse:
    bid   = _bid(request)
    agent = _get_agent(request, bid)

    stats: dict[str, Any] = {"total_conversations": 0, "total_appointments": 0,
                              "total_input_tokens": 0, "total_output_tokens": 0, "total_cost_usd": 0.0}
    conversations: list[dict[str, Any]] = []

    if agent and agent._tracker:
        stats = await agent._tracker.get_global_stats()
        async with agent._tracker._conn.execute(
            "SELECT * FROM token_summary ORDER BY last_updated DESC LIMIT 100"
        ) as cur:
            rows = await cur.fetchall()
        conversations = [dict(r) for r in rows]

    ctx = await _base_ctx(request, bid, "logs")
    ctx["stats"]         = stats
    ctx["conversations"] = conversations
    return _render("logs.html", ctx)


# ─── Agent hot-reload (per business) ─────────────────────────────────────────

async def _reload_agent(request: Request, business_id: str = DEFAULT_BUSINESS_ID) -> None:
    """Rebuild the BookingAgent for the given business and store in app.state.agents."""
    store  = _get_store(request)
    config = await store.to_agent_config(business_id)

    if not config["llm"]["api_key"] and config["llm"]["provider"] != "ollama":
        return  # Can't build without credentials

    try:
        from appt_agent import BookingAgentBuilder, Intent
        from appt_agent.llm.base import get_provider
        from pathlib import Path

        llm_cfg  = config["llm"]
        data_dir = Path(request.app.state.data_dir)

        kwargs: dict[str, Any] = {}
        if llm_cfg.get("api_key"):  kwargs["api_key"]  = llm_cfg["api_key"]
        if llm_cfg.get("base_url"): kwargs["base_url"] = llm_cfg["base_url"]
        if llm_cfg.get("model"):    kwargs["model"]    = llm_cfg["model"]

        # Each business gets its own tokens DB
        tokens_db = str(data_dir / f"{business_id}_tokens.db")

        builder = (
            BookingAgentBuilder()
            .with_llm(llm_cfg["provider"], **kwargs)
            .with_business_name(config["business_name"])
            .with_appointment_duration(config["appointment_duration"])
            .with_required_slots(config["required_slots"])
            .with_token_tracking(tokens_db)
        )

        # ── Calendars ──────────────────────────────────────────────
        # Per-business token; fall back to global legacy file
        _per_biz_token = data_dir / f"google_token_{business_id}.json"
        token_file   = _per_biz_token if _per_biz_token.exists() else data_dir / "google_token.json"
        service_file = data_dir / "google_service_account.json"
        creds_file   = data_dir / "google_credentials.json"

        if token_file.exists() and creds_file.exists():
            try:
                from appt_agent.calendars.google_cal import GoogleCalendar
                builder.with_calendar_instance(
                    GoogleCalendar.from_oauth2(
                        credentials_path=str(creds_file),
                        token_path=str(token_file),
                    )
                )
            except Exception:
                pass
        elif service_file.exists():
            try:
                from appt_agent.calendars.google_cal import GoogleCalendar
                delegate = await store.get(business_id, "google_service_delegate")
                builder.with_calendar_instance(
                    GoogleCalendar.from_service_account(
                        json_path=str(service_file),
                        delegate=delegate or None,
                    )
                )
            except Exception:
                pass

        # Outlook
        oc_id  = await store.get(business_id, "outlook_client_id")
        oc_sec = await store.get(business_id, "outlook_client_secret")
        oc_tid = await store.get(business_id, "outlook_tenant_id")
        oc_em  = await store.get(business_id, "outlook_user_email")
        if oc_id and oc_sec and oc_tid and oc_em:
            try:
                from appt_agent.calendars.outlook_cal import OutlookCalendar
                builder.with_calendar_instance(
                    OutlookCalendar(client_id=oc_id, client_secret=oc_sec,
                                    tenant_id=oc_tid, user_email=oc_em)
                )
            except Exception:
                pass

        # MCP
        mcp_url = await store.get(business_id, "mcp_server_url")
        mcp_cmd = await store.get(business_id, "mcp_command")
        if mcp_url or mcp_cmd:
            try:
                from appt_agent.calendars.mcp_cal import MCPCalendar
                env_str = await store.get(business_id, "mcp_env", "{}")
                mcp_env = json.loads(env_str) if env_str else {}
                if mcp_url:
                    builder.with_calendar_instance(MCPCalendar(server_url=mcp_url))
                else:
                    builder.with_calendar_instance(
                        MCPCalendar(command=mcp_cmd.split(), env=mcp_env)
                    )
            except Exception:
                pass
        # ──────────────────────────────────────────────────────────

        for intent in config["intents"]:
            builder.with_intent(Intent(
                name=intent["name"],
                description=intent["description"],
                webhook=intent.get("webhook"),
                webhook_secret=intent.get("webhook_secret"),
            ))

        old_agent = request.app.state.agents.get(business_id)
        if old_agent:
            await old_agent.shutdown()

        new_agent = builder.build()
        await new_agent.startup()
        request.app.state.agents[business_id] = new_agent

    except Exception as exc:
        import logging
        logging.getLogger("appt_agent.studio").warning(
            "Agent reload failed for business %s: %s", business_id, exc
        )
