"""
appt_agent.storage.tracker
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Async SQLite token & conversation tracker using aiosqlite.

Tables
------
conversations  — one row per session
messages       — every user/assistant turn with token counts
token_summary  — rolling totals per conversation
intents_log    — intent detections + webhook status
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from appt_agent.models import Conversation, Message, TokenUsage

_DDL = """
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    state       TEXT NOT NULL DEFAULT 'greeting',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    metadata    TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id   TEXT NOT NULL REFERENCES conversations(id),
    role              TEXT NOT NULL,
    content           TEXT NOT NULL,
    input_tokens      INTEGER DEFAULT 0,
    output_tokens     INTEGER DEFAULT 0,
    model             TEXT,
    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS token_summary (
    conversation_id   TEXT PRIMARY KEY REFERENCES conversations(id),
    total_input       INTEGER DEFAULT 0,
    total_output      INTEGER DEFAULT 0,
    total_cost_usd    REAL    DEFAULT 0.0,
    message_count     INTEGER DEFAULT 0,
    last_updated      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS intents_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id  TEXT NOT NULL,
    detected_intent  TEXT NOT NULL,
    confidence       REAL DEFAULT 0.0,
    webhook_url      TEXT,
    webhook_sent     INTEGER DEFAULT 0,
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_messages_conv    ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_intents_conv     ON intents_log(conversation_id);
"""


class TokenTracker:
    """Async SQLite tracker for token usage and conversation history."""

    def __init__(self, db_path: str | Path = "appt_tokens.db") -> None:
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None

    # ─── lifecycle ────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Open DB connection and apply DDL (idempotent)."""
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_DDL)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> "TokenTracker":
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    @property
    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("TokenTracker not connected. Call await tracker.connect() first.")
        return self._db

    # ─── conversation ─────────────────────────────────────────────────────────

    async def ensure_conversation(
        self, conversation_id: str, metadata: dict[str, Any] | None = None
    ) -> None:
        await self._conn.execute(
            "INSERT OR IGNORE INTO conversations (id, metadata) VALUES (?, ?)",
            (conversation_id, json.dumps(metadata or {})),
        )
        await self._conn.commit()

    async def update_state(self, conversation_id: str, state: str) -> None:
        await self._conn.execute(
            "UPDATE conversations SET state = ? WHERE id = ?",
            (state, conversation_id),
        )
        await self._conn.commit()

    # ─── messages ─────────────────────────────────────────────────────────────

    async def save_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: str | None = None,
        cost_usd: float = 0.0,
    ) -> None:
        await self.ensure_conversation(conversation_id)

        await self._conn.execute(
            """INSERT INTO messages
               (conversation_id, role, content, input_tokens, output_tokens, model)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (conversation_id, role, content, input_tokens, output_tokens, model),
        )

        # Upsert token_summary
        await self._conn.execute(
            """INSERT INTO token_summary (conversation_id, total_input, total_output, total_cost_usd, message_count, last_updated)
               VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
               ON CONFLICT(conversation_id) DO UPDATE SET
                   total_input    = total_input  + excluded.total_input,
                   total_output   = total_output + excluded.total_output,
                   total_cost_usd = total_cost_usd + excluded.total_cost_usd,
                   message_count  = message_count + 1,
                   last_updated   = CURRENT_TIMESTAMP""",
            (conversation_id, input_tokens, output_tokens, cost_usd),
        )
        await self._conn.commit()

    # ─── intents ──────────────────────────────────────────────────────────────

    async def log_intent(
        self,
        conversation_id: str,
        intent_name: str,
        confidence: float = 0.0,
        webhook_url: str | None = None,
        webhook_sent: bool = False,
    ) -> None:
        await self._conn.execute(
            """INSERT INTO intents_log
               (conversation_id, detected_intent, confidence, webhook_url, webhook_sent)
               VALUES (?, ?, ?, ?, ?)""",
            (conversation_id, intent_name, confidence, webhook_url, int(webhook_sent)),
        )
        await self._conn.commit()

    async def mark_webhook_sent(self, conversation_id: str, intent_name: str) -> None:
        await self._conn.execute(
            """UPDATE intents_log SET webhook_sent = 1
               WHERE conversation_id = ? AND detected_intent = ? AND webhook_sent = 0""",
            (conversation_id, intent_name),
        )
        await self._conn.commit()

    # ─── queries ──────────────────────────────────────────────────────────────

    async def get_token_summary(self, conversation_id: str) -> TokenUsage | None:
        async with self._conn.execute(
            "SELECT * FROM token_summary WHERE conversation_id = ?", (conversation_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return TokenUsage(
            conversation_id=row["conversation_id"],
            total_input_tokens=row["total_input"],
            total_output_tokens=row["total_output"],
            total_cost_usd=row["total_cost_usd"],
            message_count=row["message_count"],
        )

    async def get_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        async with self._conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_global_stats(self) -> dict[str, Any]:
        async with self._conn.execute(
            """SELECT
                   COUNT(DISTINCT conversation_id)  AS total_conversations,
                   SUM(total_input)                 AS total_input_tokens,
                   SUM(total_output)                AS total_output_tokens,
                   SUM(total_cost_usd)              AS total_cost_usd,
                   SUM(message_count)               AS total_messages
               FROM token_summary"""
        ) as cur:
            row = await cur.fetchone()

        async with self._conn.execute(
            "SELECT COUNT(*) AS booked FROM intents_log WHERE detected_intent = 'reservar_cita' AND webhook_sent = 1"
        ) as cur:
            booked = await cur.fetchone()

        return {
            "total_conversations":  row["total_conversations"] or 0,
            "total_input_tokens":   row["total_input_tokens"] or 0,
            "total_output_tokens":  row["total_output_tokens"] or 0,
            "total_cost_usd":       round(row["total_cost_usd"] or 0.0, 6),
            "total_messages":       row["total_messages"] or 0,
            "total_appointments":   booked["booked"] or 0,
        }
