from __future__ import annotations

import contextlib
import json
import re

from .models import ExtractedProductInfo


def extract_schema_json_ld(html: str) -> dict[str, str | float | None]:
    result: dict[str, str | float | None] = {
        "title": None,
        "price": None,
        "currency": "PLN",
        "ean": None,
        "in_stock": True,
        "brand": None,
    }
    matches = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL | re.IGNORECASE
    )
    for block in matches:
        try:
            data = json.loads(block.strip())
            if isinstance(data, list):
                candidates = data
            elif isinstance(data, dict):
                candidates = data.get("@graph") if "@graph" in data else [data]
            else:
                continue

            for item in candidates:
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("@type") or "")
                if "Product" in item_type:
                    result["title"] = item.get("name")
                    result["ean"] = item.get("gtin13") or item.get("ean") or item.get("gtin")
                    brand = item.get("brand")
                    if isinstance(brand, dict):
                        result["brand"] = brand.get("name")
                    elif isinstance(brand, str):
                        result["brand"] = brand

                    offers = item.get("offers")
                    if isinstance(offers, list) and offers:
                        offers = offers[0]
                    if isinstance(offers, dict):
                        price_val = offers.get("price")
                        if price_val is not None:
                            with contextlib.suppress(ValueError):
                                result["price"] = float(str(price_val).replace(",", "."))
                        result["currency"] = str(offers.get("priceCurrency") or "PLN")
                        availability = str(offers.get("availability") or "")
                        if "OutOfStock" in availability:
                            result["in_stock"] = False
                    return result
        except Exception:
            continue
    return result


def extract_omnibus_price(html: str) -> float | None:
    # 1. Attribute-based (e.g. Media Expert data-omnibus-price="2199.00")
    omni_match = re.search(
        r'data-(?:omnibus-price|omni-price)="([\d\.,]+)"', html, re.IGNORECASE
    )
    if omni_match:
        with contextlib.suppress(ValueError):
            return float(omni_match.group(1).replace(" ", "").replace(",", "."))

    # 2. Text patterns according to Polish EU Directive 98/6/EC implementation
    # "Najniższa cena z 30 dni przed obniżką: 2 399,00 zł"
    text_patterns = [
        r'[Nn]ajniższa cena z 30 dni[^:]*:\s*([\d\s]+(?:[.,]\d{2})?)',
        r'30[- ]dniow[a-z]+ cena[^:]*:\s*([\d\s]+(?:[.,]\d{2})?)',
        r'cena z ostatnich 30 dni[^:]*:\s*([\d\s]+(?:[.,]\d{2})?)',
    ]
    for pattern in text_patterns:
        match = re.search(pattern, html)
        if match:
            clean_str = match.group(1).replace(" ", "").replace(",", ".")
            try:
                return float(clean_str)
            except ValueError:
                continue

    return None


def extract_datalayer(html: str) -> dict[str, str | float | None]:
    match = re.search(
        r'dataLayer\.push\((\{.*?"ecommerce".*?\})\);', html, re.DOTALL | re.IGNORECASE
    )
    if not match:
        return {}
    try:
        data = json.loads(match.group(1))
        ecommerce = data.get("ecommerce") or {}
        detail = ecommerce.get("detail") or {}
        products = detail.get("products") or []
        if products and isinstance(products[0], dict):
            p = products[0]
            price_val = p.get("price")
            return {
                "title": p.get("name"),
                "price": float(price_val) if price_val is not None else None,
                "brand": p.get("brand"),
                "category": p.get("category"),
            }
    except Exception:
        pass
    return {}


def extract_product_microdata(
    html: str, current_price: float | None = None
) -> ExtractedProductInfo:
    schema = extract_schema_json_ld(html)
    omnibus = extract_omnibus_price(html)
    gtm = extract_datalayer(html)

    title = str(schema.get("title") or gtm.get("title") or "") or None
    price = schema.get("price") or gtm.get("price") or current_price
    currency = str(schema.get("currency") or "PLN")
    ean = str(schema.get("ean") or "") or None
    brand = str(schema.get("brand") or gtm.get("brand") or "") or None
    in_stock = bool(schema.get("in_stock", True))

    fair_discount_pct = None
    is_fake = False
    if price is not None and omnibus is not None:
        if omnibus > price:
            fair_discount_pct = round((omnibus - price) / omnibus * 100, 1)
        else:
            is_fake = True
            fair_discount_pct = 0.0

    return ExtractedProductInfo(
        ean=ean,
        brand=brand,
        clean_title=title,
        current_price=float(price) if price is not None else None,
        currency=currency,
        omnibus_price=omnibus,
        fair_discount_pct=fair_discount_pct,
        is_fake_discount=is_fake,
        in_stock=in_stock,
    )
