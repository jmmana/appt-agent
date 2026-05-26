"""
appt_agent.studio.routes_calendar
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Calendar configuration routes (multi-tenant aware).
All routes read ?b=<business_id> via the shared _bid() helper.
"""
from __future__ import annotations

import json
import urllib.parse
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from appt_agent.studio.config_store import ConfigStore, DEFAULT_BUSINESS_ID
from appt_agent.studio.routes import (
    _base_ctx, _TEMPLATES_DIR, _reload_agent, _render, _bid
)

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
router = APIRouter(prefix="/studio/calendars")

GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _store(request: Request) -> ConfigStore:
    return request.app.state.config_store


def _data_dir(request: Request) -> Path:
    return Path(request.app.state.data_dir)


def _google_token_path(data_dir: Path, bid: str) -> Path:
    """Return per-business token path; default business keeps the legacy filename."""
    if bid == DEFAULT_BUSINESS_ID:
        return data_dir / "google_token.json"
    return data_dir / f"google_token_{bid}.json"


def _callback_uri(request: Request) -> str:
    """Build the absolute redirect URI for Google OAuth."""
    base = str(request.base_url).rstrip("/")
    return f"{base}/studio/calendars/google/callback"


# ─── Page ─────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def calendars_page(request: Request) -> HTMLResponse:
    bid      = _bid(request)
    store    = _store(request)
    data_dir = _data_dir(request)

    google_oauth_file   = data_dir / "google_credentials.json"
    google_token_file   = _google_token_path(data_dir, bid)
    google_service_file = data_dir / "google_service_account.json"

    # Fall back to global token if per-business doesn't exist yet
    if not google_token_file.exists():
        google_token_file = data_dir / "google_token.json"

    google_connected       = google_token_file.exists() or google_service_file.exists()
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

    # Flash messages from OAuth redirect params
    flash_ok    = request.query_params.get("connected")
    flash_error = request.query_params.get("error")

    ctx = await _base_ctx(request, bid, "calendars")
    ctx.update({
        "google_connected":    google_connected,
        "google_oauth_file":   google_oauth_file_name,
        "google_service_file": google_service_file.exists(),
        "outlook_config":      outlook_config,
        "outlook_connected":   outlook_connected,
        "mcp_config":          mcp_config,
        "mcp_connected":       mcp_connected,
        "callback_uri":        _callback_uri(request),
        "flash_ok":            flash_ok,
        "flash_error":         flash_error,
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


# ─── Google OAuth2 — web redirect flow ───────────────────────────────────────

@router.get("/google/oauth-redirect")
async def google_oauth_redirect(request: Request) -> RedirectResponse:
    """Redirect the browser to Google's consent screen (no code-paste needed)."""
    bid        = _bid(request)
    data_dir   = _data_dir(request)
    creds_path = data_dir / "google_credentials.json"

    if not creds_path.exists():
        return RedirectResponse(
            f"/studio/calendars?b={bid}&error={urllib.parse.quote('Sube credentials.json primero')}"
        )
    try:
        from google_auth_oauthlib.flow import Flow  # type: ignore[import]
        redirect_uri = _callback_uri(request)
        flow = Flow.from_client_secrets_file(str(creds_path), GOOGLE_SCOPES, redirect_uri=redirect_uri)
        url, _ = flow.authorization_url(prompt="consent", access_type="offline", state=bid)

        # Store flow per business for the callback to reuse
        if not hasattr(request.app.state, "_google_flows"):
            request.app.state._google_flows = {}
        request.app.state._google_flows[bid] = flow

        return RedirectResponse(url)
    except ImportError:
        return RedirectResponse(
            f"/studio/calendars?b={bid}&error={urllib.parse.quote('Instala: pip install appt-agent[google]')}"
        )
    except Exception as exc:
        return RedirectResponse(
            f"/studio/calendars?b={bid}&error={urllib.parse.quote(str(exc))}"
        )


@router.get("/google/callback")
async def google_oauth_callback(
    request: Request,
    code:  str | None = None,
    state: str        = DEFAULT_BUSINESS_ID,
    error: str | None = None,
) -> RedirectResponse:
    """Handle Google's redirect after user grants access."""
    bid = state or DEFAULT_BUSINESS_ID

    if error:
        return RedirectResponse(
            f"/studio/calendars?b={bid}&error={urllib.parse.quote(error)}"
        )

    data_dir   = _data_dir(request)
    token_path = _google_token_path(data_dir, bid)

    try:
        from google_auth_oauthlib.flow import Flow  # type: ignore[import]
        creds_path   = data_dir / "google_credentials.json"
        redirect_uri = _callback_uri(request)

        flows = getattr(request.app.state, "_google_flows", {})
        flow  = flows.get(bid)
        if not flow:
            flow = Flow.from_client_secrets_file(str(creds_path), GOOGLE_SCOPES, redirect_uri=redirect_uri)

        flow.fetch_token(code=code)
        token_path.write_text(flow.credentials.to_json())

        # Clean up stored flow
        flows.pop(bid, None)

        await _reload_agent(request, bid)
        return RedirectResponse(f"/studio/calendars?b={bid}&connected=google")

    except Exception as exc:
        return RedirectResponse(
            f"/studio/calendars?b={bid}&error={urllib.parse.quote(str(exc))}"
        )


# ─── Legacy: keep oauth-url endpoint for API consumers ───────────────────────

@router.get("/google/oauth-url")
async def google_oauth_url(request: Request) -> JSONResponse:
    """Return the OAuth URL as JSON (for programmatic use). UI uses /oauth-redirect instead."""
    bid        = _bid(request)
    data_dir   = _data_dir(request)
    creds_path = data_dir / "google_credentials.json"
    if not creds_path.exists():
        return JSONResponse({"error": "Sube credentials.json primero"}, status_code=400)
    try:
        from google_auth_oauthlib.flow import Flow  # type: ignore[import]
        redirect_uri = _callback_uri(request)
        flow = Flow.from_client_secrets_file(str(creds_path), GOOGLE_SCOPES, redirect_uri=redirect_uri)
        url, _ = flow.authorization_url(prompt="consent", access_type="offline", state=bid)
        if not hasattr(request.app.state, "_google_flows"):
            request.app.state._google_flows = {}
        request.app.state._google_flows[bid] = flow
        return JSONResponse({"url": url, "redirect_uri": redirect_uri})
    except ImportError:
        return JSONResponse({"error": "Instala: pip install appt-agent[google]"}, status_code=500)


# ─── Google Service Account ───────────────────────────────────────────────────

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
    # Remove both per-business and legacy global token
    for f in [
        _google_token_path(data_dir, bid),
        data_dir / "google_token.json",
        data_dir / "google_service_account.json",
    ]:
        if f.exists():
            f.unlink()
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
