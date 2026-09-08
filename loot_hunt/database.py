from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

from .pepper.models import Offer
from .search.models import SearchPlan

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS offers (
 thread_id TEXT PRIMARY KEY,
 payload TEXT NOT NULL,
 first_seen_at TEXT NOT NULL,
 last_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subscriptions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_user_id INTEGER NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('search','category')), label TEXT NOT NULL,
 source TEXT NOT NULL, plan_json TEXT, active INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subscription_seen_threads (
 subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
 thread_id TEXT NOT NULL, seen_at TEXT NOT NULL, PRIMARY KEY(subscription_id, thread_id)
);
CREATE TABLE IF NOT EXISTS search_sessions (
 id TEXT PRIMARY KEY, telegram_user_id INTEGER NOT NULL, query TEXT NOT NULL,
 plan_json TEXT NOT NULL, offers_json TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS watcher_state (
 id INTEGER PRIMARY KEY CHECK(id=1), last_run TEXT, checked INTEGER NOT NULL DEFAULT 0,
 notifications INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0
);
"""


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.connection: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = await aiosqlite.connect(self.path)
        self.connection.row_factory = aiosqlite.Row
        await self.connection.executescript(SCHEMA)
        await self.connection.commit()

    @property
    def db(self) -> aiosqlite.Connection:
        if not self.connection:
            raise RuntimeError("Database is not connected")
        return self.connection

    async def close(self) -> None:
        if self.connection:
            await self.connection.close()
            self.connection = None

    async def upsert_offers(self, offers: list[Offer]) -> None:
        now = datetime.now(UTC).isoformat()
        await self.db.executemany(
            """INSERT INTO offers(thread_id,payload,first_seen_at,last_seen_at)
            VALUES(?,?,?,?) ON CONFLICT(thread_id) DO UPDATE SET
            payload=excluded.payload,last_seen_at=excluded.last_seen_at""",
            [(item.thread_id, json.dumps(item.to_dict()), now, now) for item in offers],
        )
        await self.db.commit()

    async def create_session(
        self, user_id: int, query: str, plan: SearchPlan, offers: list[Offer], ttl: int
    ) -> str:
        session_id = secrets.token_urlsafe(6)
        expires = (datetime.now(UTC) + timedelta(seconds=ttl)).isoformat()
        await self.db.execute(
            "INSERT INTO search_sessions VALUES(?,?,?,?,?,?)",
            (
                session_id,
                user_id,
                query,
                plan.model_dump_json(),
                json.dumps([item.to_dict() for item in offers]),
                expires,
            ),
        )
        await self.db.commit()
        return session_id

    async def get_session(self, session_id: str, user_id: int) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            "SELECT * FROM search_sessions WHERE id=? AND telegram_user_id=? AND expires_at>?",
            (session_id, user_id, datetime.now(UTC).isoformat()),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return {
            "query": row["query"],
            "plan": SearchPlan.model_validate_json(row["plan_json"]),
            "offers": [Offer.from_dict(item) for item in json.loads(row["offers_json"])],
        }

    async def create_subscription(
        self,
        user_id: int,
        kind: str,
        label: str,
        source: str,
        offers: list[Offer],
        plan: SearchPlan | None = None,
    ) -> int:
        cursor = await self.db.execute(
            """INSERT INTO subscriptions(telegram_user_id,kind,label,source,plan_json,created_at)
            VALUES(?,?,?,?,?,?)""",
            (
                user_id,
                kind,
                label,
                source,
                plan.model_dump_json() if plan else None,
                datetime.now(UTC).isoformat(),
            ),
        )
        subscription_id = int(cursor.lastrowid or 0)
        await self.mark_seen(subscription_id, [item.thread_id for item in offers], commit=False)
        await self.db.commit()
        return subscription_id

    async def mark_seen(self, subscription_id: int, ids: list[str], *, commit: bool = True) -> None:
        now = datetime.now(UTC).isoformat()
        await self.db.executemany(
            "INSERT OR IGNORE INTO subscription_seen_threads VALUES(?,?,?)",
            [(subscription_id, value, now) for value in ids],
        )
        if commit:
            await self.db.commit()

    async def unseen(self, subscription_id: int, offers: list[Offer]) -> list[Offer]:
        cursor = await self.db.execute(
            "SELECT thread_id FROM subscription_seen_threads WHERE subscription_id=?",
            (subscription_id,),
        )
        seen = {row[0] for row in await cursor.fetchall()}
        return [item for item in offers if item.thread_id not in seen]

    async def subscriptions(self, user_id: int | None = None, *, active_only: bool = False):
        clauses: list[str] = []
        values: list[Any] = []
        if user_id is not None:
            clauses.append("telegram_user_id=?")
            values.append(user_id)
        if active_only:
            clauses.append("active=1")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        cursor = await self.db.execute(
            "SELECT * FROM subscriptions" + where + " ORDER BY id", values
        )
        return await cursor.fetchall()

    async def set_subscription(self, subscription_id: int, user_id: int, action: str) -> bool:
        if action == "delete":
            cursor = await self.db.execute(
                "DELETE FROM subscriptions WHERE id=? AND telegram_user_id=?",
                (subscription_id, user_id),
            )
        else:
            active = 1 if action == "resume" else 0
            cursor = await self.db.execute(
                "UPDATE subscriptions SET active=? WHERE id=? AND telegram_user_id=?",
                (active, subscription_id, user_id),
            )
        await self.db.commit()
        return cursor.rowcount > 0

    async def stats(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for name, query in {
            "offers": "SELECT count(*) FROM offers",
            "active_subscriptions": "SELECT count(*) FROM subscriptions WHERE active=1",
            "users": "SELECT count(DISTINCT telegram_user_id) FROM subscriptions",
            "searches": "SELECT count(*) FROM subscriptions WHERE kind='search'",
            "categories": "SELECT count(*) FROM subscriptions WHERE kind='category'",
            "seen": "SELECT count(*) FROM subscription_seen_threads",
        }.items():
            cursor = await self.db.execute(query)
            result[name] = int((await cursor.fetchone())[0])
        return result

    async def save_watcher_stats(self, checked: int, notifications: int, errors: int) -> None:
        await self.db.execute(
            """INSERT INTO watcher_state VALUES(1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
            last_run=excluded.last_run,checked=excluded.checked,
            notifications=excluded.notifications,errors=excluded.errors""",
            (datetime.now(UTC).isoformat(), checked, notifications, errors),
        )
        await self.db.commit()
