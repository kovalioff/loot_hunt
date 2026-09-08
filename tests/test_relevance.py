from loot_hunt.pepper.models import Offer
from loot_hunt.search.models import PlannedQuery, SearchPlan
from loot_hunt.search.relevance import evaluate_offer, is_relevant


def plan(original: str, planned: PlannedQuery, intent: str = "broad") -> SearchPlan:
    return SearchPlan(original_query=original, intent=intent, queries=[planned])


def test_obviously_unrelated_result_is_rejected_generically():
    planned = PlannedQuery(
        query="wakacje Hiszpania", label="Hiszpania", category="travel", soft_terms=["wakacje"]
    )
    search_plan = plan("отдых в европе", planned, "category")
    rejected = evaluate_offer(
        Offer("1", "Samochód Lexus UX 300h", category="Motoryzacja"), planned, search_plan
    )
    assert not rejected.accepted and "below" in (rejected.rejection or "")
    assert is_relevant(
        Offer("2", "7 nocy all inclusive na Majorce, Hiszpania", category="Podróże"),
        planned,
        search_plan,
    )


def test_broad_object_terms_are_alternatives_not_blindly_all_hard():
    planned = PlannedQuery(
        query="robot sprzątający",
        label="Robot sprzątający",
        category="home",
        object_terms=["robot", "odkurzacz"],
    )
    search_plan = plan("ищу робот пылесос", planned)
    assert is_relevant(
        Offer("3", "Robot sprzątający Xiaomi Vacuum", category="Dom i mieszkanie"),
        planned,
        search_plan,
    )


def test_object_word_used_only_as_compatibility_target_is_rejected():
    planned = PlannedQuery(
        query="monitor", category="electronics", object_terms=["monitor", "ekran"]
    )
    search_plan = plan("дешевый монитор", planned)
    result = evaluate_offer(
        Offer(
            "camera",
            "Kamera FullHD na monitor z lampą LED",
            category="Elektronika",
        ),
        planned,
        search_plan,
    )
    assert not result.accepted and result.rejection == "object used as compatibility target"
    console = PlannedQuery(query="Xbox", category="gaming", object_terms=["konsola"])
    console_result = evaluate_offer(
        Offer("wheel", "Kierownica do konsol Xbox i PC", category="Gaming"),
        console,
        plan("игровая приставка", console),
    )
    assert not console_result.accepted
    assert console_result.rejection == "object used as compatibility target"


def test_soft_temporal_preference_does_not_reject_travel():
    planned = PlannedQuery(
        query="wakacje Grecja",
        label="Grecja",
        category="travel",
        object_terms=["wakacje", "hotel"],
        soft_terms=["wrzesień", "tanie"],
    )
    search_plan = plan("куда дешево слетать в сентябре", planned, "category")
    assert is_relevant(
        Offer("4", "Grecja all inclusive, 7 nocy", category="Podróże"), planned, search_plan
    )


def test_console_hardware_passes_but_game_and_controller_do_not():
    planned = PlannedQuery(
        query="PlayStation 5",
        label="PlayStation",
        category="gaming",
        object_terms=["konsola"],
        excluded_terms=["gra", "kontroler", "pad", "abonament"],
    )
    search_plan = plan("ищу игровую приставку", planned)
    assert is_relevant(
        Offer("5", "Sony PlayStation 5 Slim", category="Gaming"), planned, search_plan
    )
    assert not is_relevant(
        Offer("6", "Gra wyścigowa na PlayStation 5", category="Gaming"), planned, search_plan
    )
    assert not is_relevant(
        Offer("7", "Kontroler bezprzewodowy PlayStation 5", category="Gaming"),
        planned,
        search_plan,
    )


def test_excluded_subtype_rejects_even_when_parent_object_matches():
    planned = PlannedQuery(
        query="kawa ziarnista",
        category="grocery",
        object_terms=["kawa", "ziarna"],
        excluded_terms=["rozpuszczalna", "mielona"],
    )
    search_plan = plan("кофе в зернах", planned)
    result = evaluate_offer(
        Offer("instant", "Kawa rozpuszczalna Jacobs", category="Artykuły spożywcze"),
        planned,
        search_plan,
    )
    assert not result.accepted and result.rejection == "object mismatch: rozpuszczalna"


def test_explicit_oled_and_size_remain_hard():
    planned = PlannedQuery(
        query="telewizor OLED 65",
        category="electronics",
        required_terms=["OLED", "65"],
        object_terms=["telewizor", "TV"],
    )
    search_plan = plan("хороший телевизор OLED 65 дюймов", planned)
    assert is_relevant(
        Offer("8", 'Telewizor LG OLED 65"', category="Elektronika"), planned, search_plan
    )
    rejected = evaluate_offer(
        Offer("9", 'Telewizor LG OLED 55"', category="Elektronika"), planned, search_plan
    )
    assert not rejected.accepted and rejected.rejection == "missing hard term: 65"


def test_exact_model_requires_model_token_not_only_brand():
    planned = PlannedQuery(query="Makita DDF484", required_terms=["DDF484"])
    search_plan = plan("Makita DDF484", planned, "exact")
    assert is_relevant(Offer("10", "Wiertarko-wkrętarka Makita DDF484"), planned, search_plan)
    assert not is_relevant(Offer("11", "Zestaw bitów Makita B-66880"), planned, search_plan)


def test_fallback_direct_search_is_not_filtered():
    planned = PlannedQuery(query="непереведенный запрос")
    search_plan = plan("непереведенный запрос", planned, "fallback")
    assert is_relevant(Offer("12", "Dowolny wynik zwrócony przez Pepper"), planned, search_plan)
