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
    async def search(self, query):
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
    service = SearchService(planner, Pepper(), cap=25)
    result = await service.search("broad")
    assert planner.calls == 1
    assert [item.thread_id for item in result.offers] == ["2", "1"]
    assert service.page([Offer(str(i), str(i)) for i in range(12)], 1) == [
        Offer(str(i), str(i)) for i in range(5, 10)
    ]
