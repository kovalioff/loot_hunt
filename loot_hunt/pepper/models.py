from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True)
class Offer:
    thread_id: str
    title: str
    current_price: float | None = None
    old_price: float | None = None
    discount: float | None = None
    temperature: float = 0
    merchant: str | None = None
    merchant_url: str | None = None
    coupon_code: str | None = None
    pepper_url: str | None = None
    published_at: datetime | None = None
    category: str | None = None
    is_expired: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.published_at:
            data["published_at"] = self.published_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Offer:
        values = dict(data)
        published = values.get("published_at")
        if isinstance(published, str):
            values["published_at"] = datetime.fromisoformat(published.replace("Z", "+00:00"))
        return cls(**{key: values.get(key) for key in cls.__dataclass_fields__})

    @property
    def sort_key(self) -> tuple[float, float, str]:
        timestamp = (self.published_at or datetime.min.replace(tzinfo=UTC)).timestamp()
        return (-timestamp, -self.temperature, self.thread_id)
