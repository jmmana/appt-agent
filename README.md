# appt-agent 🗓️

[![CI](https://github.com/jmmana/appt-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/jmmana/appt-agent/actions)
[![PyPI](https://img.shields.io/pypi/v/appt-agent)](https://pypi.org/project/appt-agent/)
[![Python](https://img.shields.io/pypi/pyversions/appt-agent)](https://pypi.org/project/appt-agent/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Framework Python para crear agentes conversacionales de reserva de citas.**

`appt-agent` no es un agente: es una **librería** que te da todos los bloques para construir el tuyo propio en minutos.

---

## Features

| Feature | Detalle |
|---------|---------|
| 🤖 **10 LLM providers** | Anthropic, OpenAI, Gemini, Ollama, DeepSeek, xAI, Groq, Mistral, Cohere, Bedrock |
| 📅 **Calendarios** | Google Calendar, Outlook/Microsoft Graph, cualquier MCP server |
| 📊 **Token tracking** | SQLite: tokens y costo por conversación |
| 🔔 **Webhooks** | Configurables por intención, firmados con HMAC-SHA256 |
| 🚀 **FastAPI incluido** | Server listo: `POST /chat`, `GET /stats`, `GET /conversations/{id}/tokens` |
| 🔌 **Fluent builder** | API encadenada para configurar todo en <10 líneas |

---

## Instalación

```bash
# Mínimo (sin calendarios ni LLM específico)
pip install appt-agent

# Con todo incluido
pip install "appt-agent[all]"

# Selectivo
pip install "appt-agent[anthropic,google,server]"
```

### Extras disponibles

| Extra | Incluye |
|-------|---------|
| `anthropic` | Claude (claude-sonnet-4-6, claude-haiku-4-5, etc.) |
| `openai` | GPT-4o + DeepSeek, xAI Grok, Groq (compatibles OpenAI) |
| `google` | Gemini + Google Calendar API |
| `outlook` | Microsoft Graph API (MSAL) |
| `mistral` | Mistral AI |
| `cohere` | Cohere Command R |
| `bedrock` | Amazon Bedrock (boto3) |
| `server` | FastAPI + uvicorn |
| `all` | Todo lo anterior |

---

## Quickstart

```python
import asyncio
from appt_agent import BookingAgentBuilder, Intent

agent = (
    BookingAgentBuilder()
    # LLM — cualquiera de los 10 providers
    .with_llm("anthropic", api_key="sk-ant-...", model="claude-sonnet-4-6")
    # Calendarios (puedes agregar más de uno)
    .with_calendar("google", credentials_path="credentials.json")
    # Intenciones con webhooks opcionales
    .with_intent(Intent(
        "reservar_cita",
        description="El usuario quiere agendar una cita",
        webhook="https://mi-app.com/webhooks/nueva-cita",
        webhook_secret="mi-secreto-hmac",
    ))
    .with_intent(Intent(
        "cancelar_cita",
        description="El usuario quiere cancelar su cita",
    ))
    # Guardar tokens en SQLite
    .with_token_tracking("tokens.db")
    .with_business_name("Clínica Santa María")
    .build()
)

async def main():
    await agent.startup()
    
    response = await agent.chat(
        session_id="user-123",
        message="Hola, quiero una cita para el martes a las 3pm"
    )
    print(response.reply)        # "¿A nombre de quién?"
    print(response.intent)       # "reservar_cita"
    print(response.tokens_used)  # TokenUsage(total_input=45, total_output=32, ...)

asyncio.run(main())
```

---

## Servidor FastAPI

```python
from appt_agent import BookingAgentBuilder, Intent
from appt_agent.server import serve

agent = BookingAgentBuilder()...build()

# Levanta en http://localhost:8000
serve(agent, port=8000)
```

### Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/chat` | `{"session_id": "u1", "message": "Quiero cita"}` |
| `GET` | `/conversations/{id}` | Historial de mensajes |
| `GET` | `/conversations/{id}/tokens` | Tokens gastados en esa sesión |
| `GET` | `/stats` | Totales globales |
| `POST` | `/webhooks/test` | Probar un webhook manualmente |
| `GET` | `/health` | Health check |

### Demo (sin API key)

```bash
python -m appt_agent --demo
# → http://localhost:8000
```

---

## LLM Providers

```python
# Anthropic Claude
.with_llm("anthropic", api_key="sk-ant-...", model="claude-sonnet-4-6")

# OpenAI GPT
.with_llm("openai", api_key="sk-...", model="gpt-4o-mini")

# Google Gemini
.with_llm("google", api_key="AIza...", model="gemini-2.0-flash")

# Meta Llama via Ollama (local, sin costo)
.with_llm("ollama", model="llama3.3", base_url="http://localhost:11434")

# DeepSeek (compatible OpenAI)
.with_llm("deepseek", api_key="sk-...", model="deepseek-chat")

# xAI Grok
.with_llm("xai", api_key="xai-...", model="grok-2-1212")

# Groq (ultra-rápido)
.with_llm("groq", api_key="gsk_...", model="llama-3.3-70b-versatile")

# Mistral
.with_llm("mistral", api_key="...", model="mistral-small-latest")

# Cohere
.with_llm("cohere", api_key="...", model="command-r-08-2024")

# Amazon Bedrock
.with_llm("bedrock", region_name="us-east-1",
          model="us.anthropic.claude-3-5-sonnet-20241022-v2:0")
```

---

## Calendarios

### Google Calendar

```python
# OAuth2 (usuario — requiere credentials.json de Google Cloud Console)
.with_calendar("google", credentials_path="credentials.json")

# Service Account (servidor a servidor)
.with_calendar("google", service_account_path="service_account.json",
               delegate="calendario@tudominio.com")
```

> Guía completa: [docs/calendars.md](docs/calendars.md)

### Outlook / Microsoft 365

```python
.with_calendar(
    "outlook",
    client_id="...",
    client_secret="...",
    tenant_id="...",
    user_email="agendas@empresa.com",
)
```

### MCP Server (cualquier proveedor)

```python
# HTTP/SSE
.with_calendar("mcp", server_url="http://localhost:3000/mcp")

# Stdio (subprocess)
.with_calendar("mcp", command=["npx", "google-calendar-mcp"],
               env={"GOOGLE_OAUTH_CREDENTIALS": "..."})
```

---

## Webhooks

Cada `Intent` puede tener un `webhook` URL. Cuando el agente detecta esa intención, hace `POST` al URL con:

```json
{
  "event": "intent.reservar_cita",
  "intent_name": "reservar_cita",
  "session_id": "user-123",
  "appointment": { "attendee_name": "Ana", "start": "2026-06-01T15:00:00", ... },
  "slots": { "name": "Ana", "date": "2026-06-01", "time": "15:00" },
  "timestamp": "2026-05-25T10:00:00Z"
}
```

El header `X-Signature-256: sha256=<hmac>` permite verificar autenticidad:

```python
from appt_agent.webhooks.dispatcher import WebhookDispatcher

# En tu endpoint receptor:
is_valid = WebhookDispatcher.verify_signature(
    body=request.body(),
    signature_header=request.headers["X-Signature-256"],
    secret="mi-secreto-hmac",
)
```

---

## Token Tracking (SQLite)

```python
# Activar
.with_token_tracking("tokens.db")

# Consultar tokens de una sesión
summary = await agent._tracker.get_token_summary("user-123")
print(summary.total_input_tokens)   # 1542
print(summary.total_output_tokens)  # 876
print(summary.total_cost_usd)       # 0.000234

# Estadísticas globales
stats = await agent._tracker.get_global_stats()
# {"total_conversations": 42, "total_cost_usd": 0.18, ...}
```

**Tablas SQLite:**

| Tabla | Contenido |
|-------|-----------|
| `conversations` | Una fila por sesión |
| `messages` | Cada turno user/assistant con tokens |
| `token_summary` | Totales acumulados por conversación |
| `intents_log` | Intenciones detectadas + estado del webhook |

---

## Proveedor LLM personalizado

```python
from appt_agent.llm.base import AbstractLLM, register_provider
from appt_agent.models import LLMResponse, Message

@register_provider("mi_llm")
class MiLLM(AbstractLLM):
    provider = "mi_llm"
    model    = "mi-modelo-1"
    
    def __init__(self, api_key: str, **kwargs):
        self._key = api_key
    
    async def chat(self, messages: list[Message], **kwargs) -> LLMResponse:
        # Tu lógica aquí
        return LLMResponse(content="...", input_tokens=10, output_tokens=20,
                           model=self.model, provider=self.provider)
    
    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return 0.0

# Usar
agent = BookingAgentBuilder().with_llm("mi_llm", api_key="...").build()
```

---

## Configuración avanzada

```python
agent = (
    BookingAgentBuilder()
    .with_llm("anthropic", api_key="...")
    # Slots requeridos antes de confirmar (default: name, date, time)
    .with_required_slots(["name", "date", "time", "service", "email"])
    # Duración del turno en minutos (default: 30)
    .with_appointment_duration(60)
    # Nombre del negocio (aparece en el prompt del asistente)
    .with_business_name("Consultorio Dr. García")
    .build()
)
```

---

## Tests

```bash
pip install "appt-agent[dev,server]"
pytest tests/ -v --cov=appt_agent
```

---

## Licencia

MIT © Juan Manuel Castillo Pinto
