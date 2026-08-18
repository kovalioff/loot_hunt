from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

CategoryScope = Literal[
    "electronics",
    "gaming",
    "home",
    "garden",
    "fashion",
    "health",
    "family",
    "grocery",
    "travel",
    "auto",
    "culture",
    "sport",
    "telecom",
    "services",
]
SortMode = Literal["fresh", "cheap", "hot"]


class SemanticConstraint(BaseModel):
    """User meaning plus Polish title/URL evidence supplied by the planner."""

    name: str = Field(min_length=1, max_length=80)
    evidence_terms: list[str] = Field(default_factory=list, max_length=10)
    conflict_terms: list[str] = Field(default_factory=list, max_length=10)


class TemporalConstraint(BaseModel):
    required: bool = False
    start_date: date | None = None
    end_date: date | None = None
    month: int | None = Field(default=None, ge=1, le=12)
    year: int | None = Field(default=None, ge=2020, le=2100)
    description: str | None = Field(default=None, max_length=80)


class PlannedQuery(BaseModel):
    query: str = Field(min_length=1, max_length=120)
    label: str | None = Field(default=None, max_length=50)
    category: CategoryScope | None = None
    generated_expansions: list[str] = Field(default_factory=list, max_length=8)
    supports_core_concepts: list[str] = Field(default_factory=list, max_length=4)
    # Legacy fields keep already persisted v1 plans replayable by the watcher.
    required_terms: list[str] = Field(default_factory=list, max_length=4)
    object_terms: list[str] = Field(default_factory=list, max_length=3)
    soft_terms: list[str] = Field(default_factory=list, max_length=6)
    excluded_terms: list[str] = Field(default_factory=list, max_length=6)


class SearchPlan(BaseModel):
    original_query: str = ""
    intent: str = Field(default="search", max_length=40)
    object_class: SemanticConstraint | None = None
    sort_mode: SortMode = "fresh"
    hard_constraints: list[SemanticConstraint] = Field(default_factory=list, max_length=8)
    soft_preferences: list[SemanticConstraint] = Field(default_factory=list, max_length=8)
    core_concepts: list[SemanticConstraint] = Field(default_factory=list, max_length=6)
    exclusions: list[SemanticConstraint] = Field(default_factory=list, max_length=8)
    temporal: TemporalConstraint | None = None
    geography: SemanticConstraint | None = None
    queries: list[PlannedQuery] = Field(min_length=1, max_length=8)


class GeminiPlannedQuery(BaseModel):
    query: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=50)
    category: CategoryScope | None = None
    generated_expansions: list[str] = Field(default_factory=list, max_length=8)
    supports_core_concepts: list[str] = Field(default_factory=list, max_length=4)


class GeminiTemporalConstraint(BaseModel):
    required: bool = False
    start_date: str | None = None
    end_date: str | None = None
    month: int | None = Field(default=None, ge=1, le=12)
    year: int | None = Field(default=None, ge=2020, le=2100)
    description: str | None = Field(default=None, max_length=80)


class GeminiPlan(BaseModel):
    intent: Literal["exact", "broad", "category"]
    object_class: str | None = None
    sort_mode: SortMode
    hard_constraints: list[str] = Field(default_factory=list, max_length=8)
    soft_preferences: list[str] = Field(default_factory=list, max_length=8)
    core_concepts: list[str] = Field(default_factory=list, max_length=6)
    exclusions: list[str] = Field(default_factory=list, max_length=8)
    temporal: GeminiTemporalConstraint | None = None
    geography: str | None = None
    geography_is_user_constraint: bool = False
    queries: list[GeminiPlannedQuery] = Field(min_length=1, max_length=8)
