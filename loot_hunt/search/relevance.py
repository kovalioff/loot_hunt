from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Literal
from urllib.parse import unquote

from loot_hunt.pepper.models import Offer

from .models import PlannedQuery, SearchPlan, SemanticConstraint, TemporalConstraint

TOKEN_RE = re.compile(r"[a-z0-9]+")
GENERIC_TERMS = frozenset(
    {
        "best",
        "cheap",
        "deal",
        "dla",
        "dobry",
        "good",
        "kupic",
        "najlepszy",
        "oferta",
        "okazja",
        "online",
        "promocja",
        "szukam",
        "tani",
        "tanie",
    }
)
CATEGORY_ALIASES = {
    "electronics": ("elektronika",),
    "gaming": ("gaming", "gry"),
    "home": ("dom i mieszkanie",),
    "garden": ("ogrod", "dom"),
    "fashion": ("moda",),
    "health": ("zdrowie", "uroda"),
    "family": ("dzieci",),
    "grocery": ("spozywcze",),
    "travel": ("podroze",),
    "auto": ("motoryzacja",),
    "culture": ("rozrywka", "kultura"),
    "sport": ("sport",),
    "telecom": ("internet", "telekomunikacja"),
    "services": ("uslugi", "subskrypcje"),
}
MIN_RELEVANCE_SCORE = 2.5
TemporalStatus = Literal["MATCH", "UNKNOWN", "CONFLICT", "NOT_REQUIRED"]
MONTH_ROOTS = {
    1: ("stycz",),
    2: ("lut",),
    3: ("marc",),
    4: ("kwiec", "kwiet"),
    5: ("maj",),
    6: ("czerw",),
    7: ("lip",),
    8: ("sierp",),
    9: ("wrzes",),
    10: ("pazdz",),
    11: ("listop",),
    12: ("grud",),
}
MONTH_ABBREVIATIONS = {
    1: ("sty",),
    3: ("mar",),
    4: ("kwi",),
    6: ("cze",),
    9: ("wrz",),
    10: ("paz",),
    11: ("lis",),
    12: ("gru",),
}
MONTH_MATCHES = {
    "styczen": ("stycz", "01"),
    "luty": ("lut", "02"),
    "marzec": ("marc", "03"),
    "kwiecien": ("kwiec", "04"),
    "maj": ("maj", "05"),
    "czerwiec": ("czerw", "06"),
    "lipiec": ("lip", "07"),
    "sierpien": ("sierp", "08"),
    "wrzesien": ("wrzes", "09"),
    "pazdziernik": ("pazdz", "10"),
    "listopad": ("listop", "11"),
    "grudzien": ("grud", "12"),
}


@dataclass(frozen=True, slots=True)
class RelevanceResult:
    accepted: bool
    score: float
    reasons: tuple[str, ...]
    rejection: str | None = None
    hard_status: str = "MATCH"
    temporal_status: TemporalStatus = "NOT_REQUIRED"
    core_evidence: tuple[str, ...] = ()


def normalize(value: str | None) -> str:
    decomposed = unicodedata.normalize("NFKD", unquote(value or ""))
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()


def tokens(value: str | None) -> tuple[str, ...]:
    return tuple(TOKEN_RE.findall(normalize(value)))


def _matches(anchor: str, haystack: set[str]) -> bool:
    if anchor in haystack:
        return True
    if month := MONTH_MATCHES.get(anchor):
        root, number = month
        return number in haystack or any(word.startswith(root) for word in haystack)
    if len(anchor) < 7:
        return False
    stem = anchor[:6]
    return any(len(word) >= len(stem) and word.startswith(stem) for word in haystack)


def _groups(values: list[str], *, minimum: int = 2) -> tuple[tuple[str, ...], ...]:
    return tuple(
        group
        for value in values
        if (
            group := tuple(
                token
                for token in tokens(value)
                if len(token) >= minimum and token not in GENERIC_TERMS
            )
        )
    )


def _group_matches(group: tuple[str, ...], haystack: set[str]) -> bool:
    return all(_matches(term, haystack) for term in group)


def _constraint_matches(value: SemanticConstraint, haystack: set[str]) -> bool:
    return any(_group_matches(group, haystack) for group in _groups(value.evidence_terms))


