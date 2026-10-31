"""Failures found by exercising the complete search pipeline during review."""
from unittest.mock import patch

import pytest

from loot_hunt.pepper.models import Offer
from loot_hunt.search.models import PlannedQuery, SearchPlan
from loot_hunt.search.planner import SearchPlanner
from loot_hunt.search.relevance import evaluate_offer
from loot_hunt.search.service import SearchService
from loot_hunt.search.spelling import correct_query, correct_single_word_typo
from loot_hunt.search.structural_relevance import evaluate_structural_relevance


class Source:
    def __init__(self, *offers):
        self.offers = list(offers)

    async def search(self, query, **kwargs):
        return self.offers if kwargs.get("page", 1) == 1 else []

    async def category(self, *args, **kwargs):
        return []

    async def enrich(self, offer, **kwargs):
        return offer


@pytest.mark.parametrize("query,expected", [
    ("gbwwf WH-1000XM5", "пицца WH-1000XM5"),
    ("Sony yjen,er DDR5", "Sony ноутбук DDR5"),
    ("нотубук WH-1000XM5 DDR5 RTX4060", "ноутбук WH-1000XM5 DDR5 RTX4060"),
    ("ноут бук", "ноутбук"),
    ("кофе машина DeLonghi", "кофемашина DeLonghi"),
])
def test_correction_preserves_model_bytes_and_known_brands(query, expected):
    assert correct_query(query).effective_query == expected


def test_ambiguous_fuzzy_correction_does_not_choose_a_random_set_member():
    with patch("loot_hunt.search.spelling.MULTI_DOMAIN_VOCABULARY", {"catz", "cats"}):
        assert correct_single_word_typo("catt") is None


@pytest.mark.parametrize("query,title", [
    ("наушники", "Słuchawki Sony bez przewodów"),
    ("iphone", "iPhone 15 ohne Vertrag"),
    ("пицца", "Pizza bez glutenu"),
    ("ноутбук", "Laptop bez abonamentu"),
    ("iphone", "iPhone ohne Defekte"),
])
def test_absence_of_contract_or_unwanted_ingredient_is_not_a_defect(query, title):
    assert evaluate_structural_relevance(query, title).level != "IRRELEVANT"


def test_uncertainty_penalty_never_admits_a_zero_evidence_offer():
    planned = PlannedQuery(query="laptop", object_terms=[])
    plan = SearchPlan(original_query="ноутбук", intent="broad", queries=[planned])
    evaluation = evaluate_offer(Offer("irrelevant", "Other"), planned, plan)
    assert evaluation.is_uncertain
    assert not evaluation.accepted
    assert evaluation.score == 0


async def test_corrected_query_is_used_for_evaluation_and_persisted_plan():
    result = await SearchService(SearchPlanner(None), Source(Offer("1", "Laptop Lenovo"))).search("yjen,er")
    assert result.spelling.original_query == "yjen,er"
    assert result.plan.original_query == "ноутбук"
    assert [o.thread_id for o in result.offers] == ["1"]


async def test_all_uncertain_results_do_not_claim_a_confident_match():
    result = await SearchService(SearchPlanner(None), Source(Offer("1", "Lenovo laptop"))).search("ноутбук")
    assert result.offers
    assert result.debug.offers["1"].is_uncertain
    assert not result.has_confident_matches
    assert result.debug.to_dict()["offers"][0]["uncertainty_reasons"]


async def test_original_query_can_be_searched_without_correction():
    result = await SearchService(SearchPlanner(None), Source()).search("нотубук", autocorrect=False)
    assert not result.spelling.was_corrected
    assert result.plan.original_query == "нотубук"
