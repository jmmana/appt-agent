# ─── Stage 1: builder ─────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml README.md ./
COPY appt_agent/ appt_agent/

RUN pip install --no-cache-dir build && python -m build --wheel

# ─── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.12-slim

LABEL org.opencontainers.image.title="appt-agent studio"
LABEL org.opencontainers.image.description="Conversational appointment booking agent with web UI"
LABEL org.opencontainers.image.source="https://github.com/jmmana/appt-agent"
LABEL org.opencontainers.image.licenses="MIT"

# Install curl + wget for healthcheck (Coolify uses wget) + create non-root user
RUN apt-get update && apt-get install -y --no-install-recommends curl wget && \
    rm -rf /var/lib/apt/lists/* && \
    useradd -m -u 1000 appuser

WORKDIR /app

# Copy built wheel
COPY --from=builder /build/dist/*.whl .

# Install with common extras (users can override with build args)
ARG EXTRAS="anthropic,openai,google,outlook,mistral,cohere,server"
RUN pip install --no-cache-dir "appt_agent-0.1.0-py3-none-any.whl[$EXTRAS]" \
    && pip install --no-cache-dir "jinja2>=3.1,<3.1.5" python-multipart \
    && rm *.whl

# Data volume (SQLite files + credential files)
RUN mkdir -p /data && chown appuser:appuser /data
VOLUME ["/data"]

USER appuser

ENV APPT_DATA_DIR=/data
ENV PORT=8000
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "-m", "appt_agent.studio"]
