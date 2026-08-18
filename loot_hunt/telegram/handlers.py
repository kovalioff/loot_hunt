from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message

from loot_hunt.pepper.categories import PARENTS, flatten
from loot_hunt.search.models import PlannedQuery, SearchPlan

from .formatting import results_text
from .keyboards import categories_keyboard, main_menu, result_keyboard, subscription_actions

logger = logging.getLogger(__name__)

START_TEXT = """<b>Loot Hunt</b> ищет активные предложения на Pepper.pl.

Откройте «🔎 Найти предложения»: там можно написать запрос обычными словами
или выбрать категорию из актуального каталога Pepper.

На странице результатов нажмите «🔔 Отслеживать этот поиск».
Сохранёнными поисками можно управлять через «📋 Мои подписки»."""


class TelegramHandlers:
    def __init__(self, settings, database, search, pepper) -> None:
        self.settings = settings
        self.database = database
        self.search = search
        self.pepper = pepper
        self.catalog = PARENTS
        self.by_key = flatten(self.catalog)
        self.router = Router()
        self._register()

    async def refresh_catalog(self) -> None:
        try:
            self.catalog = await self.pepper.category_catalog()
            self.by_key = flatten(self.catalog)
        except Exception:
            logger.warning("Live category refresh failed; using verified parent snapshot")

    def _register(self) -> None:
        router = self.router
        router.message.register(self.start, CommandStart())
        router.message.register(self.ask_search, F.text == "🔎 Найти предложения")
        router.message.register(self.subscriptions, F.text == "📋 Мои подписки")
        router.message.register(self.help, F.text == "❓ Помощь")
        router.message.register(self.stats, F.text == "📊 Статистика")
        router.callback_query.register(self.paginate, F.data.startswith("pg:"))
        router.callback_query.register(self.watch_search, F.data.startswith("ws:"))
        router.callback_query.register(self.category, F.data.startswith("cat:"))
        router.callback_query.register(self.watch_category, F.data.startswith("wc:"))
        router.callback_query.register(self.subscription_action, F.data.startswith("sub:"))
        router.callback_query.register(self.new_search, F.data == "new")
        router.message.register(self.search_text, F.text)

    async def start(self, message: Message) -> None:
        admin = bool(message.from_user and message.from_user.id in self.settings.admin_ids)
        await message.answer(START_TEXT, reply_markup=main_menu(admin))

    async def ask_search(self, message: Message) -> None:
        await message.answer(
            "Что хотите найти?\n\n"
            "Можно написать запрос обычными словами:\n\n"
            "«дешёвый монитор»\n«куда слетать в сентябре»\n«робот-пылесос»\n\n"
            "Или выбрать категорию:",
            reply_markup=categories_keyboard(self.catalog),
        )

    async def help(self, message: Message) -> None:
        await message.answer(
            "Откройте «🔎 Найти предложения», напишите запрос или выберите категорию "
            "Pepper. Магазин открывается нажатием на его название. На результатах можно "
            "включить «🔔 Отслеживать этот поиск», а через «📋 Мои подписки» — поставить "
            "поиск на паузу, возобновить или удалить."
        )

    async def search_text(self, message: Message) -> None:
        if not message.text or not message.from_user:
            return
        status = await message.answer("🔎 Ищу свежие предложения…")
        try:
            result = await self.search.search(message.text)
            await self.database.upsert_offers(result.offers)
            session_id = await self.database.create_session(
                message.from_user.id,
                message.text,
                result.plan,
                result.offers,
                self.settings.search_session_ttl_seconds,
            )
            await self._render(status, session_id, result.offers, 0)
        except Exception:
            logger.exception("Interactive search failed")
            await status.edit_text("Pepper временно недоступен. Попробуйте ещё раз немного позже.")

    async def _render(
        self, message: Message, session_id: str, offers, page: int, *, watch: bool = True
    ) -> None:
        selected = self.search.page(offers, page)
        await message.edit_text(
            results_text(selected, len(offers), page, self.settings.timezone),
            reply_markup=result_keyboard(session_id, selected, page, len(offers), watch=watch),
        )

    async def paginate(self, callback: CallbackQuery) -> None:
        _, session_id, raw_page = (callback.data or "").split(":", 2)
        session = await self.database.get_session(session_id, callback.from_user.id)
        if not session or not callback.message:
            await callback.answer("Поиск устарел. Выполните его снова.", show_alert=True)
            return
        await self._render(
            callback.message,
            session_id,
            session["offers"],
            int(raw_page),
            watch=session["plan"].intent != "category",
        )
        await callback.answer()

    async def watch_search(self, callback: CallbackQuery) -> None:
        session_id = (callback.data or "").split(":", 1)[1]
        session = await self.database.get_session(session_id, callback.from_user.id)
        if not session:
            await callback.answer("Поиск устарел. Выполните его снова.", show_alert=True)
            return
        await self.database.create_subscription(
            callback.from_user.id,
            "search",
            session["query"],
            session["query"],
            session["offers"],
            session["plan"],
        )
        await callback.answer(
            "Отслеживание включено. Текущие предложения отмечены просмотренными.", show_alert=True
        )

    async def categories(self, message: Message) -> None:
        await message.answer("Выберите категорию:", reply_markup=categories_keyboard(self.catalog))

    async def category(self, callback: CallbackQuery) -> None:
        _, key, raw_page = (callback.data or "").split(":", 2)
        category = self.by_key.get(key)
        if not category or not callback.message:
            await callback.answer("Категория недоступна", show_alert=True)
            return
        page = int(raw_page)
        if category.children and page == 0:
            keyboard = categories_keyboard(category.children)
            keyboard.inline_keyboard.append(
                [InlineKeyboardButton(text="🔥 Все предложения", callback_data=f"cat:{key}:1")]
            )
            await callback.message.edit_text(
                f"{category.emoji} {category.name}", reply_markup=keyboard
            )
            await callback.answer()
            return
        try:
            offers = await self.pepper.category(category.path, page=max(1, page))
            offers = sorted(offers, key=lambda item: item.sort_key)[
                : self.settings.search_result_cap
            ]
            enriched = await asyncio.gather(
                *(self.pepper.enrich(item) for item in offers), return_exceptions=True
            )
            offers = [
                original if isinstance(value, BaseException) else value
                for original, value in zip(offers, enriched, strict=True)
            ]
            if not offers:
                await callback.answer("Активных предложений сейчас нет", show_alert=True)
                return
            plan = SearchPlan(
                original_query=category.path,
                intent="category",
                queries=[PlannedQuery(query=category.path)],
            )
            session_id = await self.database.create_session(
                callback.from_user.id,
                category.path,
                plan,
                offers,
                self.settings.search_session_ttl_seconds,
            )
            await self._render(callback.message, session_id, offers, 0, watch=False)
            await callback.answer()
        except Exception:
            logger.exception("Category browse failed")
            await callback.answer("Pepper временно недоступен", show_alert=True)

    async def watch_category(self, callback: CallbackQuery) -> None:
        _, session_id, key = (callback.data or "").split(":", 2)
        session = await self.database.get_session(session_id, callback.from_user.id)
        category = self.by_key.get(key)
        if not session or not category:
            await callback.answer("Просмотр устарел", show_alert=True)
            return
        await self.database.create_subscription(
            callback.from_user.id,
            "category",
            category.name,
            category.path,
            session["offers"],
        )
        await callback.answer(
            "Отслеживание включено. Текущие предложения не будут присланы повторно.",
            show_alert=True,
        )

    async def subscriptions(self, message: Message) -> None:
        if not message.from_user:
            return
        rows = await self.database.subscriptions(message.from_user.id)
        if not rows:
            await message.answer("У вас пока нет подписок.")
            return
        await message.answer("Ваши подписки:")
        for row in rows:
            icon = "🔎" if row["kind"] == "search" else "📁"
            state = "активна" if row["active"] else "на паузе"
            await message.answer(
                f"{icon} {row['label']} · {state}",
                reply_markup=subscription_actions(row["id"], bool(row["active"])),
            )

    async def subscription_action(self, callback: CallbackQuery) -> None:
        _, action, raw_id = (callback.data or "").split(":", 2)
        await self.database.set_subscription(int(raw_id), callback.from_user.id, action)
        await callback.answer("Готово", show_alert=True)
        if callback.message:
            await callback.message.delete()

    async def stats(self, message: Message) -> None:
        if not message.from_user or message.from_user.id not in self.settings.admin_ids:
            return
        stats = await self.database.stats()
        await message.answer("📊 " + "\n".join(f"{key}: {value}" for key, value in stats.items()))

    async def new_search(self, callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.message:
            await callback.message.answer("Что найти?")
