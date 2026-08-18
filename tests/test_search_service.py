from datetime import UTC, datetime, timedelta

from loot_hunt.pepper.models import Offer
from loot_hunt.search.models import (
    PlannedQuery,
    SearchPlan,
    SemanticConstraint,
    TemporalConstraint,
)
from loot_hunt.search.service import MAX_PEPPER_REQUESTS, SearchService


class Planner:
    def __init__(self, plan):
        self.value = plan
        self.calls = 0

    async def plan(self, text):
        self.calls += 1
        return self.value


class Pepper:
    def __init__(self, pages=None, category_offers=None):
        self.pages = pages or {}
        self.category_offers = category_offers or []
        self.searches = []
        self.categories = []

    async def search(self, query, *, page=1, group_id=None):
        self.searches.append((query, page, group_id))
        return self.pages.get((query, page), [])

    async def category(self, path, *, page=1):
        self.categories.append((path, page))
        return self.category_offers

    async def enrich(self, offer):
        return offer


def monitor_plan(sort_mode="fresh"):
    return SearchPlan(
        original_query="monitor",
        intent="broad",
        sort_mode=sort_mode,
        queries=[
            PlannedQuery(
                query="monitor",
                label="Monitor",
                category="electronics",
                object_terms=["monitor"],
                soft_terms=["tani"],
            )
        ],
    )


def monitor(identifier, price, *, hours=0, temperature=0):
    return Offer(
        identifier,
        f"Monitor {identifier}",
        current_price=price,
        temperature=temperature,
        category="Elektronika",
        published_at=datetime.now(UTC) - timedelta(hours=hours),
    )


async def test_cheap_sorts_by_price_after_relevance_and_uses_page_two_when_sparse():
    planner = Planner(monitor_plan("cheap"))
    pepper = Pepper(
        {
            ("monitor", 1): [monitor("expensive", 879, hours=0)],
            ("monitor", 2): [monitor("cheap", 220, hours=4), monitor("mid", 455, hours=2)],
        }
    )
    result = await SearchService(planner, pepper).search("дешевый монитор")
    assert planner.calls == 1
    assert pepper.searches == [("monitor", 1, "131"), ("monitor", 2, "131")]
    assert [item.current_price for item in result.offers] == [220, 455, 879]


async def test_fresh_and_hot_sort_modes_are_deterministic():
    now = datetime.now(UTC)
    offers = [
        Offer("new", "Monitor new", temperature=10, category="Elektronika", published_at=now),
        Offer(
            "hot",
            "Monitor hot",
            temperature=500,
            category="Elektronika",
            published_at=now - timedelta(days=1),
        ),
    ]
    offers.extend(
        Offer(
            str(index),
            f"Monitor {index}",
            category="Elektronika",
            published_at=now - timedelta(days=2),
        )
        for index in range(13)
    )
    fresh = await SearchService(
        Planner(monitor_plan("fresh")), Pepper({("monitor", 1): offers})
    ).search("monitor")
    hot = await SearchService(
        Planner(monitor_plan("hot")), Pepper({("monitor", 1): offers})
    ).search("monitor")
    assert fresh.offers[0].thread_id == "new"
    assert hot.offers[0].thread_id == "hot"


async def test_no_extra_page_when_page_one_has_target_candidates():
    offers = [monitor(str(index), 100 + index) for index in range(15)]
    pepper = Pepper({("monitor", 1): offers})
    await SearchService(Planner(monitor_plan()), pepper).search("monitor")
    assert pepper.searches == [("monitor", 1, "131")]


async def test_global_request_bound_with_eight_queries():
    queries = [PlannedQuery(query=f"q{index}", label=f"Item {index}") for index in range(8)]
    plan = SearchPlan(original_query="items", intent="broad", queries=queries)
    pages = {
        (query.query, page): [Offer(f"{query.query}-{page}", f"Item {query.query} {page}")]
        for query in queries
        for page in (1, 2)
    }
    pepper = Pepper(pages)
    await SearchService(Planner(plan), pepper).search("items")
    assert len(pepper.searches) <= MAX_PEPPER_REQUESTS
    assert all(page <= 2 for _, page, _ in pepper.searches)


