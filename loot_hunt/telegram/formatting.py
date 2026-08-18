from __future__ import annotations

import html
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from loot_hunt.pepper.models import Offer


def money(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ").replace(".00", "") + " zł"


def natural_date(value: datetime | None, timezone: str) -> str | None:
    if not value:
        return None
    zone = ZoneInfo(timezone)
    local = value.astimezone(zone)
    now = datetime.now(zone)
    if local.date() == now.date():
        return f"Сегодня, {local:%H:%M}"
    if (now.date() - local.date()).days == 1:
        return f"Вчера, {local:%H:%M}"
    months = (
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    )
    return f"{local.day} {months[local.month - 1]}"


def offer_card(offer: Offer, timezone: str, *, number: int | None = None) -> str:
    prefix = f"<b>{number}.</b> " if number is not None else ""
    lines = [f"{prefix}🔥 <b>{offer.temperature:g}°</b>", f"<b>{html.escape(offer.title)}</b>"]
    if offer.current_price is not None:
        price = f"💰 <b>{money(offer.current_price)}</b>"
        if offer.old_price is not None:
            price += f"  <s>{money(offer.old_price)}</s>"
        if offer.discount is not None:
            price += f" · −{offer.discount:g}%"
        lines.append(price)
    merchant_url = _merchant_url(offer.merchant_url)
    merchant = html.escape(offer.merchant) if offer.merchant else None
    if merchant_url:
        label = merchant or "Открыть в магазине"
        lines.append(f'🏪 <a href="{html.escape(merchant_url, quote=True)}">{label}</a>')
    elif merchant:
        lines.append(f"🏪 {merchant}")
    if date := natural_date(offer.published_at, timezone):
        lines.append(f"📅 {date}")
    if offer.coupon_code:
        lines.append(f"🎟 Код: <code>{html.escape(offer.coupon_code)}</code>")
    return "\n".join(lines)


def _merchant_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return None if parsed.hostname and parsed.hostname.endswith("pepper.pl") else value


def results_text(offers: list[Offer], total: int, page: int, timezone: str) -> str:
    start = page * 5
    cards = [
        offer_card(item, timezone, number=start + index + 1) for index, item in enumerate(offers)
    ]
    return f"Найдено {total} активных предложений\n\n" + "\n\n".join(cards)
