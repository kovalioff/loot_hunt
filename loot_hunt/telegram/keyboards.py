from __future__ import annotations

from urllib.parse import quote

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from loot_hunt.pepper.categories import Category
from loot_hunt.pepper.models import Offer
from loot_hunt.platforms import PLATFORMS


def referral_keyboard(
    user_id: int, bot_username: str = "ulovio_bot"
) -> InlineKeyboardMarkup:
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    share_text = quote(
        "Привет! Нашел крутого AI-бота для поиска скидок в Польше и Германии: "
        f"{ref_link}"
    )
    share_url = f"https://t.me/share/url?url={ref_link}&text={share_text}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📲 Отправить ссылку другу",
                    url=share_url,
                )
            ]
        ]
    )


def main_menu(admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="🔎 Найти предложения")],
        [KeyboardButton(text="📋 Мои подписки"), KeyboardButton(text="❓ Помощь")],
    ]
    if admin:
        rows.append([KeyboardButton(text="📊 Статистика")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def region_keyboard(current_code: str = "pl") -> InlineKeyboardMarkup:
    rows = []
    for code, p in PLATFORMS.items():
        checked = " ✅" if code == current_code else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{p.flag} {p.name}{checked}",
                    callback_data=f"reg:{code}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def result_keyboard(
    session_id: str,
    offers: list[Offer],
    page: int,
    total: int,
    *,
    watch: bool = True,
    category_key: str | None = None,
) -> InlineKeyboardMarkup:
    rows = []
    navigation = []
    if page:
        navigation.append(
            InlineKeyboardButton(text="⬅️", callback_data=f"pg:{session_id}:{page - 1}")
        )
    if (page + 1) * 5 < total:
        navigation.append(
            InlineKeyboardButton(text="➡️ Ещё", callback_data=f"pg:{session_id}:{page + 1}")
        )
    if navigation:
        rows.append(navigation)

    forwarding_offer = next(
        (o for o in offers if o.forwarding_url and o.country != "PL"), None
    )
    if forwarding_offer and forwarding_offer.forwarding_url:
        service = forwarding_offer.forwarding_service or "доставки"
        price_text = (
            f"~{int(forwarding_offer.forwarding_price_pln)} zł"
            if forwarding_offer.forwarding_price_pln
            else ""
        )
        flag = "🇩🇪" if forwarding_offer.country == "DE" else (
            "🇬🇧" if forwarding_offer.country == "GB" else "📦"
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🚚 {flag} Доставка в PL ({service} {price_text}) ↗",
                    url=forwarding_offer.forwarding_url,
                )
            ]
        )

    if watch:
        if category_key:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="🔔 Отслеживать эту категорию",
                        callback_data=f"wc:{session_id}:{category_key}",
                    )
                ]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="🔔 Отслеживать этот поиск", callback_data=f"ws:{session_id}"
                    )
                ]
            )
    action_row = []
    if offers:
        action_row.append(
            InlineKeyboardButton(text="📤 Поделиться", callback_data=f"share:{session_id}:{page}")
        )
    action_row.append(InlineKeyboardButton(text="🔎 Новый поиск", callback_data="new"))
    rows.append(action_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def categories_keyboard(
    categories: tuple[Category, ...], *, show_back: bool = False
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{item.emoji} {item.name}", callback_data=f"cat:{item.key}:0")]
        for item in categories
    ]
    if show_back:
        rows.append(
            [InlineKeyboardButton(text="⬅️ Назад ко всем категориям", callback_data="cat:root:0")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subscription_actions(identifier: int, active: bool) -> InlineKeyboardMarkup:
    toggle = ("⏸ Пауза", "pause") if active else ("▶️ Возобновить", "resume")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle[0], callback_data=f"sub:{toggle[1]}:{identifier}")],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"sub:delete:{identifier}")],
        ]
    )


def notification_keyboard(subscription_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔕 Отключить отслеживание",
                    callback_data=f"sub:pause:{subscription_id}",
                )
            ]
        ]
    )