async def test_category_fallback_when_category_like_search_is_sparse():
    plan = SearchPlan(
        original_query="путешествие",
        intent="category",
        queries=[
            PlannedQuery(
                query="wakacje Grecja", label="Grecja", category="travel", soft_terms=["wrzesień"]
            )
        ],
    )
    pepper = Pepper(
        {("wakacje Grecja", 1): []},
        [Offer("travel", "Grecja urlop all inclusive", category="Podróże")],
    )
    result = await SearchService(Planner(plan), pepper).search("путешествие")
    assert pepper.categories == [("/grupa/podroze", 1)]
    assert [item.thread_id for item in result.offers] == ["travel"]
    assert result.debug and result.debug.requests[-1].source == "category"


async def test_category_object_retrieval_requires_planned_concept():
    plan = SearchPlan(
        original_query="дешевые полеты в сентябре",
        intent="category",
        sort_mode="cheap",
        queries=[
            PlannedQuery(
                query="loty Włochy",
                label="Włochy",
                category="travel",
                object_terms=["loty"],
                soft_terms=["wrzesień"],
            )
        ],
    )
    off_month = Offer(
        "off", "Tanie loty do Tallinna w styczniu", current_price=69, category="Podróże"
    )
    september = Offer(
        "sep", "Tanie loty do Włoch we wrześniu", current_price=134, category="Podróże"
    )
    pepper = Pepper(
        {
            ("loty Włochy", 1): [],
            ("loty", 1): [off_month, september],
            ("loty", 2): [],
        }
    )
    result = await SearchService(Planner(plan), pepper).search("дешевые полеты в сентябре")
    assert [item.thread_id for item in result.offers] == ["sep"]


async def test_broad_category_fallback_requires_more_than_category_only():
    plan = SearchPlan(
        original_query="отдых в европе",
        intent="broad",
        queries=[
            PlannedQuery(
                query="wakacje Grecja",
                label="Grecja",
                category="travel",
                object_terms=["wakacje", "urlop"],
            )
        ],
    )
    pepper = Pepper(
        {("wakacje Grecja", 1): []},
        [
            Offer("good", "Wakacje all inclusive", category="Podróże"),
            Offer("weak", "Bilet komunikacji miejskiej", category="Podróże"),
        ],
    )
    result = await SearchService(Planner(plan), pepper).search("отдых в европе")
    assert [item.thread_id for item in result.offers] == ["good"]


async def test_relaxed_constraint_query_improves_non_model_recall():
    plan = SearchPlan(
        original_query="телевизор OLED 65 дюймов",
        intent="broad",
        queries=[
            PlannedQuery(
                query="telewizor OLED 65 cali",
                category="electronics",
                required_terms=["OLED", "65"],
                object_terms=["telewizor", "TV"],
            )
        ],
    )
    offer = Offer("tv", 'Telewizor OLED 65"', category="Elektronika")
    pepper = Pepper({("telewizor OLED 65 cali", 1): [], ("telewizor OLED 65", 1): [offer]})
    result = await SearchService(Planner(plan), pepper).search("телевизор OLED 65 дюймов")
    assert ("telewizor OLED 65", 1, "131") in pepper.searches
    assert [item.thread_id for item in result.offers] == ["tv"]


async def test_broad_fresh_results_are_diverse_across_query_families():
    queries = [
        PlannedQuery(query=name, label=name, category="gaming")
        for name in ("PlayStation", "Xbox", "Nintendo")
    ]
    plan = SearchPlan(original_query="console", intent="broad", queries=queries)
    pages = {
        (query.query, 1): [
            Offer(
                f"{query.query}-{index}",
                f"{query.query} console {index}",
                category="Gaming",
                published_at=datetime.now(UTC) - timedelta(minutes=index),
            )
            for index in range(5)
        ]
        for query in queries
    }
    result = await SearchService(Planner(plan), Pepper(pages)).search("console")
    assert {item.thread_id.split("-", 1)[0] for item in result.offers[:3]} == {
        "PlayStation",
        "Xbox",
        "Nintendo",
    }


