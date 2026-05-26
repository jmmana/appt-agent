"""
appt_agent.studio.config_store
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Multi-tenant persistent configuration store using SQLite.

Tables
------
businesses     — id (uuid), name
agent_config   — (business_id, key, value)
studio_intents — (id, business_id, name, ...)
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import aiosqlite

_DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS businesses (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL DEFAULT 'Mi Negocio',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_config (
    business_id TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL DEFAULT '',
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (business_id, key),
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS studio_intents (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id    TEXT NOT NULL,
    name           TEXT NOT NULL,
    description    TEXT NOT NULL DEFAULT '',
    webhook        TEXT,
    webhook_secret TEXT,
    active         INTEGER DEFAULT 1,
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(business_id, name),
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
);
"""

_DEFAULTS: dict[str, Any] = {
    "llm_provider":         "anthropic",
    "llm_model":            "claude-sonnet-4-6",
    "llm_api_key":          "",
    "llm_base_url":         "",
    "business_name":        "Mi Negocio",
    "appointment_duration": 30,
    "required_slots":       json.dumps(["name", "date", "time"]),
}

DEFAULT_BUSINESS_ID = "default"


class ConfigStore:
    """Async SQLite-backed multi-tenant config store for the Studio panel."""

    def __init__(self, db_path: str | Path = "/data/studio.db") -> None:
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None

    # ─── Lifecycle ──────────────────────────────────────────────────

    async def connect(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA foreign_keys = ON")
        await self._migrate()
        await self._db.commit()

    async def _migrate(self) -> None:
        """Create new tables; migrate legacy single-tenant data if needed."""
        # Check if we're on the old schema (agent_config with key TEXT PRIMARY KEY)
        async with self._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_config'"
        ) as cur:
            has_old_config = await cur.fetchone()

        legacy_cfg: dict[str, str] = {}
        legacy_intents: list[dict[str, Any]] = []

        if has_old_config:
            async with self._db.execute("PRAGMA table_info(agent_config)") as cur:
                cols = [r["name"] for r in await cur.fetchall()]
            if "business_id" not in cols:
                # Old single-tenant schema — salvage data before dropping
                async with self._db.execute("SELECT key, value FROM agent_config") as cur:
                    for row in await cur.fetchall():
                        legacy_cfg[row["key"]] = row["value"]
                try:
                    async with self._db.execute("SELECT * FROM studio_intents") as cur:
                        for row in await cur.fetchall():
                            legacy_intents.append(dict(row))
                except Exception:
                    pass
                await self._db.execute("DROP TABLE IF EXISTS studio_intents")
                await self._db.execute("DROP TABLE IF EXISTS agent_config")

        # Create new schema
        await self._db.executescript(_DDL)

        # Ensure default business exists
        biz_name = legacy_cfg.get("business_name", "Mi Negocio")
        await self._db.execute(
            "INSERT OR IGNORE INTO businesses (id, name) VALUES (?, ?)",
            (DEFAULT_BUSINESS_ID, biz_name),
        )

        # Seed defaults for default business
        for key, val in _DEFAULTS.items():
            stored = legacy_cfg.get(key, str(val))
            await self._db.execute(
                "INSERT OR IGNORE INTO agent_config (business_id, key, value) VALUES (?, ?, ?)",
                (DEFAULT_BUSINESS_ID, key, stored),
            )

        # Migrate legacy intents
        for intent in legacy_intents:
            await self._db.execute(
                """INSERT OR IGNORE INTO studio_intents
                   (business_id, name, description, webhook, webhook_secret, active)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    DEFAULT_BUSINESS_ID,
                    intent["name"],
                    intent.get("description", ""),
                    intent.get("webhook"),
                    intent.get("webhook_secret"),
                    intent.get("active", 1),
                ),
            )

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def _conn(self) -> aiosqlite.Connection:
        if not self._db:
            raise RuntimeError("ConfigStore not connected")
        return self._db

    # ─── Businesses CRUD ────────────────────────────────────────────

    async def list_businesses(self) -> list[dict[str, Any]]:
        async with self._conn.execute(
            "SELECT * FROM businesses ORDER BY created_at ASC"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_business(self, business_id: str) -> dict[str, Any] | None:
        async with self._conn.execute(
            "SELECT * FROM businesses WHERE id = ?", (business_id,)
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def create_business(self, name: str) -> str:
        bid = uuid.uuid4().hex[:8]
        await self._conn.execute(
            "INSERT INTO businesses (id, name) VALUES (?, ?)", (bid, name)
        )
        # Seed defaults
        for key, val in _DEFAULTS.items():
            await self._conn.execute(
                "INSERT OR IGNORE INTO agent_config (business_id, key, value) VALUES (?, ?, ?)",
                (bid, key, str(val)),
            )
        # Pre-fill business_name from the given name
        await self._conn.execute(
            """INSERT OR REPLACE INTO agent_config (business_id, key, value)
               VALUES (?, 'business_name', ?)""",
            (bid, name),
        )
        # Copy LLM config from default (same provider usually)
        for llm_key in ("llm_provider", "llm_api_key", "llm_base_url", "llm_model"):
            val = await self.get(DEFAULT_BUSINESS_ID, llm_key)
            if val:
                await self._conn.execute(
                    """INSERT OR REPLACE INTO agent_config (business_id, key, value)
                       VALUES (?, ?, ?)""",
                    (bid, llm_key, val),
                )
        await self._conn.commit()
        return bid

    async def delete_business(self, business_id: str) -> None:
        if business_id == DEFAULT_BUSINESS_ID:
            raise ValueError("No se puede eliminar el negocio por defecto")
        await self._conn.execute("DELETE FROM businesses WHERE id = ?", (business_id,))
        await self._conn.commit()

    async def rename_business(self, business_id: str, name: str) -> None:
        await self._conn.execute(
            "UPDATE businesses SET name = ? WHERE id = ?", (name, business_id)
        )
        await self._conn.execute(
            """INSERT OR REPLACE INTO agent_config (business_id, key, value)
               VALUES (?, 'business_name', ?)""",
            (business_id, name),
        )
        await self._conn.commit()

    # ─── Config key/value (scoped to business) ──────────────────────

    async def get(self, business_id: str, key: str, default: str = "") -> str:
        async with self._conn.execute(
            "SELECT value FROM agent_config WHERE business_id = ? AND key = ?",
            (business_id, key),
        ) as cur:
            row = await cur.fetchone()
        return row["value"] if row else default

    async def set(self, business_id: str, key: str, value: str) -> None:
        await self._conn.execute(
            """INSERT INTO agent_config (business_id, key, value, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(business_id, key) DO UPDATE
               SET value = excluded.value, updated_at = CURRENT_TIMESTAMP""",
            (business_id, key, value),
        )
        await self._conn.commit()

    async def get_all(self, business_id: str) -> dict[str, str]:
        async with self._conn.execute(
            "SELECT key, value FROM agent_config WHERE business_id = ?", (business_id,)
        ) as cur:
            rows = await cur.fetchall()
        return {r["key"]: r["value"] for r in rows}

    async def set_many(self, business_id: str, data: dict[str, str]) -> None:
        for key, val in data.items():
            await self.set(business_id, key, val)

    # ─── Intents CRUD (scoped to business) ──────────────────────────

    async def list_intents(self, business_id: str) -> list[dict[str, Any]]:
        async with self._conn.execute(
            "SELECT * FROM studio_intents WHERE business_id = ? ORDER BY id ASC",
            (business_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_intent(self, business_id: str, intent_id: int) -> dict[str, Any] | None:
        async with self._conn.execute(
            "SELECT * FROM studio_intents WHERE id = ? AND business_id = ?",
            (intent_id, business_id),
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def upsert_intent(
        self,
        business_id: str,
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
                   WHERE id=? AND business_id=?""",
                (name, description, webhook, webhook_secret, int(active), intent_id, business_id),
            )
        else:
            await self._conn.execute(
                """INSERT OR REPLACE INTO studio_intents
                   (business_id, name, description, webhook, webhook_secret, active)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (business_id, name, description, webhook, webhook_secret, int(active)),
            )
        await self._conn.commit()

    async def delete_intent(self, business_id: str, intent_id: int) -> None:
        await self._conn.execute(
            "DELETE FROM studio_intents WHERE id = ? AND business_id = ?",
            (intent_id, business_id),
        )
        await self._conn.commit()

    # ─── Build live agent config ─────────────────────────────────────

    async def to_agent_config(self, business_id: str) -> dict[str, Any]:
        """Return a dict suitable for BookingAgentBuilder."""
        cfg = await self.get_all(business_id)
        intents = await self.list_intents(business_id)
        return {
            "llm": {
                "provider": cfg.get("llm_provider", "anthropic"),
                "api_key":  cfg.get("llm_api_key", ""),
                "model":    cfg.get("llm_model", "claude-sonnet-4-6"),
                "base_url": cfg.get("llm_base_url") or None,
            },
            "business_name":        cfg.get("business_name", "Mi Negocio"),
            "appointment_duration": int(cfg.get("appointment_duration", 30)),
            "required_slots":       json.loads(cfg.get("required_slots", '["name","date","time"]')),
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
