from datetime import date

from loot_hunt.pepper.models import Offer
from loot_hunt.search.models import (
    PlannedQuery,
    SearchPlan,
    SemanticConstraint,
    TemporalConstraint,
)
from loot_hunt.search.relevance import (
    evaluate_offer,
    extract_date_evidence,
    temporal_evidence,
)


def semantic_plan(**updates) -> SearchPlan:
    values = {
        "original_query": "request",
        "intent": "broad",
        "object_class": SemanticConstraint(name="jacket", evidence_terms=["kurtka", "płaszcz"]),
        "queries": [PlannedQuery(query="kurtka outdoor", category="fashion")],
    }
    values.update(updates)
    return SearchPlan(**values)


def test_user_hard_constraints_survive_every_generated_branch():
    hard = SemanticConstraint(
        name="waterproof",
        evidence_terms=["wodoodporna", "przeciwdeszczowa"],
        conflict_terms=["polar"],
    )
    queries = [
        PlannedQuery(query="kurtka trekkingowa", generated_expansions=["trekkingowa"]),
        PlannedQuery(query="kurtka outdoor", generated_expansions=["outdoor"]),
    ]
    plan = semantic_plan(hard_constraints=[hard], queries=queries)
    for query in queries:
        rejected = evaluate_offer(Offer("f", "Kurtka polarowa"), query, plan)
        assert not rejected.accepted and "hard constraint" in (rejected.rejection or "")
    assert evaluate_offer(Offer("w", "Kurtka trekkingowa wodoodporna"), queries[0], plan).accepted


def test_generated_entities_are_branch_expansions_not_global_hard_constraints():
    query = PlannedQuery(query="wakacje Grecja", generated_expansions=["Grecja"], label="Grecja")
    plan = SearchPlan(original_query="Europe holiday", intent="category", queries=[query])
    assert plan.hard_constraints == []
    assert evaluate_offer(Offer("s", "Wakacje Grecja"), query, plan).accepted


def test_strict_temporal_match_overlap_conflict_and_unknown():
    constraint = TemporalConstraint(required=True, month=9)
    assert temporal_evidence(Offer("a", "Loty 10-17.09"), constraint) == "MATCH"
    assert temporal_evidence(Offer("b", "Wyjazd 29.08-05.09"), constraint) == "MATCH"
    assert temporal_evidence(Offer("c", "Wakacje 12-19.10"), constraint) == "CONFLICT"
    assert temporal_evidence(Offer("d", "Tanie wakacje"), constraint) == "UNKNOWN"
    assert (
        temporal_evidence(
            Offer(
                "e",
                "Wyjazd tylko październik-listopad",
                merchant_url="https://travel.example/?from=2026-09-01&to=2026-12-01",
            ),
            constraint,
        )
        == "CONFLICT"
    )


def test_temporal_range_and_year_are_strict():
    constraint = TemporalConstraint(
        required=True, start_date=date(2027, 9, 10), end_date=date(2027, 9, 17)
    )
    assert temporal_evidence(Offer("a", "Lot 2027-09-12"), constraint) == "MATCH"
    assert temporal_evidence(Offer("b", "Lot 2027-10-12"), constraint) == "CONFLICT"


def test_merchant_url_and_compact_date_evidence_are_extracted():
    offer = Offer(
        "url",
        "Tanie loty",
        merchant_url="https://shop.example/trip/260924?dateIn=2026-09-30",
    )
    values = extract_date_evidence(offer.title, offer.merchant_url)
    assert date(2026, 9, 24) in values and date(2026, 9, 30) in values
    assert (
        temporal_evidence(offer, TemporalConstraint(required=True, month=9, year=2026)) == "MATCH"
    )


def test_all_polish_month_stems_are_recognized():
    names = [
        "styczniu",
        "lutym",
        "marcu",
        "kwietniu",
        "maju",
        "czerwcu",
        "lipcu",
        "sierpniu",
        "wrześniu",
        "październiku",
        "listopadzie",
        "grudniu",
    ]
    for month, name in enumerate(names, 1):
        assert (
            temporal_evidence(
                Offer(str(month), f"Wyjazd w {name}"),
                TemporalConstraint(required=True, month=month),
            )
            == "MATCH"
        )


def test_common_polish_month_abbreviations_are_recognized():
    for month, abbreviation in {1: "sty", 9: "wrz", 10: "paź", 11: "lis", 12: "gru"}.items():
        assert (
            temporal_evidence(
                Offer(str(month), f"Wyjazd {abbreviation}"),
                TemporalConstraint(required=True, month=month),
            )
            == "MATCH"
        )


def test_core_concept_provenance_is_valid_only_for_its_direct_query():
    concept = SemanticConstraint(name="mountain travel", evidence_terms=["góry", "Tatry"])
    query = PlannedQuery(
        query="wakacje Zakopane",
        label="Zakopane",
        supports_core_concepts=["mountain travel"],
    )
    plan = SearchPlan(
        original_query="mountain weekend",
        intent="category",
        core_concepts=[concept],
        queries=[query],
    )
    direct = evaluate_offer(Offer("z", "Weekend Zakopane"), query, plan)
    fallback = evaluate_offer(Offer("m", "Weekend Mallorca"), query, plan, source_kind="category")
    assert direct.accepted and direct.core_evidence == ("mountain travel (query)",)
    assert not fallback.accepted and fallback.rejection == "missing core concept evidence"


