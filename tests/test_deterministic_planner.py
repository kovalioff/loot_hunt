from loot_hunt.search.deterministic_planner import DeterministicSearchPlanner


def test_sort_mode_cheap_detection():
    planner = DeterministicSearchPlanner("pl")
    plan = planner.plan("хочу компьютер дешевый")
    assert plan.sort_mode == "cheap"
    assert [q.query for q in plan.queries] == ["komputer", "pc", "komputer stacjonarny"]
    assert plan.queries[0].category == "electronics"


def test_sort_mode_hot_and_temporal():
    planner = DeterministicSearchPlanner("pl")
    plan = planner.plan("самый горячий айфон со вчерашнего дня")
    assert plan.sort_mode == "hot"
    assert plan.temporal is not None
    assert plan.temporal.description == "since yesterday"
    assert any("iphone" in q.query for q in plan.queries)


def test_price_bounds_extraction():
    planner = DeterministicSearchPlanner("pl")
    plan = planner.plan("ноутбук от 1500 do 3500 zł")
    assert plan.min_price == 1500.0
    assert plan.max_price == 3500.0
    assert any("laptop" in q.query for q in plan.queries)


def test_german_localization():
    planner = DeterministicSearchPlanner("de")
    plan = planner.plan("billiger gaming pc")
    assert plan.sort_mode == "cheap"
    assert any("pc" in q.query for q in plan.queries)


def test_raw_sku_fallback():
    planner = DeterministicSearchPlanner("pl")
    plan = planner.plan("RTX 4070 ti super")
    assert plan.sort_mode == "fresh"
    assert [q.query for q in plan.queries] == ["RTX 4070 ti super"]
