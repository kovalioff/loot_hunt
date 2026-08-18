from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

from google import genai
from google.genai import types

from .models import (
    GeminiPlan,
    PlannedQuery,
    SearchPlan,
    SemanticConstraint,
    TemporalConstraint,
)

logger = logging.getLogger(__name__)
MODEL = "gemini-3.5-flash-lite"
SYSTEM_PROMPT = """You are the sole semantic interpreter for a Pepper.pl search executor.
Understand arbitrary Russian, Polish, English, or other natural language. Pepper titles,
categories, and useful retrieval phrases are Polish. Return only the structured plan and
never browse Pepper or invent offers, prices, merchants, or availability.

Separate USER MEANING from RETRIEVAL EXPANSIONS:
- intent exact means an explicit model/SKU/version and stays narrow; broad means a product,
  service, or concept; category means open-ended discovery.
- object_class uses `name :: Polish evidence 1 | Polish evidence 2`.
  Evidence MUST include at least one standalone Polish head-noun alternative (for example
  `konsola` for console hardware), not only a long descriptive phrase.
- hard_constraints contain only requirements explicitly mandatory in the user request. Each
  entry uses `name :: Polish evidence 1 | evidence 2 :: conflict 1 | conflict 2`; the final
  conflict section may be empty. Exact identifiers, OLED, size, storage,
  waterproof, an explicitly required colour/gender/platform, and explicit dates can be hard.
  An explicit eligibility-changing property such as waterproof/water-resistant is ALWAYS hard,
  even when grammatically expressed as an adjective. Do not hide it only in object_class or soft.
  Do not make vague adjectives such as good, interesting, or recommended hard.
- soft_preferences use `name :: Polish evidence 1 | evidence 2`. Cheap is a preference and
  sets cheap sort; only explicitly popular/hottest sets hot; otherwise fresh. Words meaning
  good or recommended alone do NOT set hot.
- core_concepts use `name :: Polish evidence 1 | evidence 2` for indispensable abstract
  meaning that retrieval should expand, such as mountain travel. Evidence is words/entities
  that support the concept. Do not demote it below incidental context such as weekend.
- exclusions use `name :: Polish evidence 1 | evidence 2` for explicit negatives and
  conservative adjacent-object exclusions. Do not exclude a valid parent object merely
  because terms overlap. Include useful singular and plural Polish evidence forms. For hardware
  discovery distinguish games, controllers, steering wheels, subscriptions, cases, and accessories.
- temporal is structured. An explicit month/date/range is required=true. Normalize month and
  year or start/end dates. NEVER invent a year absent from the user's text. A temporal concept
  belongs only in temporal, not core_concepts. Weekend without a safe concrete date is normally
  a soft preference.
- geography uses `name :: Polish evidence 1 | evidence 2`. Generated countries/destinations
  are not user hard constraints. Encode the geographic ROLE: for a requested destination,
  evidence should include Polish destination forms such as `do Pragi`/`Praga`, while reliable
  opposite-direction forms such as `z Pragi` belong after the second `::` as conflicts.
  Set geography_is_user_constraint=true ONLY when the user explicitly supplied that geography;
  never promote a generated destination (such as Zakopane) to global geography.

queries are concise, natural Polish Pepper searches, maximum 8. For broad concepts, EACH useful
concrete alternative entity/product family/destination/platform must be an actual separate
query entry, not merely a suggestion inside generated_expansions. generated_expansions lists
only the concrete expansion used by that query. supports_core_concepts contains only the exact
core-concept name before `::`, never the evidence or full encoded entry. Generated alternatives
never become global hard constraints. Every query branch inherits plan-level hard constraints.
For open-ended region discovery, generic region queries such as `wakacje Europa`, `urlop Europa`,
or paraphrases are NOT sufficient: create separate queries for concrete destinations inside the
requested geography. For hardware families, exclusions should cover Polish singular/plural words
for games, digital game editions/collections, controllers, wheels, subscriptions, and accessories.
Every query marked as supporting a core concept must materially encode that core concept itself
or a concrete entity that realizes it; never mark an unrelated brand/attribute query as support.
Prefer searchable phrases such as 'monitor 27', 'kurtka wodoodporna', 'robot sprzątający',
'wakacje Zakopane', or 'loty Mediolan wrzesień', not verbose sentences. Preserve exact model,
brand, SKU, storage, and measurement tokens. For exact intent return one query (rarely two),
never substitutes. For broad console hardware, use concrete hardware families and exclude
games/controllers/subscriptions where reliable. For broad travel, use concrete destinations.

category may be electronics, gaming, home, garden, fashion, health, family, grocery, travel,
auto, culture, sport, telecom, services, or null. Leave null if scope could hide valid results.
Never send or request Pepper results. Prefer fewer sufficient queries."""


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
                    max_output_tokens=1400,
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
                            generated_expansions=item.generated_expansions,
                            supports_core_concepts=[
                                value.split("::", 1)[0].strip()
                                for value in item.supports_core_concepts
                                if value.strip()
                            ],
                        )
                    )
            if not unique:
                return fallback
            return SearchPlan(
                original_query=text,
                intent=parsed.intent,
                object_class=_semantic(parsed.object_class),
                sort_mode=parsed.sort_mode,
                hard_constraints=_semantics(parsed.hard_constraints),
                soft_preferences=_semantics(parsed.soft_preferences),
                core_concepts=_semantics(parsed.core_concepts),
                exclusions=_semantics(parsed.exclusions),
                temporal=_temporal(parsed, text),
                geography=(
                    _geography(parsed.geography) if parsed.geography_is_user_constraint else None
                ),
                queries=unique,
            )
        except Exception as exc:  # provider failures must never disable search
            logger.warning(
                "Gemini planning unavailable; using direct search (%s)", type(exc).__name__
            )
            return fallback


def _semantic(value: str | None) -> SemanticConstraint | None:
    if not value or not value.strip():
        return None
    sections = [part.strip() for part in value.split("::", 2)]
    name = sections[0]
    evidence = [item.strip() for item in sections[1].split("|")] if len(sections) > 1 else []
    conflicts = [item.strip() for item in sections[2].split("|")] if len(sections) > 2 else []
    return SemanticConstraint(
        name=name,
        evidence_terms=[item for item in evidence if item],
        conflict_terms=[item for item in conflicts if item],
    )


def _semantics(values: list[str]) -> list[SemanticConstraint]:
    return [parsed for value in values if (parsed := _semantic(value))]


def _geography(value: str | None) -> SemanticConstraint | None:
    parsed = _semantic(value)
    if parsed and not parsed.evidence_terms:
        return parsed.model_copy(update={"evidence_terms": [parsed.name]})
    return parsed


def _temporal(parsed: GeminiPlan, original_query: str) -> TemporalConstraint | None:
    if not parsed.temporal:
        return None
    value = TemporalConstraint.model_validate(parsed.temporal.model_dump())
    explicit_years = {int(year) for year in re.findall(r"(?<!\d)(20\d{2})(?!\d)", original_query)}
    if not explicit_years:
        return value.model_copy(update={"year": None, "start_date": None, "end_date": None})
    explicit_year = next(iter(explicit_years)) if len(explicit_years) == 1 else None
    if explicit_year:
        return value.model_copy(update={"year": explicit_year})
    return value
