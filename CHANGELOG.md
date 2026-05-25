# Changelog

## [0.1.0] - 2026-05-25

### Added
- `BookingAgentBuilder` — fluent API para construir agentes de citas
- 10 LLM providers: Anthropic, OpenAI, Gemini, Ollama/Meta, DeepSeek, xAI, Groq, Mistral, Cohere, Amazon Bedrock
- Adaptadores de calendario: Google Calendar (OAuth2 + Service Account), Outlook (MSAL), MCP
- Motor de conversación multi-turno con máquina de estados (GREETING → COLLECT → CONFIRM → BOOKED)
- Slot filler LLM-based: extrae nombre, fecha, hora, servicio, email
- Clasificador de intenciones configurable
- SQLite token tracker con 4 tablas (conversations, messages, token_summary, intents_log)
- Webhook dispatcher async con HMAC-SHA256 y reintentos exponenciales
- Servidor FastAPI: `/chat`, `/conversations`, `/stats`, `/webhooks/test`, `/health`
- CLI: `python -m appt_agent --demo`
- 38 tests unitarios/integración con pytest-asyncio
- GitHub Actions CI (Python 3.11/3.12/3.13) + workflow de publish a PyPI
