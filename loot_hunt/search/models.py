from __future__ import annotations

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


class PlannedQuery(BaseModel):
    query: str = Field(min_length=1, max_length=120)
    label: str | None = Field(default=None, max_length=50)
    category: CategoryScope | None = None
    required_terms: list[str] = Field(default_factory=list, max_length=4)
    object_terms: list[str] = Field(default_factory=list, max_length=3)


class SearchPlan(BaseModel):
    original_query: str = ""
    intent: str = Field(default="search", max_length=40)
    queries: list[PlannedQuery] = Field(min_length=1, max_length=8)


class GeminiPlannedQuery(BaseModel):
    query: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=50)
    category: CategoryScope | None = None
    required_terms: list[str] = Field(min_length=1, max_length=4)
    object_terms: list[str] = Field(max_length=3)


class GeminiPlan(BaseModel):
    intent: str = Field(default="search", max_length=40)
    queries: list[GeminiPlannedQuery] = Field(min_length=1, max_length=8)
