# Guía de Calendarios

## Google Calendar

### Opción 1: OAuth2 (acceso a calendario de usuario)

1. Ve a [Google Cloud Console](https://console.cloud.google.com)
2. Crea un proyecto → habilita la **Google Calendar API**
3. Crea credenciales → **OAuth 2.0 Client ID** (tipo: Desktop app)
4. Descarga el JSON → guárdalo como `credentials.json`

```python
.with_calendar("google", credentials_path="credentials.json")
# → primera vez abre navegador para autorizar
# → guarda token en token.json automáticamente
```

### Opción 2: Service Account (server-to-server)

1. En Google Cloud Console → IAM → Service Accounts → Crear
2. Descarga el JSON de la cuenta de servicio
3. Comparte el calendario de Google con el email de la cuenta de servicio

```python
.with_calendar(
    "google",
    service_account_path="service_account.json",
    delegate="user@tudominio.com",  # usuario cuyo calendario gestionar
)
```

---

## Outlook / Microsoft 365

### Prerequisitos

1. En [Azure Portal](https://portal.azure.com) → Azure Active Directory → App registrations → New
2. Permisos de API requeridos (Application, no Delegated):
   - `Calendars.ReadWrite`
3. Crea un **Client Secret** en Certificates & Secrets
4. Copia el **Application (client) ID**, **Directory (tenant) ID**, y el secreto

```python
.with_calendar(
    "outlook",
    client_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    client_secret="tu_secreto",
    tenant_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    user_email="usuario@empresa.com",
)
```

---

## MCP Calendar (cualquier proveedor via MCP)

El adapter MCP puede conectarse a cualquier servidor que exponga estas herramientas:
- `get_available_slots(date, duration_minutes, calendar_id)`
- `create_event(attendee_name, attendee_email, service, start, end, notes)`
- `delete_event(event_id, calendar_id)`

### Via HTTP/SSE

```python
.with_calendar("mcp", server_url="http://localhost:3000/mcp")
```

### Via stdio (proceso hijo)

```python
# Ejemplo: google-calendar-mcp (npm)
.with_calendar("mcp",
    command=["npx", "-y", "@takisrs/google-calendar-mcp"],
    env={
        "GOOGLE_CLIENT_ID":     "...",
        "GOOGLE_CLIENT_SECRET": "...",
        "GOOGLE_REFRESH_TOKEN": "...",
    }
)
```

### Implementar tu propio MCP Calendar server

El servidor debe responder al protocolo JSON-RPC 2.0 con método `tools/call`:

```json
// Request
{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"get_available_slots","arguments":{"date":"2026-06-01","duration_minutes":30}}}

// Response
{"jsonrpc":"2.0","id":1,"result":{"slots":[
  {"start":"2026-06-01T08:00:00","end":"2026-06-01T08:30:00","available":true},
  {"start":"2026-06-01T09:00:00","end":"2026-06-01T09:30:00","available":true}
]}}
```
