from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ParsedEntity:
    raw_title: str
    price: float | None
    head_class: str  # e.g. "laptop", "gpu", "accessory", "console", "smartphone", "other"
    is_accessory: bool
    accessory_type: str | None = None  # e.g. "kabel", "etui", "podstawka", "gra"
    accessory_target: str | None = None  # target device e.g. "laptop", "ps5", "iphone"
    specs: dict[str, str] = field(default_factory=dict)
    confidence: float = 1.0
    explanation: str = ""


@dataclass(slots=True)
class ExtractedProductInfo:
    ean: str | None = None
    brand: str | None = None
    model: str | None = None
    clean_title: str | None = None
    current_price: float | None = None
    currency: str = "PLN"
    omnibus_price: float | None = None
    fair_discount_pct: float | None = None
    is_fake_discount: bool = False
    in_stock: bool = True
    specs: dict[str, str] = field(default_factory=dict)
