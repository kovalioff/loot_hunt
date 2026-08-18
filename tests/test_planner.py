from types import SimpleNamespace

from loot_hunt.search.models import GeminiPlan, PlannedQuery
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
        intent="travel",
        queries=[
            PlannedQuery(query=value)
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
    assert plan.queries[0].query == "wakacje Hiszpania"


async def test_malformed_provider_response_falls_back(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    models = FakeModels(SimpleNamespace(parsed=None, text="not json"))
    plan = await SearchPlanner("injected", client=SimpleNamespace(models=models)).plan("sony xm5")
    assert models.calls == 1
    assert [item.query for item in plan.queries] == ["sony xm5"]
