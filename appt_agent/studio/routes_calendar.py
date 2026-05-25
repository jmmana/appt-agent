"""
appt_agent.studio.routes_calendar
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Calendar configuration routes:
  GET  /studio/calendars                 → calendar config page
  POST /studio/calendars/upload          → upload credentials.json or service_account.json
  GET  /studio/calendars/google/oauth-url → get Google OAuth2 authorization URL
  POST /studio/calendars/google/oauth-code → exchange code for token
  POST /studio/calendars/google/service   → save service account delegate
  POST /studio/calendars/google/disconnect
  POST /studio/calendars/outlook          → save Outlook credentials
  POST /studio/calendars/outlook/test     → test Outlook connection
  POST /studio/calendars/mcp              → save MCP config
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from appt_agent.studio.config_store import ConfigStore
from appt_agent.studio.routes import _base_ctx, _TEMPLATES_DIR, _reload_agent, _render

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
router = APIRouter(prefix="/studio/calendars")


def _store(request: Request) -> ConfigStore:
    return request.app.state.config_store


def _data_dir(request: Request) -> Path:
    return Path(request.app.state.tokens_db).parent


# ─── Page ─────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def calendars_page(request: Request) -> HTMLResponse:
    store    = _store(request)
    config   = await store.to_agent_config()
    data_dir = _data_dir(request)

    # Detect what's already configured
    google_oauth_file   = data_dir / "google_credentials.json"
    google_token_file   = data_dir / "google_token.json"
    google_service_file = data_dir / "google_service_account.json"

    google_connected  = google_token_file.exists() or google_service_file.exists()
    google_oauth_file_name = google_oauth_file.name if google_oauth_file.exists() else None

    outlook_config = {
        "client_id":  await store.get("outlook_client_id"),
        "tenant_id":  await store.get("outlook_tenant_id"),
        "user_email": await store.get("outlook_user_email"),
    }
    outlook_connected = bool(outlook_config["client_id"] and outlook_config["user_email"])

    mcp_config = {
        "server_url": await store.get("mcp_server_url"),
        "command":    await store.get("mcp_command"),
    }
    mcp_connected = bool(mcp_config["server_url"] or mcp_config["command"])

    ctx = _base_ctx(request, config, "calendars")
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
    data_dir = _data_dir(request)
    content  = await file.read()

    # Validate JSON
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

    target = data_dir / filename
    target.write_bytes(content)

    await _reload_agent(request)
    return JSONResponse({"ok": True, "file": filename})


# ─── Google OAuth2 flow ───────────────────────────────────────────────────────

@router.get("/google/oauth-url")
async def google_oauth_url(request: Request) -> JSONResponse:
    data_dir = _data_dir(request)
    creds_path = data_dir / "google_credentials.json"
    if not creds_path.exists():
        return JSONResponse({"error": "Sube credentials.json primero"}, status_code=400)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import]
        SCOPES = ["https://www.googleapis.com/auth/calendar"]
        flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
        flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
        url, _ = flow.authorization_url(prompt="consent", access_type="offline")
        # Store flow state for code exchange
        request.app.state._google_flow = flow
        return JSONResponse({"url": url})
    except ImportError:
        return JSONResponse({"error": "Instala: pip install appt-agent[google]"}, status_code=500)


@router.post("/google/oauth-code")
async def google_oauth_code(request: Request) -> JSONResponse:
    body = await request.json()
    code = body.get("code", "").strip()
    data_dir  = _data_dir(request)
    token_path = data_dir / "google_token.json"

    try:
        flow = getattr(request.app.state, "_google_flow", None)
        if not flow:
            # Re-create flow
            from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import]
            creds_path = data_dir / "google_credentials.json"
            flow = InstalledAppFlow.from_client_secrets_file(
                str(creds_path), ["https://www.googleapis.com/auth/calendar"]
            )
            flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"

        flow.fetch_token(code=code)
        creds = flow.credentials
        token_path.write_text(creds.to_json())
        await _reload_agent(request)
        return JSONResponse({"ok": True})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@router.post("/google/service")
async def google_service_delegate(request: Request) -> JSONResponse:
    body = await request.json()
    store = _store(request)
    await store.set("google_service_delegate", body.get("delegate", ""))
    await _reload_agent(request)
    return JSONResponse({"ok": True})


@router.post("/google/disconnect")
async def google_disconnect(request: Request) -> JSONResponse:
    data_dir = _data_dir(request)
    for f in ["google_token.json", "google_service_account.json"]:
        p = data_dir / f
        if p.exists():
            p.unlink()
    await _reload_agent(request)
    return JSONResponse({"ok": True})


# ─── Outlook ──────────────────────────────────────────────────────────────────

@router.post("/outlook")
async def save_outlook(request: Request) -> JSONResponse:
    body  = await request.json()
    store = _store(request)
    await store.set_many({
        "outlook_client_id":     body.get("client_id", ""),
        "outlook_tenant_id":     body.get("tenant_id", ""),
        "outlook_user_email":    body.get("user_email", ""),
    })
    if body.get("client_secret"):
        await store.set("outlook_client_secret", body["client_secret"])
    await _reload_agent(request)
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
    body  = await request.json()
    store = _store(request)
    await store.set_many({
        "mcp_server_url": body.get("server_url", ""),
        "mcp_command":    body.get("command", ""),
        "mcp_env":        body.get("env", "{}"),
    })
    await _reload_agent(request)
    return JSONResponse({"ok": True})
