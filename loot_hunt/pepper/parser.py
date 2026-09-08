from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

from .models import Offer

BASE_URL = "https://www.pepper.pl"
VUE_RE = re.compile(
    r"""data-vue3='(\{"name":"ThreadMainListItemNormalizer".*?)'|"""
    r'data-vue3=&apos;(\{"name":"ThreadMainListItemNormalizer".*?)&apos;',
    re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", html.unescape(str(value or "")))).strip()


def number(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, dict):
        return next(
            (
                result
                for key in ("amount", "value", "price")
                if (result := number(value.get(key))) is not None
            ),
            None,
        )
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", raw)
    return float(match.group()) if match else None


def moment(value: Any) -> datetime | None:
    if value in (None, "", 0):
        return None
    if isinstance(value, (int, float)):
        stamp = float(value) / (1000 if float(value) > 1e12 else 1)
        return datetime.fromtimestamp(stamp, tz=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def initial_state(page: str) -> dict[str, Any]:
    marker = "window.__INITIAL_STATE__"
    position = page.find(marker)
    if position < 0:
        return {}
    start = page.find("{", position)
    try:
        result, _ = json.JSONDecoder().raw_decode(page[start:])
    except (ValueError, json.JSONDecodeError):
        return {}
    return result if isinstance(result, dict) else {}


def listing_threads(page: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in VUE_RE.finditer(page):
        try:
            payload = json.loads(html.unescape(match.group(1) or match.group(2)))
        except json.JSONDecodeError:
            continue
        thread = (payload.get("props") or {}).get("thread")
        identifier = str((thread or {}).get("threadId") or "")
        if isinstance(thread, dict) and identifier and identifier not in seen:
            seen.add(identifier)
            found.append(thread)
    if found:
        return found
    state = initial_state(page)
    return list(_find_thread_lists(state))


def _find_thread_lists(node: Any) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict):
        if node.get("threadId") and node.get("title"):
            yield node
            return
        for child in node.values():
            yield from _find_thread_lists(child)
    elif isinstance(node, list):
        for child in node:
            yield from _find_thread_lists(child)


def _pick(raw: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = raw.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _text_from(value: Any) -> str | None:
    if isinstance(value, dict):
        value = _pick(
            value,
            "name",
            "title",
            "code",
            "value",
            "merchantName",
            "threadGroupName",
        )
    result = clean(value)
    return result or None


def _url_from(value: Any) -> str | None:
    if isinstance(value, dict):
        value = _pick(value, "url", "link", "targetUrl", "target")
    if not isinstance(value, str):
        return None
    url = urljoin(BASE_URL, html.unescape(value))
    parsed = urlparse(url)
    return url if parsed.scheme in {"http", "https"} and parsed.netloc else None


def normalize_offer(raw: dict[str, Any], pepper_url: str | None = None) -> Offer | None:
    thread_id = str(_pick(raw, "threadId", "thread_id", "id") or "")
    title = clean(_pick(raw, "title", "name"))
    if not thread_id or not title:
        return None
    current = number(_pick(raw, "price", "currentPrice", "dealPrice"))
    if current is not None and current <= 0:
        current = None
    old = number(_pick(raw, "nextBestPrice", "oldPrice", "originalPrice", "referencePrice"))
    if old is not None and (old <= 0 or current is None or old <= current):
        old = None
    explicit_discount = number(_pick(raw, "discount", "discountPercentage", "percentage"))
    if explicit_discount is not None and not 0 < explicit_discount <= 95:
        explicit_discount = None
    computed = round((old - current) / old * 100) if old and current and old > current else None
    discount = explicit_discount or computed
    merchant = _text_from(_pick(raw, "merchant", "merchantName", "shop", "retailer"))
    merchant_url = _url_from(
        _pick(
            raw,
            "merchantUrl",
            "dealUrl",
            "outboundUrl",
            "targetUrl",
            "link",
            "linkCloakedItemMainButton",
        )
    )
    if (
        merchant_url
        and urlparse(merchant_url).netloc.endswith("pepper.pl")
        and "/visit/" not in urlparse(merchant_url).path
    ):
        merchant_url = None
    coupon = _text_from(_pick(raw, "voucherCode", "couponCode", "promoCode"))
    category = _text_from(_pick(raw, "group", "category", "mainGroup"))
    explicit_url = _url_from(_pick(raw, "url", "shareableLink"))
    return Offer(
        thread_id=thread_id,
        title=title,
        current_price=current,
        old_price=old,
        discount=discount,
        temperature=number(raw.get("temperature")) or 0,
        merchant=merchant,
        merchant_url=merchant_url,
        coupon_code=coupon,
        pepper_url=pepper_url or explicit_url,
        published_at=moment(_pick(raw, "publishedAt", "published_at", "createdAt")),
        category=category,
        is_expired=bool(_pick(raw, "isExpired", "expired", "is_expired")),
    )


def detail_from_page(page: str, pepper_url: str) -> Offer | None:
    state = initial_state(page)
    raw = state.get("threadDetail") or state.get("thread")
    return normalize_offer(raw, pepper_url) if isinstance(raw, dict) else None
