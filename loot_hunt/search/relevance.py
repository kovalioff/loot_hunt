from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from loot_hunt.pepper.models import Offer

from .models import PlannedQuery, SearchPlan

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


def normalize(value: str | None) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
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
        patterns = (
            rf"\b(?:do|dla|na|pod)\s+{stem}\w*",
            rf"\b\w+\s*[/|]\s*{stem}\w*",
            rf"\b{stem}\w*\s*[/|]\s*\w+",
            rf"\b{stem}\w*\s+(?:i|oraz)\s+\w+",
        )
        for pattern in patterns:
            contexts.extend(match.span() for match in re.finditer(pattern, normalized_title))
    return bool(occurrences) and all(
        any(
            context_start <= start and end <= context_end for context_start, context_end in contexts
        )
        for start, end in occurrences
    )


def evaluate_offer(offer: Offer, planned: PlannedQuery, plan: SearchPlan) -> RelevanceResult:
    """Score a candidate while reserving rejection for genuine hard conflicts."""
    if offer.is_expired:
        return RelevanceResult(False, 0, (), "expired")
    if plan.intent == "fallback":
        return RelevanceResult(True, 1, ("direct fallback",))

    haystack = set(tokens(" ".join(filter(None, (offer.title, offer.category, offer.merchant)))))
    reasons: list[str] = []
    score = 0.0

    model_terms = {
        term
        for term in tokens(plan.original_query)
        if any(char.isalpha() for char in term) and any(char.isdigit() for char in term)
    }
    missing_models = sorted(term for term in model_terms if not _matches(term, haystack))
    if missing_models:
        return RelevanceResult(False, 0, (), "missing exact model: " + ", ".join(missing_models))
    if model_terms:
        score += 10 * len(model_terms)
        reasons.append("exact model")

    required = _groups(planned.required_terms)
    missing_required = [
        " ".join(group) for group in required if not _group_matches(group, haystack)
    ]
    if missing_required:
        return RelevanceResult(
            False, score, tuple(reasons), "missing hard term: " + ", ".join(missing_required)
        )
    if required:
        score += 6 * len(required)
        reasons.append(f"hard terms {len(required)}")

    if _category_matches(planned.category, offer.category):
        score += 3
        reasons.append("category")

    object_groups = _groups(planned.object_terms)
    object_matches = sum(_group_matches(group, haystack) for group in object_groups)
    if object_matches and _compatibility_only(object_groups, offer.title):
        return RelevanceResult(False, score, tuple(reasons), "object used as compatibility target")
    if object_matches:
        score += 4 + min(2, object_matches - 1)
        reasons.append(f"object {object_matches}")

    excluded = [
        group for group in _groups(planned.excluded_terms) if _group_matches(group, haystack)
    ]
    if excluded:
        return RelevanceResult(
            False,
            score,
            tuple(reasons),
            "object mismatch: " + ", ".join(" ".join(group) for group in excluded),
        )

    soft_groups = _groups(planned.soft_terms, minimum=3)
    matched_soft = [group for group in soft_groups if _group_matches(group, haystack)]
    soft_matches = len(matched_soft)
    if soft_matches:
        score += min(6, soft_matches * 2)
        reasons.append(f"soft {soft_matches}")
    if any(group[0] in MONTH_MATCHES for group in matched_soft):
        score += 3
        reasons.append("temporal")

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
    )


def is_relevant(offer: Offer, planned: PlannedQuery, plan: SearchPlan) -> bool:
    return evaluate_offer(offer, planned, plan).accepted
