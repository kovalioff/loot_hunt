from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from loot_hunt.pepper.categories import Category
from loot_hunt.pepper.models import Offer


def main_menu(admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="🔎 Найти предложения")],
        [KeyboardButton(text="📋 Мои подписки"), KeyboardButton(text="❓ Помощь")],
    ]
    if admin:
        rows.append([KeyboardButton(text="📊 Статистика")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def result_keyboard(
    session_id: str, _offers: list[Offer], page: int, total: int, *, watch: bool = True
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
    if watch:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔔 Отслеживать этот поиск", callback_data=f"ws:{session_id}"
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="🔎 Новый поиск", callback_data="new")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def categories_keyboard(categories: tuple[Category, ...]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{item.emoji} {item.name}", callback_data=f"cat:{item.key}:0")]
        for item in categories
    ]
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
