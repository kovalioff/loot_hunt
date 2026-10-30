from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
    currency: str = "zł"
    country: str = "PL"
    platform_code: str = "pl"
    price_pln: float | None = None
    forwarding_service: str | None = None
    forwarding_price_pln: float | None = None
    forwarding_url: str | None = None
    ean: str | None = None
    omnibus_price: float | None = None
    fair_discount_pct: float | None = None
    is_fake_discount: bool = False
    specs: dict[str, str] = field(default_factory=dict)

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
        kwargs = {}
        for key in cls.__dataclass_fields__:
            if key in values:
                # Use default if value is None and dataclass field has non-None default
                if values[key] is None and key in {"currency", "country", "platform_code"}:
                    continue
                kwargs[key] = values[key]
        return cls(**kwargs)

    @property
    def sort_key(self) -> tuple[float, float, str]:
        timestamp = (self.published_at or datetime.min.replace(tzinfo=UTC)).timestamp()
        return (-timestamp, -self.temperature, self.thread_id)

    @property
    def display_price(self) -> str:
        if self.current_price is None:
            return ""
        formatted = f"{self.current_price:,.2f}".replace(",", " ").replace(".00", "")
        return f"{formatted} {self.currency}"

    @property
    def display_price_with_pln(self) -> str:
        if self.current_price is None:
            return ""
        base = self.display_price
        if self.country == "PL" or not self.price_pln:
            return base
        pln_str = f"{self.price_pln:,.2f}".replace(",", " ").replace(".00", "") + " zł"
        return f"{base} (~{pln_str})"
