from types import SimpleNamespace

from loot_hunt.search.models import GeminiPlan, GeminiPlannedQuery
from loot_hunt.search.planner import SearchPlanner


class FakeModels:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        return self.response


async def test_no_key_falls_back_to_original():
    plan = await SearchPlanner(None).plan("sony wh-1000xm5")
    assert [item.query for item in plan.queries] == ["sony wh-1000xm5"]


async def test_pytest_never_calls_even_injected_realish_client():
    models = FakeModels(None)
    plan = await SearchPlanner("secret", client=SimpleNamespace(models=models)).plan("travel")
    assert models.calls == 0 and plan.intent == "fallback"


async def test_structured_one_call_dedupes_and_caps(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    parsed = GeminiPlan(
        intent="category",
        sort_mode="fresh",
        queries=[
            GeminiPlannedQuery(
                query=value,
                label=value.removeprefix("wakacje "),
                category="travel",
                required_terms=[],
                object_terms=[],
                soft_terms=[value.removeprefix("wakacje ")],
                excluded_terms=[],
            )
            for value in [
                "wakacje Hiszpania",
                "wakacje Grecja",
                "WAKACJE HISZPANIA",
                "wakacje Włochy",
                "wakacje Cypr",
                "wakacje Malta",
                "wakacje Portugalia",
                "wakacje Chorwacja",
            ]
        ],
    )
    models = FakeModels(SimpleNamespace(parsed=parsed, text=""))
    planner = SearchPlanner("injected", client=SimpleNamespace(models=models))
    plan = await planner.plan("ищу отдых в европе")
    assert models.calls == 1 and planner.calls == 1
    assert len(plan.queries) == 7
    assert len(plan.queries) <= 8
    assert plan.queries[0].query == "wakacje Hiszpania"
    assert all(item.category == "travel" for item in plan.queries)
    assert all(not item.soft_terms for item in plan.queries)


async def test_exact_sku_provider_plan_stays_narrow(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    parsed = GeminiPlan(
        intent="exact",
        sort_mode="fresh",
        queries=[
            GeminiPlannedQuery(
                query="Makita DDF484",
                label="Makita DDF484",
                required_terms=["DDF484"],
                object_terms=[],
                soft_terms=[],
                excluded_terms=[],
            )
        ],
    )
    models = FakeModels(SimpleNamespace(parsed=parsed, text=""))
    planner = SearchPlanner("injected", client=SimpleNamespace(models=models))
    plan = await planner.plan("Makita DDF484")
    assert models.calls == 1 and planner.calls == 1
    assert plan.intent == "exact"
    assert [item.query for item in plan.queries] == ["Makita DDF484"]


async def test_generated_alternatives_are_not_promoted_to_user_hard_constraints(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    parsed = GeminiPlan(
        intent="broad",
        sort_mode="fresh",
        queries=[
            GeminiPlannedQuery(
                query=name,
                label=name,
                category="gaming",
                required_terms=[name],
                object_terms=["konsola"],
                soft_terms=[],
                excluded_terms=["gra"],
            )
            for name in ("PlayStation 5", "Xbox Series X")
        ],
    )
    models = FakeModels(SimpleNamespace(parsed=parsed, text=""))
    planner = SearchPlanner("injected", client=SimpleNamespace(models=models))
    planned = await planner.plan("ищу игровую приставку")
    assert models.calls == 1
    assert all(not item.required_terms for item in planned.queries)


async def test_generic_named_entity_search_is_not_narrowed_to_invented_object(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    parsed = GeminiPlan(
        intent="broad",
        sort_mode="fresh",
        queries=[
            GeminiPlannedQuery(
                query="Xiaomi",
                label="Xiaomi",
                category="electronics",
                required_terms=["Xiaomi"],
                object_terms=["telefon", "smartfon"],
                soft_terms=[],
                excluded_terms=["etui"],
            )
        ],
    )
    models = FakeModels(SimpleNamespace(parsed=parsed, text=""))
    planned = await SearchPlanner("injected", client=SimpleNamespace(models=models)).plan(
        "покажи скидки Xiaomi"
    )
    assert planned.queries[0].object_terms == []


async def test_malformed_provider_response_falls_back(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    models = FakeModels(SimpleNamespace(parsed=None, text="not json"))
    plan = await SearchPlanner("injected", client=SimpleNamespace(models=models)).plan("sony xm5")
    assert models.calls == 1
    assert [item.query for item in plan.queries] == ["sony xm5"]


async def test_provider_wire_semantics_become_typed_global_plan(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    parsed = GeminiPlan(
        intent="broad",
        object_class="kurtka :: kurtka | płaszcz",
        sort_mode="fresh",
        hard_constraints=["waterproof :: wodoodporna | przeciwdeszczowa :: polarowa"],
        soft_preferences=["good :: polecana"],
        core_concepts=["outdoor use :: trekking | outdoor"],
        exclusions=["used :: używana"],
        geography=None,
        queries=[
            GeminiPlannedQuery(
                query="kurtka trekkingowa",
                label="Trekking",
                category="fashion",
                generated_expansions=["trekkingowa"],
                supports_core_concepts=["outdoor use :: trekking | outdoor"],
            )
        ],
    )
    planner = SearchPlanner(
        "injected", client=SimpleNamespace(models=FakeModels(SimpleNamespace(parsed=parsed)))
    )
    plan = await planner.plan("непромокаемая куртка")
    assert plan.object_class and plan.object_class.evidence_terms == ["kurtka", "płaszcz"]
    assert plan.hard_constraints[0].name == "waterproof"
    assert plan.hard_constraints[0].conflict_terms == ["polarowa"]
    assert plan.queries[0].supports_core_concepts == ["outdoor use"]


async def test_provider_cannot_invent_unstated_temporal_year(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    parsed = GeminiPlan(
        intent="category",
        sort_mode="cheap",
        temporal={
            "required": True,
            "start_date": "2024-09-01",
            "end_date": "2024-09-30",
            "month": 9,
            "year": 2024,
        },
        queries=[GeminiPlannedQuery(query="loty wrzesień", label="Wrzesień")],
    )
    planner = SearchPlanner(
        "injected", client=SimpleNamespace(models=FakeModels(SimpleNamespace(parsed=parsed)))
    )
    plan = await planner.plan("куда слетать в сентябре")
    assert plan.temporal
    assert plan.temporal.month == 9
    assert plan.temporal.year is None
    assert plan.temporal.start_date is None and plan.temporal.end_date is None
