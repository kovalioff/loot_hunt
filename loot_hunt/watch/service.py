from __future__ import annotations

import asyncio
import contextlib
import logging

from loot_hunt.search.models import SearchPlan

logger = logging.getLogger(__name__)


class WatcherService:
    """Replays persisted sources. It deliberately has no SearchPlanner dependency."""

    def __init__(
        self,
        database,
        search_service,
        pepper,
        notifier,
        *,
        channel_publisher=None,
    ) -> None:
        self.database = database
        self.search_service = search_service
        self.pepper = pepper
        self.notifier = notifier
        self.channel_publisher = channel_publisher

    async def check_once(self) -> dict[str, int]:
        with contextlib.suppress(Exception):
            await self.database.purge_expired_sessions()
        stats = {"checked": 0, "notifications": 0, "errors": 0}
        rows = await self.database.subscriptions(active_only=True)
        for row in rows:
            stats["checked"] += 1
            try:
                platform_code = (
                    row["platform"]
                    if "platform" in row and row["platform"]
                    else "pl"
                )
                if row["kind"] == "search":
                    plan = SearchPlan.model_validate_json(row["plan_json"])
                    target_platform = getattr(plan, "platform", None) or platform_code
                    try:
                        offers = await self.search_service.execute_plan(
                            plan, platform=target_platform
                        )
                    except TypeError:
                        offers = await self.search_service.execute_plan(plan)
                else:
                    try:
                        offers = await self.pepper.category(row["source"], platform=platform_code)
                    except TypeError:
                        offers = await self.pepper.category(row["source"])
                await self.database.upsert_offers(offers)
                new = await self.database.unseen(row["id"], offers)
                user_blocked = False
                for offer in new:
                    try:
                        offer = await self.pepper.enrich(offer, platform=platform_code)
                    except TypeError:
                        offer = await self.pepper.enrich(offer)
                    if self.channel_publisher:
                        with contextlib.suppress(Exception):
                            await self.channel_publisher.maybe_publish(offer)
                    try:
                        await self.notifier(row["telegram_user_id"], row["id"], offer)
                        stats["notifications"] += 1
                    except Exception as notify_exc:
                        err_msg = str(notify_exc).lower()
                        if any(term in err_msg for term in ("forbidden", "blocked", "deactivated")):
                            logger.info(
                                "User %s blocked bot; pausing sub %s",
                                row["telegram_user_id"],
                                row["id"],
                            )
                            await self.database.set_subscription(
                                row["id"], row["telegram_user_id"], "pause"
                            )
                            user_blocked = True
                            break
                        raise
                if not user_blocked:
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
