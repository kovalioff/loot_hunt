from loot_hunt.pepper.models import Offer
from loot_hunt.search.deterministic_planner import DeterministicSearchPlanner
from loot_hunt.search.relevance import evaluate_offer


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


def test_price_bound_is_not_a_hard_constraint():
    planner = DeterministicSearchPlanner("pl")
    plan = planner.plan("наушники до 300 zł")
    assert plan.max_price == 300.0
    assert plan.hard_constraints == []
    offer = Offer("1", "Słuchawki Sony WH-CH520", current_price=199, category="Elektronika")
    result = evaluate_offer(offer, plan.queries[0], plan)
    assert result.accepted, result.rejection


def test_numbers_for_time_or_count_are_not_price_bounds():
    planner = DeterministicSearchPlanner("pl")
    assert planner.plan("lego do 5 lat").max_price is None
    assert planner.plan("игрушки от 2 лет").min_price is None


def test_inverted_price_bounds_are_ignored():
    plan = DeterministicSearchPlanner("pl").plan("монитор от 3000 до 1000 zł")
    assert plan.min_price is None and plan.max_price is None


def test_keyword_mode_accepts_polish_title_without_category():
    plan = DeterministicSearchPlanner("pl").plan("наушники")
    assert plan.keyword_mode is True
    offer = Offer("1", "Słuchawki Sony WH-CH520", current_price=199)
    result = evaluate_offer(offer, plan.queries[0], plan)
    assert result.accepted, result.rejection


def test_keyword_mode_does_not_accept_untranslated_queries():
    plan = DeterministicSearchPlanner("pl").plan("холодильник")
    offer = Offer("1", "Lodówka Samsung No Frost", current_price=1999)
    assert not evaluate_offer(offer, plan.queries[0], plan).accepted


def test_relative_freshness_is_recorded_for_published_at_checks():
    planner = DeterministicSearchPlanner("pl")
    assert planner.plan("наушники сегодня").temporal.freshness_days == 0
    assert planner.plan("наушники со вчерашнего дня").temporal.freshness_days == 1
    assert planner.plan("наушники за неделю").temporal.freshness_days == 7


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
