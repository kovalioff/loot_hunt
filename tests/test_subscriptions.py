from loot_hunt.database import Database
from loot_hunt.pepper.models import Offer
from loot_hunt.search.models import PlannedQuery, SearchPlan
from loot_hunt.watch.service import WatcherService


async def test_baseline_unseen_pause_resume_delete(tmp_path):
    db = Database(tmp_path / "test.db")
    await db.connect()
    try:
        plan = SearchPlan(original_query="x", queries=[PlannedQuery(query="x")])
        identifier = await db.create_subscription(7, "search", "x", "x", [Offer("1", "old")], plan)
        assert await db.unseen(identifier, [Offer("1", "old")]) == []
        assert [
            item.thread_id
            for item in await db.unseen(identifier, [Offer("1", "old"), Offer("2", "new")])
        ] == ["2"]
        assert await db.set_subscription(identifier, 7, "pause")
        assert not (await db.subscriptions(7))[0]["active"]
        assert await db.set_subscription(identifier, 7, "resume")
        assert (await db.subscriptions(7))[0]["active"]
        assert await db.set_subscription(identifier, 7, "delete")
        assert await db.subscriptions(7) == []
    finally:
        await db.close()


class Search:
    def __init__(self):
        self.planner = ExplodingPlanner()

    async def execute_plan(self, plan):
        return [Offer("old", "Old"), Offer("new", "New")]


class ExplodingPlanner:
    async def plan(self, text):
        raise AssertionError("watcher called Gemini")


class Pepper:
    async def category(self, path):
        return [Offer("category-new", "Category")]

    async def enrich(self, offer):
        return offer


async def test_watcher_reuses_plan_and_only_new_ids(tmp_path):
    db = Database(tmp_path / "watch.db")
    await db.connect()
    notifications = []

    async def notify(user_id, subscription_id, offer):
        notifications.append(offer.thread_id)

    try:
        plan = SearchPlan(original_query="x", queries=[PlannedQuery(query="polski x")])
        await db.create_subscription(1, "search", "x", "x", [Offer("old", "Old")], plan)
        await db.create_subscription(1, "category", "Cat", "/grupa/cat", [], None)
        watcher = WatcherService(db, Search(), Pepper(), notify)
        first = await watcher.check_once()
        second = await watcher.check_once()
        assert sorted(notifications) == ["category-new", "new"]
        assert first == {"checked": 2, "notifications": 2, "errors": 0}
        assert second["notifications"] == 0
    finally:
        await db.close()
