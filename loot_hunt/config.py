from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    gemini_api_key: str | None
    database_path: Path
    watcher_interval_seconds: int
    log_level: str
    admin_ids: frozenset[int]
    timezone: str
    pepper_timeout_seconds: int
    pepper_max_concurrency: int
    search_result_cap: int
    search_session_ttl_seconds: int

    @classmethod
    def from_env(cls, *, load_env: bool = True) -> Settings:
        if load_env:
            load_dotenv()
        admins = frozenset(
            int(value.strip())
            for value in os.getenv("ADMIN_IDS", "").split(",")
            if value.strip().isdigit()
        )
        return cls(
            bot_token=os.getenv("BOT_TOKEN", ""),
            gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
            database_path=Path(os.getenv("DATABASE_PATH", "data/loot_hunt.db")),
            watcher_interval_seconds=max(60, _int("WATCHER_INTERVAL_SECONDS", 3600)),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            admin_ids=admins,
            timezone=os.getenv("APP_TIMEZONE", "Europe/Warsaw"),
            pepper_timeout_seconds=max(5, _int("PEPPER_TIMEOUT_SECONDS", 25)),
            pepper_max_concurrency=max(1, _int("PEPPER_MAX_CONCURRENCY", 4)),
            search_result_cap=min(30, max(5, _int("SEARCH_RESULT_CAP", 25))),
            search_session_ttl_seconds=max(300, _int("SEARCH_SESSION_TTL_SECONDS", 3600)),
        )
