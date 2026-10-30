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

    async def notify(user_id, subscription_id, offers):
        notifications.extend(item.thread_id for item in offers)

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

    async def blocked_notify(user_id, subscription_id, offers):
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


class PlatformPepper:
    def __init__(self):
        self.calls = []

    async def category(self, path, *, platform="pl"):
        self.calls.append((path, platform))
        return []

    async def enrich(self, offer, *, platform="pl"):
        return offer


async def test_watcher_uses_stored_platform_for_category_subscription(tmp_path):
    db = Database(tmp_path / "platform.db")
    await db.connect()
    pepper = PlatformPepper()

    async def notify(user_id, subscription_id, offers):
        raise AssertionError("no offers expected")

    try:
        await db.create_subscription(1, "category", "Cat", "/grupa/cat", [], None, platform="de")
        watcher = WatcherService(db, Search(), pepper, notify)
        await watcher.check_once()
        assert pepper.calls == [("/grupa/cat", "de")]
    finally:
        await db.close()


async def test_purge_stale_offers(tmp_path):
    db = Database(tmp_path / "offers.db")
    await db.connect()
    try:
        await db.upsert_offers([Offer("old", "Old"), Offer("new", "New")])
        await db.db.execute(
            "UPDATE offers SET last_seen_at='2000-01-01T00:00:00+00:00' WHERE thread_id='old'"
        )
        await db.db.commit()
        assert await db.purge_stale_offers(days=30) == 1
        cursor = await db.db.execute("SELECT thread_id FROM offers ORDER BY thread_id")
        assert [row[0] for row in await cursor.fetchall()] == ["new"]
    finally:
        await db.close()


async def test_create_subscription_is_idempotent(tmp_path):
    db = Database(tmp_path / "idempotent.db")
    await db.connect()
    try:
        plan = SearchPlan(original_query="x", queries=[PlannedQuery(query="x")])
        first = await db.create_subscription(1, "search", "x", "x", [Offer("1", "old")], plan)
        second = await db.create_subscription(1, "search", "x", "x", [Offer("2", "new")], plan)
        assert first == second
        assert len(await db.subscriptions(1)) == 1
        unseen = await db.unseen(second, [Offer("1", "old"), Offer("2", "new"), Offer("3", "new")])
        assert [item.thread_id for item in unseen] == ["3"]
    finally:
        await db.close()


async def test_resume_respects_subscription_limit(tmp_path):
    db = Database(tmp_path / "limit.db")
    await db.connect()
    try:
        plan = SearchPlan(original_query="x", queries=[PlannedQuery(query="x")])
        identifiers = [
            await db.create_subscription(1, "search", f"q{index}", f"q{index}", [], plan)
            for index in range(3)
        ]
        paused = await db.create_subscription(1, "search", "q3", "q3", [], plan)
        await db.set_subscription(paused, 1, "pause")
        assert await db.set_subscription(paused, 1, "resume") is False
        await db.set_subscription(identifiers[0], 1, "pause")
        assert await db.set_subscription(paused, 1, "resume") is True
    finally:
        await db.close()


async def test_duplicate_subscriptions_are_collapsed_on_connect(tmp_path):
    path = tmp_path / "duplicates.db"
    db = Database(path)
    await db.connect()
    await db.db.execute("DROP INDEX idx_subscriptions_source")
    for label in ("first", "second"):
        await db.db.execute(
            """INSERT INTO subscriptions(
                telegram_user_id,kind,label,source,plan_json,platform,active,created_at
            ) VALUES(1,'search',?,'same',NULL,'pl',1,'2026-01-01')""",
            (label,),
        )
    await db.db.commit()
    await db.close()

    reopened = Database(path)
    await reopened.connect()
    try:
        rows = await reopened.subscriptions(1)
        assert len(rows) == 1 and rows[0]["label"] == "second"
    finally:
        await reopened.close()
