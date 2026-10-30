from __future__ import annotations

import contextlib
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
PRAGMA busy_timeout=5000;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS offers (
 thread_id TEXT PRIMARY KEY,
 payload TEXT NOT NULL,
 first_seen_at TEXT NOT NULL,
 last_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subscriptions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_user_id INTEGER NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('search','category')), label TEXT NOT NULL,
 source TEXT NOT NULL, plan_json TEXT, platform TEXT NOT NULL DEFAULT 'pl',
 active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subscription_seen_threads (
 subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
 thread_id TEXT NOT NULL, seen_at TEXT NOT NULL, PRIMARY KEY(subscription_id, thread_id)
);
CREATE TABLE IF NOT EXISTS search_sessions (
 id TEXT PRIMARY KEY, telegram_user_id INTEGER NOT NULL, query TEXT NOT NULL,
 plan_json TEXT NOT NULL, offers_json TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_preferences (
 telegram_user_id INTEGER PRIMARY KEY,
 platform TEXT NOT NULL DEFAULT 'pl'
);
CREATE TABLE IF NOT EXISTS referrals (
 referrer_id INTEGER NOT NULL,
 referred_id INTEGER NOT NULL PRIMARY KEY,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_bonus_slots (
 telegram_user_id INTEGER PRIMARY KEY,
 bonus_slots INTEGER NOT NULL DEFAULT 0,
 granted_by INTEGER,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS watcher_state (
 id INTEGER PRIMARY KEY CHECK(id=1), last_run TEXT, checked INTEGER NOT NULL DEFAULT 0,
 notifications INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_active ON subscriptions(active);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON search_sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_offers_last_seen ON offers(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id);
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
        with contextlib.suppress(Exception):
            await self.connection.execute(
                "ALTER TABLE subscriptions ADD COLUMN platform TEXT NOT NULL DEFAULT 'pl'"
            )
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

    async def get_user_platform(self, user_id: int) -> str:
        async with self.db.execute(
            "SELECT platform FROM user_preferences WHERE telegram_user_id=?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return str(row["platform"]) if row else "pl"

    async def set_user_platform(self, user_id: int, platform: str) -> None:
        await self.db.execute(
            """INSERT INTO user_preferences(telegram_user_id, platform)
            VALUES(?, ?) ON CONFLICT(telegram_user_id) DO UPDATE SET platform=excluded.platform""",
            (user_id, platform),
        )
        await self.db.commit()

    async def record_referral(self, referrer_id: int, referred_id: int) -> bool:
        if referrer_id == referred_id:
            return False
        now = datetime.now(UTC).isoformat()
        try:
            await self.db.execute(
                "INSERT INTO referrals(referrer_id, referred_id, created_at) VALUES(?,?,?)",
                (referrer_id, referred_id, now),
            )
            await self.db.commit()
            return True
        except Exception:
            return False

    async def get_referral_count(self, user_id: int) -> int:
        async with self.db.execute(
            "SELECT COUNT(*) as count FROM referrals WHERE referrer_id=?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return int(row["count"]) if row else 0

    async def grant_bonus_slots(
        self, user_id: int, slots: int, granted_by: int | None = None
    ) -> int:
        now = datetime.now(UTC).isoformat()
        await self.db.execute(
            """INSERT INTO user_bonus_slots(
                telegram_user_id, bonus_slots, granted_by, updated_at
            ) VALUES(?,?,?,?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
            bonus_slots = MAX(0, user_bonus_slots.bonus_slots + excluded.bonus_slots),
            granted_by = excluded.granted_by,
            updated_at = excluded.updated_at""",
            (user_id, slots, granted_by, now),
        )
        await self.db.commit()
        return await self.get_bonus_slots(user_id)

    async def get_bonus_slots(self, user_id: int) -> int:
        async with self.db.execute(
            "SELECT bonus_slots FROM user_bonus_slots WHERE telegram_user_id=?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return int(row["bonus_slots"]) if row else 0

    async def get_subscription_limit(self, user_id: int) -> int:
        count = await self.get_referral_count(user_id)
        bonus = await self.get_bonus_slots(user_id)
        if count >= 3:
            return 50 + bonus
        return 3 + count * 2 + bonus

    async def can_add_subscription(self, user_id: int) -> bool:
        subs = await self.subscriptions(user_id, active_only=True)
        limit = await self.get_subscription_limit(user_id)
        return len(subs) < limit

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

    async def purge_expired_sessions(self) -> int:
        cursor = await self.db.execute(
            "DELETE FROM search_sessions WHERE expires_at <= ?",
            (datetime.now(UTC).isoformat(),),
        )
        await self.db.commit()
        return cursor.rowcount

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
        platform: str | None = None,
    ) -> int:
        platform_code = platform or (plan.platform if plan else "pl")
        cursor = await self.db.execute(
            """INSERT INTO subscriptions(
                telegram_user_id,kind,label,source,plan_json,platform,created_at
            ) VALUES(?,?,?,?,?,?,?)""",
            (
                user_id,
                kind,
                label,
                source,
                plan.model_dump_json() if plan else None,
                platform_code,
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
        params: list[Any] = []
        if user_id is not None:
            clauses.append("telegram_user_id=?")
            params.append(user_id)
        if active_only:
            clauses.append("active=1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cursor = await self.db.execute(
            f"SELECT * FROM subscriptions {where} ORDER BY id DESC",
            params,
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

    async def save_watcher_stats(self, checked: int, notifications: int, errors: int) -> None:
        now = datetime.now(UTC).isoformat()
        await self.db.execute(
            """INSERT INTO watcher_state(id,last_run,checked,notifications,errors)
            VALUES(1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
            last_run=excluded.last_run,checked=checked+excluded.checked,
            notifications=notifications+excluded.notifications,errors=errors+excluded.errors""",
            (now, checked, notifications, errors),
        )
        await self.db.commit()

    async def stats(self) -> dict[str, Any]:
        cursor = await self.db.execute(
            """SELECT
            (SELECT COUNT(*) FROM offers) as offers,
            (SELECT COUNT(*) FROM subscriptions WHERE active=1) as active_subscriptions,
            (SELECT COUNT(DISTINCT telegram_user_id) FROM subscriptions) as users,
            (SELECT notifications FROM watcher_state WHERE id=1) as notifications,
            (SELECT errors FROM watcher_state WHERE id=1) as errors,
            (SELECT last_run FROM watcher_state WHERE id=1) as last_run"""
        )
        row = await cursor.fetchone()
        return dict(row) if row else {}
