from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from loot_hunt.pepper.categories import PARENTS
from loot_hunt.pepper.models import Offer

from .models import PlannedQuery, SearchPlan
from .planner import SearchPlanner
from .relevance import RelevanceResult, evaluate_offer, normalize

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
CATEGORY_PATHS = {item.key: item.path for item in PARENTS}
TARGET_CANDIDATES = 15
CATEGORY_FALLBACK_THRESHOLD = 5
MAX_SEARCH_PAGES = 2
MAX_PEPPER_REQUESTS = 12
MAX_RAW_CANDIDATES = 120


@dataclass(slots=True)
class RequestDebug:
    source: str
    query: str
    page: int
    raw: int
    accepted: int
    rejected: int
    error: str | None = None


@dataclass(slots=True)
class OfferDebug:
    thread_id: str
    title: str
    source_query: str
    source_kind: str
    page: int
    accepted: bool
    score: float
    reasons: tuple[str, ...]
    rejection: str | None
    hard_status: str
    temporal_status: str
    core_evidence: tuple[str, ...]


@dataclass(slots=True)
class SearchDebug:
    sort_mode: str
    requests: list[RequestDebug] = field(default_factory=list)
    offers: dict[str, OfferDebug] = field(default_factory=dict)
    raw_candidates: int = 0
    accepted_candidates: int = 0

    def to_dict(self) -> dict:
        return {
            "sort_mode": self.sort_mode,
            "requests": [asdict(item) for item in self.requests],
            "raw_candidates": self.raw_candidates,
            "accepted_candidates": self.accepted_candidates,
            "offers": [asdict(item) for item in self.offers.values()],
        }


@dataclass(slots=True)
class SearchResult:
    plan: SearchPlan
    offers: list[Offer]
    debug: SearchDebug | None = None


@dataclass(slots=True)
class _Candidate:
    offer: Offer
    evaluation: RelevanceResult
    source_query: str
    source_kind: str
    page: int


class SearchUnavailable(RuntimeError):
    pass


