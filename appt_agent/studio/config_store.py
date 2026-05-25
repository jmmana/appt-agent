"""
appt_agent.studio.config_store
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Persistent configuration store using SQLite.
Stores all agent settings so they survive container restarts.

Tables
------
agent_config   — key/value pairs (LLM, business, channels)
studio_intents — intent definitions (CRUD via web UI)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite

_DDL = """
CREATE TABLE IF NOT EXISTS agent_config (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL DEFAULT '',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS studio_intents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    webhook     TEXT,
    webhook_secret TEXT,
    active      INTEGER DEFAULT 1,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

# Default config values
_DEFAULTS: dict[str, Any] = {
    "llm_provider":      "anthropic",
    "llm_model":         "claude-sonnet-4-6",
    "llm_api_key":       "",
    "llm_base_url":      "",
    "business_name":     "Mi Negocio",
    "appointment_duration": 30,
    "required_slots":    json.dumps(["name", "date", "time"]),
    "studio_password":   "",   # optional UI password
}


class ConfigStore:
    """Async SQLite-backed config store for the Studio panel."""

    def __init__(self, db_path: str | Path = "/data/studio.db") -> None:
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_DDL)
        # Seed defaults (INSERT OR IGNORE)
        for key, val in _DEFAULTS.items():
            await self._db.execute(
                "INSERT OR IGNORE INTO agent_config (key, value) VALUES (?, ?)",
                (key, str(val)),
            )
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def _conn(self) -> aiosqlite.Connection:
        if not self._db:
            raise RuntimeError("ConfigStore not connected")
        return self._db

    # ─── config key/value ────────────────────────────────────────────────────

    async def get(self, key: str, default: str = "") -> str:
        async with self._conn.execute(
            "SELECT value FROM agent_config WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
        return row["value"] if row else default

    async def set(self, key: str, value: str) -> None:
        await self._conn.execute(
            """INSERT INTO agent_config (key, value, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP""",
            (key, value),
        )
        await self._conn.commit()

    async def get_all(self) -> dict[str, str]:
        async with self._conn.execute("SELECT key, value FROM agent_config") as cur:
            rows = await cur.fetchall()
        return {r["key"]: r["value"] for r in rows}

    async def set_many(self, data: dict[str, str]) -> None:
        for key, val in data.items():
            await self.set(key, val)

    # ─── intents CRUD ────────────────────────────────────────────────────────

    async def list_intents(self) -> list[dict[str, Any]]:
        async with self._conn.execute(
            "SELECT * FROM studio_intents ORDER BY id ASC"
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_intent(self, intent_id: int) -> dict[str, Any] | None:
        async with self._conn.execute(
            "SELECT * FROM studio_intents WHERE id = ?", (intent_id,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def upsert_intent(
        self,
        name: str,
        description: str,
        webhook: str | None = None,
        webhook_secret: str | None = None,
        active: bool = True,
        intent_id: int | None = None,
    ) -> None:
        if intent_id:
            await self._conn.execute(
                """UPDATE studio_intents
                   SET name=?, description=?, webhook=?, webhook_secret=?, active=?
                   WHERE id=?""",
                (name, description, webhook, webhook_secret, int(active), intent_id),
            )
        else:
            await self._conn.execute(
                """INSERT OR REPLACE INTO studio_intents
                   (name, description, webhook, webhook_secret, active)
                   VALUES (?, ?, ?, ?, ?)""",
                (name, description, webhook, webhook_secret, int(active)),
            )
        await self._conn.commit()

    async def delete_intent(self, intent_id: int) -> None:
        await self._conn.execute("DELETE FROM studio_intents WHERE id = ?", (intent_id,))
        await self._conn.commit()

    # ─── build live agent config ──────────────────────────────────────────────

    async def to_agent_config(self) -> dict[str, Any]:
        """Return a dict suitable for BookingAgentBuilder."""
        cfg = await self.get_all()
        intents = await self.list_intents()
        return {
            "llm": {
                "provider":  cfg.get("llm_provider", "anthropic"),
                "api_key":   cfg.get("llm_api_key", ""),
                "model":     cfg.get("llm_model", "claude-sonnet-4-6"),
                "base_url":  cfg.get("llm_base_url") or None,
            },
            "business_name":         cfg.get("business_name", ""),
            "appointment_duration":  int(cfg.get("appointment_duration", 30)),
            "required_slots":        json.loads(cfg.get("required_slots", '["name","date","time"]')),
            "intents": [
                {
                    "name":           i["name"],
                    "description":    i["description"],
                    "webhook":        i["webhook"],
                    "webhook_secret": i["webhook_secret"],
                }
                for i in intents if i["active"]
            ],
        }
