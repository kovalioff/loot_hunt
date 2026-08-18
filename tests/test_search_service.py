from datetime import UTC, datetime, timedelta

from loot_hunt.pepper.models import Offer
from loot_hunt.search.models import PlannedQuery, SearchPlan
from loot_hunt.search.service import SearchService


class Planner:
    calls = 0

    async def plan(self, text):
        self.calls += 1
        return SearchPlan(
            original_query=text,
            queries=[PlannedQuery(query="a"), PlannedQuery(query="b")],
        )


class Pepper:
    def __init__(self):
        self.searches = []

    async def search(self, query, *, group_id=None):
        self.searches.append((query, group_id))
        now = datetime.now(UTC)
        if query == "a":
            return [
                Offer("1", "old", published_at=now - timedelta(hours=1)),
                Offer("x", "expired", is_expired=True),
            ]
        return [Offer("1", "duplicate"), Offer("2", "fresh", temperature=10, published_at=now)]

    async def enrich(self, offer):
        return offer


async def test_one_plan_call_dedupe_filter_sort_and_pages():
    planner = Planner()
    pepper = Pepper()
    service = SearchService(planner, pepper, cap=25)
    result = await service.search("broad")
    assert planner.calls == 1
    assert pepper.searches == [("a", None), ("b", None)]
    assert [item.thread_id for item in result.offers] == ["2", "1"]
    assert service.page([Offer(str(i), str(i)) for i in range(12)], 1) == [
        Offer(str(i), str(i)) for i in range(5, 10)
    ]


async def test_category_scope_is_forwarded_without_more_planner_calls():
    class ScopedPlanner(Planner):
        async def plan(self, text):
            self.calls += 1
            return SearchPlan(
                original_query=text,
                intent="travel",
                queries=[
                    PlannedQuery(query="wakacje Hiszpania", label="Hiszpania", category="travel")
                ],
            )

    planner = ScopedPlanner()
    pepper = Pepper()
    await SearchService(planner, pepper).search("отдых в европе")
    assert planner.calls == 1
    assert pepper.searches == [("wakacje Hiszpania", "14")]