class SearchService:
    def __init__(self, planner: SearchPlanner, pepper, *, cap: int = 25) -> None:
        self.planner = planner
        self.pepper = pepper
        self.cap = min(30, max(5, cap))

    async def search(self, text: str) -> SearchResult:
        plan = await self.planner.plan(text)
        offers, debug = await self._execute(plan)
        return SearchResult(plan, offers, debug)

    async def execute_plan(self, plan: SearchPlan) -> list[Offer]:
        offers, _ = await self._execute(plan)
        return offers

    async def _execute(self, plan: SearchPlan) -> tuple[list[Offer], SearchDebug]:
        debug = SearchDebug(plan.sort_mode)
        candidates: dict[str, _Candidate] = {}
        raw_ids: set[str] = set()
        requests = 0

        retrievals = self._retrieval_queries(plan)
        first_pages = await asyncio.gather(
            *(self._search_query(item, 1) for item, _ in retrievals), return_exceptions=True
        )
        requests += len(first_pages)
        if first_pages and all(isinstance(batch, BaseException) for batch in first_pages):
            raise SearchUnavailable("All Pepper search queries failed")

        first_stats: list[tuple[int, int]] = []
        for (planned, source), batch in zip(retrievals, first_pages, strict=True):
            accepted, raw = self._consume(
                plan, planned, batch, candidates, raw_ids, debug, source=source, page=1
            )
            first_stats.append((accepted, raw))

        scope = self._fallback_scope(plan)
        page_request_limit = MAX_PEPPER_REQUESTS - (1 if scope else 0)
        if len(candidates) < TARGET_CANDIDATES and len(raw_ids) < MAX_RAW_CANDIDATES:
            order = sorted(
                range(len(retrievals)),
                key=lambda index: (first_stats[index][0] > 0, first_stats[index][1]),
                reverse=True,
            )
            for index in order:
                if (
                    requests >= page_request_limit
                    or len(candidates) >= TARGET_CANDIDATES
                    or len(raw_ids) >= MAX_RAW_CANDIDATES
                ):
                    break
                if first_stats[index][1] == 0 or MAX_SEARCH_PAGES < 2:
                    continue
                planned, source = retrievals[index]
                batch = await self._search_query(planned, 2)
                requests += 1
                self._consume(
                    plan, planned, batch, candidates, raw_ids, debug, source=source, page=2
                )

        if (
            scope
            and len(candidates) < CATEGORY_FALLBACK_THRESHOLD
            and requests < MAX_PEPPER_REQUESTS
            and len(raw_ids) < MAX_RAW_CANDIDATES
        ):
            path = CATEGORY_PATHS[scope]
            try:
                batch = await self.pepper.category(path, page=1)
            except Exception as exc:
                debug.requests.append(
                    RequestDebug("category", path, 1, 0, 0, 0, type(exc).__name__)
                )
            else:
                self._consume_category(plan, scope, batch, candidates, raw_ids, debug)

        debug.raw_candidates = len(raw_ids)
        debug.accepted_candidates = len(candidates)
        ranked = self._rank(candidates.values(), plan)
        selected = ranked[: min(30, self.cap + 5)]
        offers = [item.offer for item in selected]
        enriched = await asyncio.gather(
            *(self.pepper.enrich(item) for item in offers), return_exceptions=True
        )
        final_candidates: list[_Candidate] = []
        for original, value in zip(selected, enriched, strict=True):
            enriched_offer = original.offer if isinstance(value, BaseException) else value
            selected_plan, evaluation = self._final_evaluation(
                enriched_offer, plan, original.source_kind, original.source_query
            )
            self._record_debug(
                enriched_offer,
                evaluation,
                debug,
                original.source_query,
                original.source_kind,
                original.page,
                replace=True,
            )
            if evaluation.accepted:
                final_candidates.append(
                    _Candidate(
                        enriched_offer,
                        evaluation,
                        original.source_query or selected_plan.label or selected_plan.query,
                        original.source_kind,
                        original.page,
                    )
                )
        final = self._rank(final_candidates, plan)[: self.cap]
        return [item.offer for item in final if not item.offer.is_expired], debug

    def _consume(
        self,
        plan: SearchPlan,
        planned: PlannedQuery,
        batch,
        candidates: dict[str, _Candidate],
        raw_ids: set[str],
        debug: SearchDebug,
        *,
        source: str,
        page: int,
    ) -> tuple[int, int]:
        if isinstance(batch, BaseException):
            debug.requests.append(
                RequestDebug(source, planned.query, page, 0, 0, 0, type(batch).__name__)
            )
            return 0, 0
        accepted = 0
        considered = 0
        for offer in batch:
            if offer.thread_id not in raw_ids and len(raw_ids) >= MAX_RAW_CANDIDATES:
                continue
            raw_ids.add(offer.thread_id)
            considered += 1
            selected_plan = planned
            if source == "search-object":
                compatible = [item for item in plan.queries if item.category == planned.category]
                selected_plan, evaluation = max(
                    (
                        (item, evaluate_offer(offer, item, plan, source_kind=source))
                        for item in compatible
                    ),
                    key=lambda pair: pair[1].score,
                )
            else:
                evaluation = evaluate_offer(offer, planned, plan, source_kind=source)
            if (
                evaluation.accepted
                and plan.intent == "broad"
                and selected_plan.object_terms
                and selected_plan.excluded_terms
                and not any(reason.startswith("object ") for reason in evaluation.reasons)
                and source == "search"
            ):
                evaluation = RelevanceResult(
                    False,
                    evaluation.score,
                    evaluation.reasons,
                    "object class unconfirmed by title or object-scoped retrieval",
                )
            if (
                evaluation.accepted
                and plan.intent == "category"
                and source == "search-object"
                and not any(reason.startswith(("label ", "soft ")) for reason in evaluation.reasons)
            ):
                evaluation = RelevanceResult(
                    False,
                    evaluation.score,
                    evaluation.reasons,
                    "generic category candidate lacks planned concept",
                )
            self._record(
                offer,
                evaluation,
                candidates,
                debug,
                selected_plan.label or selected_plan.query,
                source,
                page,
            )
            accepted += evaluation.accepted
        debug.requests.append(
            RequestDebug(source, planned.query, page, considered, accepted, considered - accepted)
        )
        return accepted, considered

    def _consume_category(
        self,
        plan: SearchPlan,
        scope: str,
        batch: list[Offer],
        candidates: dict[str, _Candidate],
        raw_ids: set[str],
        debug: SearchDebug,
    ) -> None:
        accepted = 0
        considered = 0
        planned_queries = [item for item in plan.queries if item.category == scope]
        for offer in batch:
            if offer.thread_id not in raw_ids and len(raw_ids) >= MAX_RAW_CANDIDATES:
                continue
            raw_ids.add(offer.thread_id)
            considered += 1
            evaluations = [
                evaluate_offer(offer, item, plan, source_kind="category")
                for item in planned_queries
            ]
            position, evaluation = max(enumerate(evaluations), key=lambda item: item[1].score)
            if evaluation.accepted and (
                (
                    plan.intent == "category"
                    and not any(
                        reason.startswith(("label ", "soft ")) for reason in evaluation.reasons
                    )
                )
                or (plan.intent != "category" and evaluation.reasons == ("category",))
            ):
                evaluation = RelevanceResult(
                    False,
                    evaluation.score,
                    evaluation.reasons,
                    "category fallback lacks planned concept",
                )
            selected = planned_queries[position]
            self._record(
                offer,
                evaluation,
                candidates,
                debug,
                selected.label or selected.query,
                "category",
                1,
            )
            accepted += evaluation.accepted
        debug.requests.append(
            RequestDebug(
                "category",
                CATEGORY_PATHS[scope],
                1,
                considered,
                accepted,
                considered - accepted,
            )
        )

    @staticmethod
    def _record(
        offer: Offer,
        evaluation: RelevanceResult,
        candidates: dict[str, _Candidate],
        debug: SearchDebug,
        source_query: str,
        source_kind: str,
        page: int,
    ) -> None:
        SearchService._record_debug(offer, evaluation, debug, source_query, source_kind, page)
        current = candidates.get(offer.thread_id)
        if evaluation.accepted and (current is None or evaluation.score > current.evaluation.score):
            candidates[offer.thread_id] = _Candidate(
                offer, evaluation, source_query, source_kind, page
            )

    @staticmethod
    def _record_debug(
        offer: Offer,
        evaluation: RelevanceResult,
        debug: SearchDebug,
        source_query: str,
        source_kind: str,
        page: int,
        *,
        replace: bool = False,
    ) -> None:
        previous = debug.offers.get(offer.thread_id)
        if replace or previous is None or evaluation.score >= previous.score:
            debug.offers[offer.thread_id] = OfferDebug(
                offer.thread_id,
                offer.title,
                source_query,
                source_kind,
                page,
                evaluation.accepted,
                evaluation.score,
                evaluation.reasons,
                evaluation.rejection,
                evaluation.hard_status,
                evaluation.temporal_status,
                evaluation.core_evidence,
            )

    @staticmethod
    def _final_evaluation(
        offer: Offer, plan: SearchPlan, source_kind: str, source_query: str
    ) -> tuple[PlannedQuery, RelevanceResult]:
        object_values = [normalize(value) for item in plan.queries for value in item.object_terms]

        def conflicts_with_valid_object(term: str) -> bool:
            value = normalize(term)
            stem = value[:6]
            return any(
                value in valid or valid in value or (len(stem) == 6 and valid.startswith(stem))
                for valid in object_values
            )

        exclusions = list(
            dict.fromkeys(
                term
                for item in plan.queries
                for term in item.excluded_terms
                if not conflicts_with_valid_object(term)
            )
        )
        evaluations = []
        for item in plan.queries:
            merged = item.model_copy(update={"excluded_terms": exclusions})
            evaluation = evaluate_offer(
                offer,
                merged,
                plan,
                source_kind=(
                    source_kind if (item.label or item.query) == source_query else "cross-query"
                ),
            )
            if (
                evaluation.accepted
                and plan.intent == "broad"
                and merged.object_terms
                and merged.excluded_terms
                and not any(reason.startswith("object ") for reason in evaluation.reasons)
                and source_kind == "search"
            ):
                evaluation = RelevanceResult(
                    False,
                    evaluation.score,
                    evaluation.reasons,
                    "object class unconfirmed after enrichment",
                )
            evaluations.append((item, evaluation))
        return max(evaluations, key=lambda pair: (pair[1].accepted, pair[1].score))

    async def _search_query(self, planned: PlannedQuery, page: int = 1) -> list[Offer]:
        group_id = CATEGORY_GROUP_IDS.get(planned.category or "")
        return await self.pepper.search(planned.query, page=page, group_id=group_id)

    @staticmethod
    def _retrieval_queries(plan: SearchPlan) -> list[tuple[PlannedQuery, str]]:
        retrievals = [(item, "search") for item in plan.queries]
        model_terms = [
            term
            for term in normalize(plan.original_query).split()
            if any(char.isalpha() for char in term) and any(char.isdigit() for char in term)
        ]
        if model_terms:
            return retrievals
        seen = {item.query.casefold() for item in plan.queries}
        global_hard = [
            item.evidence_terms[0] for item in plan.hard_constraints if item.evidence_terms
        ]
        global_objects = plan.object_class.evidence_terms if plan.object_class else []
        for item in plan.queries:
            hard = item.required_terms or global_hard
            objects = item.object_terms or global_objects
            if not hard or not objects or len(retrievals) >= 8:
                continue
            relaxed = " ".join([objects[0], *hard])
            if relaxed.casefold() in seen:
                continue
            seen.add(relaxed.casefold())
            retrievals.append((item.model_copy(update={"query": relaxed}), "search-relaxed"))
        for item in plan.queries:
            objects = item.object_terms or global_objects
            if not objects or len(retrievals) >= 8:
                continue
            object_query = objects[0]
            if object_query.casefold() in seen:
                continue
            seen.add(object_query.casefold())
            retrievals.append((item.model_copy(update={"query": object_query}), "search-object"))
        return retrievals

    @staticmethod
    def _fallback_scope(plan: SearchPlan) -> str | None:
        scopes = {item.category for item in plan.queries if item.category}
        if plan.intent not in {"broad", "category", "category-like", "travel"} or len(scopes) != 1:
            return None
        scope = scopes.pop()
        return scope if scope in CATEGORY_PATHS else None

    @staticmethod
    def _sort_key(item: _Candidate, mode: str) -> tuple:
        offer = item.offer
        timestamp = (offer.published_at or datetime.min.replace(tzinfo=UTC)).timestamp()
        hard_relevance = -int(
            "exact model" in item.evaluation.reasons
            or any(reason.startswith("hard terms") for reason in item.evaluation.reasons)
        )
        if mode == "cheap":
            free = "za darmo" in normalize(offer.title) or "bezplat" in normalize(offer.title)
            missing = offer.current_price is None and not free
            price = offer.current_price if offer.current_price is not None else (0 if free else 0)
            return (
                hard_relevance,
                -int("temporal" in item.evaluation.reasons),
                missing,
                price,
                -item.evaluation.score,
                -offer.temperature,
                -timestamp,
                offer.thread_id,
            )
        if mode == "hot":
            return (
                hard_relevance,
                -int("temporal" in item.evaluation.reasons),
                -item.evaluation.score,
                -offer.temperature,
                -timestamp,
                offer.thread_id,
            )
        return (
            hard_relevance,
            -int("temporal" in item.evaluation.reasons),
            -item.evaluation.score,
            -timestamp,
            -offer.temperature,
            offer.thread_id,
        )

    def _rank(self, candidates, plan: SearchPlan) -> list[_Candidate]:
        ranked = sorted(candidates, key=lambda item: self._sort_key(item, plan.sort_mode))
        if plan.intent != "broad" or plan.sort_mode == "cheap" or len(plan.queries) < 2:
            return ranked
        groups: dict[str, list[_Candidate]] = {
            item.label or item.query: [] for item in plan.queries
        }
        remainder: list[_Candidate] = []
        for item in ranked:
            group = groups.get(item.source_query)
            (group if group is not None else remainder).append(item)
        diverse: list[_Candidate] = []
        active = [values for values in groups.values() if values]
        while active:
            heads = sorted(
                ((values[0], values) for values in active),
                key=lambda pair: self._sort_key(pair[0], plan.sort_mode),
            )
            for head, values in heads:
                diverse.append(head)
                values.pop(0)
            active = [values for values in active if values]
        return diverse + remainder

    @staticmethod
    def page(offers: list[Offer], page: int, size: int = 5) -> list[Offer]:
        start = max(0, page) * size
        return offers[start : start + size]
