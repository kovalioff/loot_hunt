from __future__ import annotations

import asyncio
from dataclasses import dataclass

from loot_hunt.pepper.models import Offer

from .models import PlannedQuery, SearchPlan
from .planner import SearchPlanner
from .relevance import is_relevant

CATEGORY_GROUP_IDS = {
    "electronics": "131",
    "gaming": "19",
    "home": "133",
    "garden": "10",
    "fashion": "5",
    "health": "20",
    "family": "17",
    "grocery": "16",
    "travel": "14",
    "auto": "132",
    "culture": "4",
    "sport": "103",
    "telecom": "135",
    "services": "136",
}


@dataclass(slots=True)
class SearchResult:
    plan: SearchPlan
    offers: list[Offer]


class SearchUnavailable(RuntimeError):
    pass


class SearchService:
    def __init__(self, planner: SearchPlanner, pepper, *, cap: int = 25) -> None:
        self.planner = planner
        self.pepper = pepper
        self.cap = min(30, max(5, cap))

    async def search(self, text: str) -> SearchResult:
        plan = await self.planner.plan(text)  # exactly one planning call per user search
        return SearchResult(plan, await self.execute_plan(plan))

    async def execute_plan(self, plan: SearchPlan) -> list[Offer]:
        batches = await asyncio.gather(
            *(self._search_query(item) for item in plan.queries), return_exceptions=True
        )
        if batches and all(isinstance(batch, BaseException) for batch in batches):
            raise SearchUnavailable("All Pepper search queries failed")
        unique: dict[str, Offer] = {}
        for planned, batch in zip(plan.queries, batches, strict=True):
            if isinstance(batch, BaseException):
                continue
            for offer in batch:
                if (
                    not offer.is_expired
                    and is_relevant(offer, planned, plan)
                    and offer.thread_id not in unique
                ):
                    unique[offer.thread_id] = offer
        offers = sorted(unique.values(), key=lambda item: item.sort_key)[: self.cap]
        enriched = await asyncio.gather(
            *(self.pepper.enrich(item) for item in offers), return_exceptions=True
        )
        final = [
            original if isinstance(value, BaseException) else value
            for original, value in zip(offers, enriched, strict=True)
        ]
        return [item for item in final if not item.is_expired]

    async def _search_query(self, planned: PlannedQuery) -> list[Offer]:
        group_id = CATEGORY_GROUP_IDS.get(planned.category or "")
        return await self.pepper.search(planned.query, group_id=group_id)

    @staticmethod
    def page(offers: list[Offer], page: int, size: int = 5) -> list[Offer]:
        start = max(0, page) * size
        return offers[start : start + size]
