from loot_hunt.pepper.models import Offer
from loot_hunt.search.models import PlannedQuery, SearchPlan
from loot_hunt.search.relevance import is_relevant


def plan(original: str, query: str, label: str, intent: str = "broad"):
    planned = PlannedQuery(query=query, label=label)
    return planned, SearchPlan(original_query=original, intent=intent, queries=[planned])


def test_obviously_unrelated_result_is_rejected_generically():
    planned, search_plan = plan("отдых в европе", "wakacje Hiszpania", "Hiszpania")
    assert not is_relevant(
        Offer("1", "Samochód Lexus UX 300h", category="Motoryzacja"),
        planned,
        search_plan,
    )
    assert is_relevant(
        Offer("2", "7 nocy all inclusive na Majorce, Hiszpania", category="Podróże"),
        planned,
        search_plan,
    )


def test_legitimate_variant_wording_is_not_overfiltered():
    planned, search_plan = plan("ищу робот пылесос", "robot sprzątający Dreame", "Dreame")
    assert is_relevant(
        Offer("3", "Odkurzacz automatyczny Dreame L40 Ultra"),
        planned,
        search_plan,
    )


def test_multiword_anchor_rejects_related_but_wrong_product_type():
    planned, search_plan = plan(
        "ищу игровую приставку", "konsola PlayStation 5", "konsola PlayStation"
    )
    assert is_relevant(
        Offer("7", "Konsola Sony PlayStation 5 Slim"),
        planned,
        search_plan,
    )
    assert not is_relevant(
        Offer("8", "Gra wyścigowa na PlayStation 5"),
        planned,
        search_plan,
    )


def test_required_terms_take_priority_over_loose_label():
    planned = PlannedQuery(
        query="PlayStation 5",
        label="PlayStation 5",
        category="gaming",
        required_terms=["konsola", "PlayStation"],
        object_terms=["konsola"],
    )
    search_plan = SearchPlan(
        original_query="ищу игровую приставку", intent="broad", queries=[planned]
    )
    assert is_relevant(Offer("9", "Konsola Sony PlayStation 5 Slim"), planned, search_plan)
    assert not is_relevant(Offer("10", "Gra na PlayStation 5"), planned, search_plan)


def test_object_terms_reject_related_entity_in_wrong_form():
    planned = PlannedQuery(
        query="Roborock",
        label="Roborock",
        category="home",
        required_terms=["Roborock"],
        object_terms=["robot", "odkurzacz"],
    )
    search_plan = SearchPlan(original_query="ищу робот пылесос", intent="broad", queries=[planned])
    assert is_relevant(
        Offer("11", "Robot odkurzająco-mopujący Roborock Qrevo"),
        planned,
        search_plan,
    )
    assert not is_relevant(
        Offer("12", "Ręczny odkurzacz mopujący Roborock F25"),
        planned,
        search_plan,
    )


def test_exact_model_requires_model_token_not_only_brand():
    planned, search_plan = plan("Makita DDF484", "Makita DDF484", "Makita DDF484", "exact")
    assert is_relevant(Offer("4", "Wiertarko-wkrętarka Makita DDF484"), planned, search_plan)
    assert not is_relevant(Offer("5", "Zestaw bitów Makita B-66880"), planned, search_plan)


def test_fallback_direct_search_is_not_filtered():
    planned, search_plan = plan("непереведенный запрос", "непереведенный запрос", "", "fallback")
    assert is_relevant(Offer("6", "Dowolny wynik zwrócony przez Pepper"), planned, search_plan)
