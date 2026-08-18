from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from google import genai
from google.genai import types

from .models import GeminiPlan, PlannedQuery, SearchPlan

logger = logging.getLogger(__name__)
MODEL = "gemini-3.5-flash-lite"
SYSTEM_PROMPT = """You plan candidate retrieval for Pepper.pl, a Polish deal community.
Understand Russian and other languages and produce natural Polish search phrases.
Preserve exact model, SKU, brand, and code strings.
Classify intent as exactly one of:
- exact: an explicit model, SKU, or named exact platform/version identifier;
- broad: a product/object request that benefits from several concrete searches;
- category: open-ended discovery in a domain, including destination/holiday discovery.
Attribute combinations such as an OLED TV size are constrained product searches, not an
exact model/SKU merely because several attributes were supplied. Open-ended travel and
destination requests should be category intent even when several destination queries are used.
For an exact model, SKU, platform, or named product, return one query (very rarely two)
and do not add alternatives that change the requested product.
For a broad request, decompose it into diverse CONCRETE entities that people put in
Pepper titles: specific destinations, product families, platforms, brands, or use cases.
Do not return several abstract paraphrases of the same broad request. For example,
broad European travel should become concrete destination searches, not generic phrases
such as 'wakacje w Europie', 'city break Europa', or 'all inclusive Europa'.
Each label must be a short human-readable concrete entity.
Use required_terms ONLY for genuinely hard literal constraints explicitly stated by the
user: exact model/SKU tokens, OLED, an essential size/storage value, or an explicitly
requested platform/version. Never put cheap/good/recommended, months, seasons, Europe,
travel intent, generic object nouns, or generated destinations in required_terms.
object_terms are alternative Polish nouns that identify the requested object class and
help scoring; they are NOT all mandatory. soft_terms are preferences/concepts useful for
scoring but never hard title requirements. excluded_terms are concise Polish words that
strongly signal adjacent unwanted content, such as accessories/subscriptions instead of
the requested hardware. Keep them generic and use an empty list when uncertain.
Temporal wording is normally soft. Pepper titles may use numeric dates or omit a month,
so do not require or necessarily include a month in every retrieval query.
For broad console hardware, generate several concrete hardware-family/platform queries;
do not classify the generic request as exact. For broad travel discovery, choose several
destinations with short high-recall queries rather than over-constrained phrases.
Set sort_mode only from the user's stated preference: cheap for explicitly cheap/low-cost,
hot for explicitly hottest/popular deal requests, otherwise fresh. Use correct Polish.
Optionally set category to one matching top-level Pepper scope: electronics, gaming,
home, garden, fashion, health, family, grocery, travel, auto, culture, sport, telecom,
or services. Leave it null when uncertain or when category scope could hide valid results.
Never browse Pepper, mention or invent deals, prices, stores, coupon codes, or deal quality.
Return only the structured search plan. Prefer fewer queries; never more than 8."""


class SearchPlanner:
    def __init__(self, api_key: str | None, *, client: Any | None = None) -> None:
        self._client = client or (genai.Client(api_key=api_key) if api_key else None)
        self.calls = 0

    async def plan(self, text: str) -> SearchPlan:
        fallback = SearchPlan(
            original_query=text, queries=[PlannedQuery(query=text)], intent="fallback"
        )
        if not self._client or os.getenv("PYTEST_CURRENT_TEST"):
            return fallback
        try:
            self.calls += 1
            response = await asyncio.to_thread(
                self._client.models.generate_content,
                model=MODEL,
                contents=text,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=GeminiPlan,
                    temperature=0.1,
                    max_output_tokens=700,
                ),
            )
            parsed = response.parsed
            if not isinstance(parsed, GeminiPlan):
                parsed = GeminiPlan.model_validate_json(response.text)
            unique: list[PlannedQuery] = []
            seen: set[str] = set()
            for item in parsed.queries[:8]:
                normalized = " ".join(item.query.split()).strip()
                key = normalized.casefold()
                if normalized and key not in seen:
                    seen.add(key)
                    anchors = " ".join(item.required_terms).casefold()
                    object_terms = [
                        value for value in item.object_terms if value.casefold() not in anchors
                    ]
                    named_entity_search = (
                        parsed.intent == "broad"
                        and len(parsed.queries) == 1
                        and item.required_terms
                        and normalized.casefold() == item.label.casefold()
                        and all(
                            value.casefold() in item.label.casefold()
                            for value in item.required_terms
                        )
                    )
                    label_text = item.label.casefold()
                    soft_terms = [
                        value
                        for value in item.soft_terms
                        if value.casefold() not in label_text and label_text not in value.casefold()
                    ]
                    unique.append(
                        PlannedQuery(
                            query=normalized,
                            label=item.label,
                            category=item.category,
                            required_terms=(
                                []
                                if parsed.intent != "exact" and len(parsed.queries) > 1
                                else item.required_terms
                            ),
                            object_terms=[] if named_entity_search else object_terms,
                            soft_terms=soft_terms,
                            excluded_terms=item.excluded_terms,
                        )
                    )
            if not unique:
                return fallback
            return SearchPlan(
                original_query=text,
                intent=parsed.intent,
                sort_mode=parsed.sort_mode,
                queries=unique,
            )
        except Exception as exc:  # provider failures must never disable search
            logger.warning(
                "Gemini planning unavailable; using direct search (%s)", type(exc).__name__
            )
            return fallback
