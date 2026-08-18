from __future__ import annotations

import asyncio
import contextlib
import logging

from loot_hunt.search.models import SearchPlan

logger = logging.getLogger(__name__)


class WatcherService:
    """Replays persisted sources. It deliberately has no SearchPlanner dependency."""

    def __init__(self, database, search_service, pepper, notifier) -> None:
        self.database = database
        self.search_service = search_service
        self.pepper = pepper
        self.notifier = notifier

    async def check_once(self) -> dict[str, int]:
        stats = {"checked": 0, "notifications": 0, "errors": 0}
        rows = await self.database.subscriptions(active_only=True)
        for row in rows:
            stats["checked"] += 1
            try:
                if row["kind"] == "search":
                    plan = SearchPlan.model_validate_json(row["plan_json"])
                    offers = await self.search_service.execute_plan(plan)
                else:
                    offers = await self.pepper.category(row["source"])
                await self.database.upsert_offers(offers)
                new = await self.database.unseen(row["id"], offers)
                for offer in new:
                    offer = await self.pepper.enrich(offer)
                    await self.notifier(row["telegram_user_id"], row["id"], offer)
                    stats["notifications"] += 1
                await self.database.mark_seen(row["id"], [item.thread_id for item in offers])
            except Exception:
                stats["errors"] += 1
                logger.exception("Subscription %s failed", row["id"])
        await self.database.save_watcher_stats(**stats)
        return stats

    async def run(self, interval: int, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await self.check_once()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), interval)
