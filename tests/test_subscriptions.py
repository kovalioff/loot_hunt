from loot_hunt.database import Database
from loot_hunt.pepper.models import Offer
from loot_hunt.search.models import PlannedQuery, SearchPlan, SemanticConstraint, TemporalConstraint
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


async def test_zero_result_subscription_has_empty_baseline_and_keeps_semantics(tmp_path):
    db = Database(tmp_path / "empty.db")
    await db.connect()
    try:
        plan = SearchPlan(
            original_query="rare waterproof item",
            intent="broad",
            hard_constraints=[
                SemanticConstraint(name="waterproof", evidence_terms=["wodoodporny"])
            ],
            temporal=TemporalConstraint(required=True, month=9),
            queries=[PlannedQuery(query="rzadki przedmiot wodoodporny")],
        )
        identifier = await db.create_subscription(9, "search", "rare", "rare", [], plan)
        cursor = await db.db.execute(
            "SELECT count(*) FROM subscription_seen_threads WHERE subscription_id=?",
            (identifier,),
        )
        assert (await cursor.fetchone())[0] == 0
        row = (await db.subscriptions(9))[0]
        restored = SearchPlan.model_validate_json(row["plan_json"])
        assert restored == plan
    finally:
        await db.close()


async def test_purge_expired_sessions(tmp_path):
    db = Database(tmp_path / "sessions.db")
    await db.connect()
    try:
        plan = SearchPlan(original_query="q", queries=[PlannedQuery(query="q")])
        # expired session with ttl=-10
        await db.create_session(1, "query1", plan, [], ttl=-10)
        # valid session with ttl=3600
        valid_id = await db.create_session(1, "query2", plan, [], ttl=3600)
        purged = await db.purge_expired_sessions()
        assert purged == 1
        assert await db.get_session(valid_id, 1) is not None
    finally:
        await db.close()


async def test_watcher_pauses_blocked_user_subscription(tmp_path):
    db = Database(tmp_path / "blocked.db")
    await db.connect()

    async def blocked_notify(user_id, subscription_id, offer):
        raise RuntimeError("Forbidden: bot was blocked by the user")

    try:
        plan = SearchPlan(original_query="x", queries=[PlannedQuery(query="x")])
        await db.create_subscription(99, "search", "x", "x", [], plan)
        watcher = WatcherService(db, Search(), Pepper(), blocked_notify)
        await watcher.check_once()
        subs = await db.subscriptions(99)
        assert subs[0]["active"] == 0
    finally:
        await db.close()
