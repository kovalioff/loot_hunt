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
Do not unnecessarily broaden exact product searches.
For broad semantic intent, create a few concrete useful searches,
for example destinations for travel.
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
                    unique.append(PlannedQuery(query=normalized, label=item.label))
            if not unique:
                return fallback
            return SearchPlan(original_query=text, intent=parsed.intent, queries=unique)
        except Exception as exc:  # provider failures must never disable search
            logger.warning(
                "Gemini planning unavailable; using direct search (%s)", type(exc).__name__
            )
            return fallback