def test_fuzzy_search_provenance_cannot_validate_unrelated_offer():
    concept = SemanticConstraint(name="mountains", evidence_terms=["góry", "Tatry"])
    query = PlannedQuery(
        query="wakacje Zakopane",
        label="Zakopane",
        generated_expansions=["Zakopane"],
        supports_core_concepts=["mountains"],
    )
    plan = SearchPlan(
        original_query="mountain trip",
        intent="broad",
        object_class=SemanticConstraint(name="trip", evidence_terms=["wyjazd", "wakacje"]),
        core_concepts=[concept],
        queries=[query],
    )
    result = evaluate_offer(Offer("car", "Samochód Lexus UX 300h"), query, plan)
    assert not result.accepted and result.rejection == "object class unconfirmed by offer evidence"


def test_explicit_product_attribute_is_generic_plan_data():
    plan = semantic_plan(
        hard_constraints=[
            SemanticConstraint(
                name="required weather protection",
                evidence_terms=["wodoodporna", "membrana"],
            )
        ]
    )
    query = plan.queries[0]
    assert not evaluate_offer(Offer("x", "Kurtka softshell"), query, plan).accepted
    assert evaluate_offer(Offer("y", "Kurtka z membraną"), query, plan).accepted


def test_attribute_expansion_cannot_substitute_for_requested_object_class():
    query = PlannedQuery(
        query="kurtka wodoodporna",
        label="Wodoodporna kurtka",
        generated_expansions=["wodoodporna"],
    )
    plan = SearchPlan(
        original_query="waterproof jacket",
        intent="broad",
        object_class=SemanticConstraint(name="jacket", evidence_terms=["kurtka"]),
        hard_constraints=[SemanticConstraint(name="waterproof", evidence_terms=["wodoodporna"])],
        queries=[query],
    )
    assert evaluate_offer(Offer("j", "Kurtka wodoodporna"), query, plan).accepted
    assert not evaluate_offer(Offer("s", "Buty wodoodporne"), query, plan).accepted


def test_adjacent_class_risk_requires_primary_object_evidence():
    query = PlannedQuery(
        query="Xbox Series X", label="Xbox Series X", generated_expansions=["Xbox Series X"]
    )
    plan = SearchPlan(
        original_query="game console",
        intent="broad",
        object_class=SemanticConstraint(name="console", evidence_terms=["konsola"]),
        exclusions=[SemanticConstraint(name="games", evidence_terms=["gra", "gry"])],
        queries=[query],
    )
    assert evaluate_offer(Offer("c", "Konsola Xbox Series X 1TB"), query, plan).accepted
    assert not evaluate_offer(Offer("g", "Racing Collection Xbox Series X"), query, plan).accepted


def test_geographic_role_conflict_is_rejected_generically():
    query = PlannedQuery(query="Praga weekend", label="Praga", generated_expansions=["Praga"])
    plan = SearchPlan(
        original_query="weekend in Prague",
        intent="broad",
        geography=SemanticConstraint(
            name="destination Prague",
            evidence_terms=["Praga", "Pradze", "do Pragi"],
            conflict_terms=["z Pragi"],
        ),
        queries=[query],
    )
    assert evaluate_offer(Offer("to", "Weekend w Pradze"), query, plan).accepted
    result = evaluate_offer(Offer("from", "Loty z Pragi do San Francisco"), query, plan)
    assert not result.accepted and result.rejection == "geographic conflict: destination Prague"


def test_exact_named_service_requires_complete_planned_phrase():
    query = PlannedQuery(query="Adobe Creative Cloud")
    plan = SearchPlan(original_query="Adobe Creative Cloud", intent="exact", queries=[query])
    assert evaluate_offer(Offer("yes", "Adobe Creative Cloud subskrypcja"), query, plan).accepted
    assert not evaluate_offer(
        Offer("no", "Bezpłatny dostęp do Adobe Photoshop"), query, plan
    ).accepted


def test_semantic_plan_round_trip_preserves_all_fields():
    plan = SearchPlan(
        original_query="semantic request",
        intent="category",
        object_class=SemanticConstraint(name="trip", evidence_terms=["wyjazd"]),
        sort_mode="cheap",
        hard_constraints=[SemanticConstraint(name="direct", evidence_terms=["bezpośredni"])],
        soft_preferences=[SemanticConstraint(name="cheap", evidence_terms=["tani"])],
        core_concepts=[SemanticConstraint(name="beach", evidence_terms=["plaża"])],
        exclusions=[SemanticConstraint(name="used", evidence_terms=["używany"])],
        temporal=TemporalConstraint(required=True, month=8, year=2027),
        geography=SemanticConstraint(name="Europe", evidence_terms=["Europa"]),
        queries=[
            PlannedQuery(
                query="wakacje plaża",
                generated_expansions=["plaża"],
                supports_core_concepts=["beach"],
            )
        ],
    )
    restored = SearchPlan.model_validate_json(plan.model_dump_json())
    assert restored == plan