def _constraint_conflicts(value: SemanticConstraint, haystack: set[str]) -> bool:
    return any(_group_matches(group, haystack) for group in _groups(value.conflict_terms))


def _category_matches(scope: str | None, category: str | None) -> bool:
    normalized = normalize(category)
    aliases = CATEGORY_ALIASES.get(scope or "", ())
    return bool(normalized and any(term in normalized for term in aliases))


def _compatibility_only(object_groups: tuple[tuple[str, ...], ...], title: str) -> bool:
    normalized_title = normalize(title)
    title_tokens = tokens(normalized_title)
    matched_terms = {
        term
        for group in object_groups
        for term in group
        if any(_matches(term, {word}) for word in title_tokens)
    }
    if not matched_terms:
        return False
    occurrences: list[tuple[int, int]] = []
    contexts: list[tuple[int, int]] = []
    for term in matched_terms:
        stem = re.escape(term[:6] if len(term) >= 7 else term)
        occurrences.extend(match.span() for match in re.finditer(rf"\b{stem}\w*", normalized_title))
        for pattern in (
            rf"\b(?:do|dla|na|pod)\s+{stem}\w*",
            rf"\b\w+\s*[/|]\s*{stem}\w*",
            rf"\b{stem}\w*\s*[/|]\s*\w+",
            rf"\b{stem}\w*\s+(?:i|oraz)\s+\w+",
        ):
            contexts.extend(match.span() for match in re.finditer(pattern, normalized_title))
    return bool(occurrences) and all(
        any(start <= left and right <= end for start, end in contexts)
        for left, right in occurrences
    )


def _valid_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def extract_date_evidence(title: str | None, merchant_url: str | None) -> tuple[date, ...]:
    """Extract generic Polish/numeric dates without merchant-specific rules."""
    text = normalize(" ".join(filter(None, (title, merchant_url))))
    found: set[date] = set()
    for year, month, day in re.findall(r"(?<!\d)(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)", text):
        if value := _valid_date(int(year), int(month), int(day)):
            found.add(value)
    explicit_years = [int(value) for value in re.findall(r"(?<!\d)(20\d{2})(?!\d)", text)]
    inferred_year = explicit_years[0] if len(set(explicit_years)) == 1 else 2000
    for day, month, year in re.findall(
        r"(?=(?<!\d)(\d{1,2})[.-](\d{1,2})(?:[.-](20\d{2}))?(?!\d))", text
    ):
        if value := _valid_date(int(year) if year else inferred_year, int(month), int(day)):
            found.add(value)
    for compact in re.findall(r"(?<!\d)(2\d)(0[1-9]|1[0-2])([0-3]\d)(?!\d)", text):
        if value := _valid_date(2000 + int(compact[0]), int(compact[1]), int(compact[2])):
            found.add(value)
    return tuple(sorted(found))


def _month_evidence(title: str | None, merchant_url: str | None) -> set[int]:
    text = normalize(" ".join(filter(None, (title, merchant_url))))
    return {
        month
        for month, roots in MONTH_ROOTS.items()
        if any(re.search(rf"\b{root}\w*", text) for root in roots)
        or any(
            re.search(rf"\b{abbreviation}\b", text)
            for abbreviation in MONTH_ABBREVIATIONS.get(month, ())
        )
    }


def temporal_evidence(offer: Offer, constraint: TemporalConstraint | None) -> TemporalStatus:
    if not constraint or not constraint.required:
        return "NOT_REQUIRED"
    title_dates = extract_date_evidence(offer.title, None)
    title_months = _month_evidence(offer.title, None)
    if title_dates or title_months:
        return _classify_temporal(title_dates, title_months, constraint)
    return _classify_temporal(
        extract_date_evidence(None, offer.merchant_url),
        _month_evidence(None, offer.merchant_url),
        constraint,
    )


def _classify_temporal(
    dates: tuple[date, ...], months: set[int], constraint: TemporalConstraint
) -> TemporalStatus:
    has_evidence = bool(dates or months)
    if constraint.start_date or constraint.end_date:
        start = constraint.start_date or date.min
        end = constraint.end_date or date.max
        if any(start <= value <= end for value in dates if value.year != 2000):
            return "MATCH"
        if dates:
            return "CONFLICT"
    if constraint.month:
        for value in dates:
            year_ok = not constraint.year or value.year in {2000, constraint.year}
            if value.month == constraint.month and year_ok:
                return "MATCH"
        if constraint.month in months:
            return "MATCH"
        if has_evidence:
            return "CONFLICT"
    if constraint.year:
        years = {value.year for value in dates if value.year != 2000}
        if constraint.year in years:
            return "MATCH"
        if years:
            return "CONFLICT"
    return "UNKNOWN"


