"""
appt_agent.studio.routes_calendar
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Calendar configuration routes (multi-tenant aware).
All routes read ?b=<business_id> via the shared _bid() helper.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from appt_agent.studio.config_store import ConfigStore
from appt_agent.studio.routes import (
    _base_ctx, _TEMPLATES_DIR, _reload_agent, _render, _bid
)

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
router = APIRouter(prefix="/studio/calendars")


def _store(request: Request) -> ConfigStore:
    return request.app.state.config_store


def _data_dir(request: Request) -> Path:
    return Path(request.app.state.data_dir)


# ─── Page ─────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def calendars_page(request: Request) -> HTMLResponse:
    bid      = _bid(request)
    store    = _store(request)
    data_dir = _data_dir(request)

    google_oauth_file   = data_dir / "google_credentials.json"
    google_token_file   = data_dir / "google_token.json"
    google_service_file = data_dir / "google_service_account.json"

    google_connected     = google_token_file.exists() or google_service_file.exists()
    google_oauth_file_name = google_oauth_file.name if google_oauth_file.exists() else None

    outlook_config = {
        "client_id":  await store.get(bid, "outlook_client_id"),
        "tenant_id":  await store.get(bid, "outlook_tenant_id"),
        "user_email": await store.get(bid, "outlook_user_email"),
    }
    outlook_connected = bool(outlook_config["client_id"] and outlook_config["user_email"])

    mcp_config = {
        "server_url": await store.get(bid, "mcp_server_url"),
        "command":    await store.get(bid, "mcp_command"),
    }
    mcp_connected = bool(mcp_config["server_url"] or mcp_config["command"])

    ctx = await _base_ctx(request, bid, "calendars")
    ctx.update({
        "google_connected":    google_connected,
        "google_oauth_file":   google_oauth_file_name,
        "google_service_file": google_service_file.exists(),
        "outlook_config":      outlook_config,
        "outlook_connected":   outlook_connected,
        "mcp_config":          mcp_config,
        "mcp_connected":       mcp_connected,
    })
    return _render("calendars.html", ctx)


# ─── Upload credentials file ──────────────────────────────────────────────────

@router.post("/upload")
async def upload_credentials(
    request: Request,
    file: UploadFile = File(...),
    type: str = Form(...),
) -> JSONResponse:
    bid      = _bid(request)
    data_dir = _data_dir(request)
    content  = await file.read()

    try:
        json.loads(content)
    except json.JSONDecodeError:
        return JSONResponse({"ok": False, "error": "Archivo JSON inválido"}, status_code=400)

    filename_map = {
        "google_oauth":   "google_credentials.json",
        "google_service": "google_service_account.json",
    }
    filename = filename_map.get(type)
    if not filename:
        return JSONResponse({"ok": False, "error": "Tipo desconocido"}, status_code=400)

    (data_dir / filename).write_bytes(content)
    await _reload_agent(request, bid)
    return JSONResponse({"ok": True, "file": filename})


# ─── Google OAuth2 flow ───────────────────────────────────────────────────────

@router.get("/google/oauth-url")
async def google_oauth_url(request: Request) -> JSONResponse:
    data_dir   = _data_dir(request)
    creds_path = data_dir / "google_credentials.json"
    if not creds_path.exists():
        return JSONResponse({"error": "Sube credentials.json primero"}, status_code=400)
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import]
        SCOPES = ["https://www.googleapis.com/auth/calendar"]
        flow   = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
        flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
        url, _ = flow.authorization_url(prompt="consent", access_type="offline")
        request.app.state._google_flow = flow
        return JSONResponse({"url": url})
    except ImportError:
        return JSONResponse({"error": "Instala: pip install appt-agent[google]"}, status_code=500)


@router.post("/google/oauth-code")
async def google_oauth_code(request: Request) -> JSONResponse:
    bid        = _bid(request)
    body       = await request.json()
    code       = body.get("code", "").strip()
    data_dir   = _data_dir(request)
    token_path = data_dir / "google_token.json"
    try:
        flow = getattr(request.app.state, "_google_flow", None)
        if not flow:
            from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import]
            creds_path = data_dir / "google_credentials.json"
            flow = InstalledAppFlow.from_client_secrets_file(
                str(creds_path), ["https://www.googleapis.com/auth/calendar"]
            )
            flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
        flow.fetch_token(code=code)
        token_path.write_text(flow.credentials.to_json())
        await _reload_agent(request, bid)
        return JSONResponse({"ok": True})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@router.post("/google/service")
async def google_service_delegate(request: Request) -> JSONResponse:
    bid   = _bid(request)
    body  = await request.json()
    store = _store(request)
    await store.set(bid, "google_service_delegate", body.get("delegate", ""))
    await _reload_agent(request, bid)
    return JSONResponse({"ok": True})


@router.post("/google/disconnect")
async def google_disconnect(request: Request) -> JSONResponse:
    bid      = _bid(request)
    data_dir = _data_dir(request)
    for f in ["google_token.json", "google_service_account.json"]:
        p = data_dir / f
        if p.exists():
            p.unlink()
    await _reload_agent(request, bid)
    return JSONResponse({"ok": True})


# ─── Outlook ──────────────────────────────────────────────────────────────────

@router.post("/outlook")
async def save_outlook(request: Request) -> JSONResponse:
    bid   = _bid(request)
    body  = await request.json()
    store = _store(request)
    await store.set_many(bid, {
        "outlook_client_id":  body.get("client_id", ""),
        "outlook_tenant_id":  body.get("tenant_id", ""),
        "outlook_user_email": body.get("user_email", ""),
    })
    if body.get("client_secret"):
        await store.set(bid, "outlook_client_secret", body["client_secret"])
    await _reload_agent(request, bid)
    return JSONResponse({"ok": True})


@router.post("/outlook/test")
async def test_outlook(request: Request) -> JSONResponse:
    body = await request.json()
    try:
        from appt_agent.calendars.outlook_cal import OutlookCalendar
        cal = OutlookCalendar(
            client_id=body["client_id"],
            client_secret=body["client_secret"],
            tenant_id=body["tenant_id"],
            user_email=body["user_email"],
        )
        await cal._get_token()
        return JSONResponse({"ok": True})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)})


# ─── MCP ──────────────────────────────────────────────────────────────────────

@router.post("/mcp")
async def save_mcp(request: Request) -> JSONResponse:
    bid   = _bid(request)
    body  = await request.json()
    store = _store(request)
    await store.set_many(bid, {
        "mcp_server_url": body.get("server_url", ""),
        "mcp_command":    body.get("command", ""),
        "mcp_env":        body.get("env", "{}"),
    })
    await _reload_agent(request, bid)
    return JSONResponse({"ok": True})
