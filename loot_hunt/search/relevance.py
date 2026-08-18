from __future__ import annotations

import re
import unicodedata

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


def normalize(value: str | None) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()


def tokens(value: str | None) -> tuple[str, ...]:
    return tuple(TOKEN_RE.findall(normalize(value)))


def _matches(anchor: str, haystack: set[str]) -> bool:
    if anchor in haystack:
        return True
    if len(anchor) < 7:
        return False
    stem = anchor[:6]
    return any(len(word) >= 7 and word.startswith(stem) for word in haystack)


def is_relevant(offer: Offer, planned: PlannedQuery, plan: SearchPlan) -> bool:
    """Conservative lexical guard applied to each Pepper query's own results."""
    if plan.intent == "fallback":
        return True

    haystack = set(tokens(" ".join(filter(None, (offer.title, offer.category, offer.merchant)))))
    original_model_terms = {
        term
        for term in tokens(plan.original_query)
        if any(char.isalpha() for char in term) and any(char.isdigit() for char in term)
    }
    if original_model_terms:
        return all(_matches(term, haystack) for term in original_model_terms)

    object_terms = {
        token
        for value in planned.object_terms
        for token in tokens(value)
        if len(token) >= 2 and token not in GENERIC_TERMS
    }
    if object_terms and not all(_matches(term, haystack) for term in object_terms):
        return False

    required_terms = {
        token
        for value in planned.required_terms
        for token in tokens(value)
        if len(token) >= 2 and token not in GENERIC_TERMS
    }
    if required_terms:
        return all(_matches(term, haystack) for term in required_terms)

    label_terms = {
        term for term in tokens(planned.label) if len(term) >= 3 and term not in GENERIC_TERMS
    }
    if label_terms:
        return all(_matches(term, haystack) for term in label_terms)

    query_terms = {
        term for term in tokens(planned.query) if len(term) >= 3 and term not in GENERIC_TERMS
    }
    if not query_terms:
        return True
    return any(_matches(term, haystack) for term in query_terms)