def _branch_matches(planned: PlannedQuery, haystack: set[str]) -> bool:
    values = [*planned.generated_expansions]
    if planned.label:
        values.append(planned.label)
    return any(_group_matches(group, haystack) for group in _groups(values, minimum=3))


def _label_matches(planned: PlannedQuery, haystack: set[str]) -> bool:
    return bool(planned.label) and any(
        _group_matches(group, haystack) for group in _groups([planned.label], minimum=3)
    )


def _branch_compatibility_only(planned: PlannedQuery, title: str) -> bool:
    values = [*planned.generated_expansions]
    if planned.label:
        values.append(planned.label)
    groups = _groups(values, minimum=3)
    return bool(groups) and _compatibility_only(groups, title)


def evaluate_offer(
    offer: Offer,
    planned: PlannedQuery,
    plan: SearchPlan,
    *,
    source_kind: str = "search",
) -> RelevanceResult:
    """Apply global user semantics to every retrieval branch, then score relevance."""
    if offer.is_expired:
        return RelevanceResult(False, 0, (), "expired")
    if plan.intent == "fallback":
        return RelevanceResult(True, 1, ("direct fallback",))

    haystack = set(
        tokens(
            " ".join(
                filter(None, (offer.title, offer.category, offer.merchant, offer.merchant_url))
            )
        )
    )
    reasons: list[str] = []
    score = 0.0

    model_terms = {
        term
        for term in tokens(plan.original_query)
        if any(char.isalpha() for char in term) and any(char.isdigit() for char in term)
    }
    missing_models = sorted(term for term in model_terms if not _matches(term, haystack))
    if plan.intent == "exact" and missing_models:
        return RelevanceResult(
            False, 0, (), "missing exact model: " + ", ".join(missing_models), "MISSING"
        )
    if model_terms and not missing_models:
        score += 10 * len(model_terms)
        reasons.append("exact model")
    exact_query_groups = _groups([planned.query], minimum=2)
    exact_query_match = any(_group_matches(group, haystack) for group in exact_query_groups)
    if plan.intent == "exact" and exact_query_groups and not exact_query_match:
        return RelevanceResult(False, score, tuple(reasons), "exact query phrase not confirmed")
    if plan.intent == "exact" and exact_query_match:
        score += 10
        reasons.append("exact query")

    global_hard = plan.hard_constraints
    missing_hard = [item.name for item in global_hard if not _constraint_matches(item, haystack)]
    conflicting_hard = [item.name for item in global_hard if _constraint_conflicts(item, haystack)]
    if conflicting_hard or missing_hard:
        label = "conflicting" if conflicting_hard else "missing"
        values = conflicting_hard or missing_hard
        return RelevanceResult(
            False,
            score,
            tuple(reasons),
            f"{label} hard constraint: {', '.join(values)}",
            "CONFLICT" if conflicting_hard else "MISSING",
        )
    if global_hard:
        score += 6 * len(global_hard)
        reasons.append(f"hard terms {len(global_hard)}")

    required = _groups(planned.required_terms)
    missing_required = [
        " ".join(group) for group in required if not _group_matches(group, haystack)
    ]
    if missing_required:
        return RelevanceResult(
            False,
            score,
            tuple(reasons),
            "missing hard term: " + ", ".join(missing_required),
            "MISSING",
        )
    if required:
        score += 6 * len(required)
        reasons.append(f"hard terms {len(required)}")

    temporal_status = temporal_evidence(offer, plan.temporal)
    if temporal_status == "CONFLICT":
        return RelevanceResult(
            False, score, tuple(reasons), "explicit temporal conflict", "MATCH", temporal_status
        )
    if temporal_status == "MATCH":
        score += 8
        reasons.append("temporal")

    if plan.geography:
        if _constraint_conflicts(plan.geography, haystack):
            return RelevanceResult(
                False,
                score,
                tuple(reasons),
                "geographic conflict: " + plan.geography.name,
            )
        if not _constraint_matches(plan.geography, haystack) and not _branch_matches(
            planned, haystack
        ):
            return RelevanceResult(
                False,
                score,
                tuple(reasons),
                "geography unconfirmed: " + plan.geography.name,
            )
        score += 5
        reasons.append("geography")

    global_exclusions = [
        item
        for item in plan.exclusions
        if _constraint_matches(item, haystack) or _constraint_conflicts(item, haystack)
    ]
    if global_exclusions:
        return RelevanceResult(
            False,
            score,
            tuple(reasons),
            "excluded: " + ", ".join(item.name for item in global_exclusions),
        )

    if _category_matches(planned.category, offer.category):
        score += 3
        reasons.append("category")

    object_terms = list(planned.object_terms)
    if plan.object_class:
        object_terms.extend(plan.object_class.evidence_terms)
    object_groups = _groups(object_terms)
    object_matches = sum(_group_matches(group, haystack) for group in object_groups)
    if object_matches and _compatibility_only(object_groups, offer.title):
        return RelevanceResult(False, score, tuple(reasons), "object used as compatibility target")
    if object_matches:
        score += 4 + min(2, object_matches - 1)
        reasons.append(f"object {object_matches}")
    branch_matches = _branch_matches(planned, haystack)
    if branch_matches and _branch_compatibility_only(planned, offer.title):
        return RelevanceResult(
            False,
            score,
            tuple(reasons),
            "retrieval entity used only as compatibility target",
            "MISSING",
            temporal_status,
        )
    object_unconfirmed = plan.object_class and not object_matches
    if object_unconfirmed and (plan.exclusions or not _label_matches(planned, haystack)):
        return RelevanceResult(
            False,
            score,
            tuple(reasons),
            "object class unconfirmed by offer evidence",
            "MISSING",
            temporal_status,
        )

    excluded_terms = [*planned.excluded_terms]
    excluded = [group for group in _groups(excluded_terms) if _group_matches(group, haystack)]
    if excluded:
        return RelevanceResult(
            False,
            score,
            tuple(reasons),
            "object mismatch: " + ", ".join(" ".join(group) for group in excluded),
        )

    core_evidence: list[str] = []
    for concept in plan.core_concepts:
        lexical = _constraint_matches(concept, haystack)
        provenance = (
            source_kind == "search"
            and branch_matches
            and concept.name in planned.supports_core_concepts
        )
        if lexical or provenance:
            core_evidence.append(concept.name + (" (query)" if provenance and not lexical else ""))
    if plan.core_concepts and len(core_evidence) != len(plan.core_concepts):
        return RelevanceResult(
            False,
            score,
            tuple(reasons),
            "missing core concept evidence",
            "MATCH",
            temporal_status,
            tuple(core_evidence),
        )
    if core_evidence:
        score += 7 * len(core_evidence)
        reasons.append(f"core {len(core_evidence)}")

    soft_values = [term for item in plan.soft_preferences for term in item.evidence_terms]
    soft_groups = _groups([*planned.soft_terms, *soft_values], minimum=3)
    soft_matches = sum(_group_matches(group, haystack) for group in soft_groups)
    if soft_matches:
        score += min(6, soft_matches * 2)
        reasons.append(f"soft {soft_matches}")

    label_terms = {
        term for term in tokens(planned.label) if len(term) >= 3 and term not in GENERIC_TERMS
    }
    label_matches = sum(_matches(term, haystack) for term in label_terms)
    if label_matches:
        score += min(4, label_matches * 2)
        reasons.append(f"label {label_matches}")

    query_terms = {
        term for term in tokens(planned.query) if len(term) >= 3 and term not in GENERIC_TERMS
    }
    query_matches = sum(_matches(term, haystack) for term in query_terms)
    if query_matches:
        score += min(3, query_matches * 0.75)
        reasons.append(f"query {query_matches}")

    accepted = score >= MIN_RELEVANCE_SCORE
    return RelevanceResult(
        accepted,
        score,
        tuple(reasons),
        None if accepted else f"score {score:g} below {MIN_RELEVANCE_SCORE:g}",
        "MATCH",
        temporal_status,
        tuple(core_evidence),
    )


def is_relevant(offer: Offer, planned: PlannedQuery, plan: SearchPlan) -> bool:
    return evaluate_offer(offer, planned, plan).accepted
