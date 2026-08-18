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
SYSTEM_PROMPT = """You plan searches for Pepper.pl, a Polish deal community.
Understand Russian and other languages and produce natural Polish search phrases.
Preserve exact model, SKU, brand, and code strings.
Classify the request as exact/narrow or broad before planning.
For an exact model, SKU, platform, or named product, return one query (very rarely two)
and do not add alternatives that change the requested product.
For a broad request, decompose it into diverse CONCRETE entities that people put in
Pepper titles: specific destinations, product families, platforms, brands, or use cases.
Do not return several abstract paraphrases of the same broad request. For example,
broad European travel should become concrete destination searches, not generic phrases
such as 'wakacje w Europie', 'city break Europa', or 'all inclusive Europa'.
Each label must be a short human-readable concrete entity. For every query,
required_terms MUST contain 1-4 minimal Polish title anchors that a matching offer must
contain. object_terms MUST separately contain the Polish noun for the requested object
type when it is needed to distinguish the wanted item from related content. For example,
a request for game-console hardware needs the hardware object noun, not only platform
names that also occur in games or controllers. A robot vacuum needs its appliance-type
terms, not only a brand. Use an empty object_terms only when the exact model token or a
precise native category scope already makes the object unambiguous. Use correct Polish.
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
                    unique.append(
                        PlannedQuery(
                            query=normalized,
                            label=item.label,
                            category=item.category,
                            required_terms=item.required_terms,
                            object_terms=item.object_terms,
                        )
                    )
            if not unique:
                return fallback
            return SearchPlan(original_query=text, intent=parsed.intent, queries=unique)
        except Exception as exc:  # provider failures must never disable search
            logger.warning(
                "Gemini planning unavailable; using direct search (%s)", type(exc).__name__
            )
            return fallback
