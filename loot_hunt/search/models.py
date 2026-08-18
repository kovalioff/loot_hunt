from __future__ import annotations

from pydantic import BaseModel, Field


class PlannedQuery(BaseModel):
    query: str = Field(min_length=1, max_length=120)
    label: str | None = Field(default=None, max_length=50)


class SearchPlan(BaseModel):
    original_query: str = ""
    intent: str = Field(default="search", max_length=40)
    queries: list[PlannedQuery] = Field(min_length=1, max_length=8)


class GeminiPlan(BaseModel):
    intent: str = Field(default="search", max_length=40)
    queries: list[PlannedQuery] = Field(min_length=1, max_length=8)