async def test_object_scoped_retrieval_confirms_hardware_without_title_noun():
    plan = SearchPlan(
        original_query="игровая приставка",
        intent="broad",
        queries=[
            PlannedQuery(
                query="Xbox Series X",
                label="Xbox Series X",
                category="gaming",
                required_terms=["Xbox"],
                object_terms=["konsola"],
                excluded_terms=["gra", "pad"],
            )
        ],
    )
    game = Offer("game", "Racing Collection Xbox Series X Store", category="Gaming")
    hardware = Offer("hardware", "Microsoft Xbox Series X 1TB", category="Gaming")
    pepper = Pepper(
        {
            ("Xbox Series X", 1): [game],
            ("konsola Xbox", 1): [hardware],
            ("konsola", 1): [],
            ("konsola Xbox", 2): [],
        }
    )
    result = await SearchService(Planner(plan), pepper).search("игровая приставка")
    assert [item.thread_id for item in result.offers] == ["hardware"]
    assert result.debug and result.debug.offers["game"].rejection.startswith(
        "object class unconfirmed"
    )


async def test_missing_price_does_not_beat_priced_offer_for_cheap_sort():
    offers = [monitor("unknown", None), monitor("priced", 300)]
    pepper = Pepper({("monitor", 1): offers, ("monitor", 2): []})
    result = await SearchService(Planner(monitor_plan("cheap")), pepper).search("cheap monitor")
    assert [item.thread_id for item in result.offers] == ["priced", "unknown"]


async def test_enriched_title_is_rechecked_before_display():
    plan = SearchPlan(
        original_query="кофемашина",
        intent="broad",
        queries=[
            PlannedQuery(
                query="ekspres",
                category="home",
                object_terms=["ekspres"],
                excluded_terms=["filtr"],
            )
        ],
    )

    class EnrichingPepper(Pepper):
        async def enrich(self, offer):
            return Offer(
                offer.thread_id,
                "Filtr do ekspresu DeLonghi",
                category="Dom i mieszkanie",
            )

    listing = Offer("filter", "Ekspres DeLonghi", category="Dom i mieszkanie")
    pepper = EnrichingPepper({("ekspres", 1): [listing], ("ekspres", 2): []})
    result = await SearchService(Planner(plan), pepper).search("кофемашина")
    assert result.offers == []


async def test_cheap_sort_happens_only_after_global_hard_constraints():
    plan = SearchPlan(
        original_query="monitor 27",
        intent="broad",
        object_class=SemanticConstraint(name="monitor", evidence_terms=["monitor"]),
        hard_constraints=[SemanticConstraint(name="27 inch", evidence_terms=["27"])],
        sort_mode="cheap",
        queries=[PlannedQuery(query="monitor 27", category="electronics")],
    )
    offers = [
        Offer("wrong", 'Monitor 24"', current_price=100, category="Elektronika"),
        Offer("right", 'Monitor 27"', current_price=500, category="Elektronika"),
    ]
    pepper = Pepper({("monitor 27", 1): offers, ("monitor 27", 2): []})
    result = await SearchService(Planner(plan), pepper).search("monitor 27")
    assert [item.thread_id for item in result.offers] == ["right"]


async def test_enriched_merchant_url_can_reject_wrong_explicit_month():
    plan = SearchPlan(
        original_query="September travel",
        intent="category",
        temporal=TemporalConstraint(required=True, month=9),
        queries=[PlannedQuery(query="wakacje", label="wakacje", category="travel")],
    )

    class DatedPepper(Pepper):
        async def enrich(self, offer):
            return Offer(
                offer.thread_id,
                offer.title,
                category=offer.category,
                merchant_url="https://travel.example/?dateOut=2026-10-12",
            )

    listing = Offer("trip", "Wakacje all inclusive", category="Podróże")
    pepper = DatedPepper({("wakacje", 1): [listing], ("wakacje", 2): []})
    result = await SearchService(Planner(plan), pepper).search("September travel")
    assert result.offers == []
    assert result.debug
    assert result.debug.offers["trip"].temporal_status == "CONFLICT"
