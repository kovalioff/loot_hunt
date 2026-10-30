from __future__ import annotations

import html
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from loot_hunt.affiliate import AffiliateTransformer
from loot_hunt.pepper.models import Offer
from loot_hunt.platforms import get_platform

TELEGRAM_TEXT_LIMIT = 4096
NOTIFICATION_CHUNK_LIMIT = 3800


def money(value: float, currency: str = "zł") -> str:
    formatted = f"{value:,.2f}".replace(",", " ").replace(".00", "")
    return f"{formatted} {currency}"


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
    platform = get_platform(offer.platform_code)
    flag_str = f" · {platform.flag} {platform.name}" if offer.country != "PL" else ""
    lines = [
        f"{prefix}🔥 <b>{offer.temperature:g}°</b>{flag_str}",
        f"<b>{html.escape(offer.title)}</b>",
    ]
    if offer.current_price is not None:
        curr = html.escape(offer.currency or "zł")
        price = f"💰 <b>{money(offer.current_price, curr)}</b>"
        if offer.country != "PL" and offer.price_pln is not None:
            price += f" <i>(~{money(offer.price_pln, 'zł')})</i>"
        if offer.old_price is not None:
            price += f"  <s>{money(offer.old_price, curr)}</s>"
        if offer.discount is not None:
            price += f" · −{offer.discount:g}%"
        lines.append(price)

    curr = html.escape(offer.currency or "zł")
    if offer.omnibus_price is not None:
        if offer.fair_discount_pct is not None and offer.fair_discount_pct > 0:
            omni_str = money(offer.omnibus_price, curr)
            pct = offer.fair_discount_pct
            lines.append(
                f"📉 <b>Честная скидка:</b> −{pct:g}% от 30-дн. цены ({omni_str})"
            )
        elif offer.is_fake_discount:
            lines.append(
                f"⚠️ <b>30-дн. минимум:</b> {money(offer.omnibus_price, curr)} (скидка номинальная)"
            )

    if offer.specs:
        spec_parts = [html.escape(str(value)) for value in offer.specs.values() if value]
        if spec_parts:
            lines.append(f"⚙️ <b>ТТХ:</b> {' • '.join(spec_parts[:4])}")

    if offer.country != "PL" and offer.forwarding_service:
        fwd_price = (
            f"~{money(offer.forwarding_price_pln, 'zł')}"
            if offer.forwarding_price_pln
            else ""
        )
        if offer.forwarding_url:
            fwd_link = (
                f'<a href="{html.escape(offer.forwarding_url, quote=True)}">'
                f"{html.escape(offer.forwarding_service)}</a>"
            )
        else:
            fwd_link = html.escape(offer.forwarding_service)
        lines.append(f"🚚 <b>Доставка в Польшу</b>: {fwd_price} через {fwd_link}")

    merchant_url = _merchant_url(offer.merchant_url, platform_code=offer.platform_code)
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


def _merchant_url(value: str | None, platform_code: str = "pl") -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    hostname = (parsed.hostname or "").lower()
    if any(hostname.endswith(d) for d in ("pepper.pl", "mydealz.de", "hotukdeals.com")):
        return None
    return AffiliateTransformer().transform(value, platform_code=platform_code)


def results_text(offers: list[Offer], total: int, page: int, timezone: str) -> str:
    if total == 0:
        return (
            "Активных предложений сейчас нет.\n\n"
            "🔔 Можно включить отслеживание — я сообщу, когда появится "
            "подходящее предложение."
        )
    start = page * 5
    cards = [
        offer_card(item, timezone, number=start + index + 1)
        for index, item in enumerate(offers)
    ]
    return f"Найдено {total} активных предложений\n\n" + "\n\n".join(cards)


def notification_chunks(
    offers: list[Offer], timezone: str, *, limit: int = NOTIFICATION_CHUNK_LIMIT
) -> list[str]:
    """Group offer cards into Telegram-sized messages instead of one message per offer."""
    chunks: list[str] = []
    current = ""
    for offer in offers:
        card = offer_card(offer, timezone)
        if len(card) > limit:
            card = card[:limit]
        candidate = f"{current}\n\n{card}" if current else card
        if current and len(candidate) > limit:
            chunks.append(current)
            current = card
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks
