from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import time
from urllib.parse import quote

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from loot_hunt.pepper.categories import PARENTS, flatten
from loot_hunt.platforms import PLATFORMS, get_platform
from loot_hunt.search.models import PlannedQuery, SearchPlan

from .formatting import results_text
from .keyboards import (
    categories_keyboard,
    main_menu,
    referral_keyboard,
    region_keyboard,
    result_keyboard,
    subscription_actions,
)

logger = logging.getLogger(__name__)

START_TEXT = (
    "<b>Ulovio</b> ищет предложения на Pepper.pl (PL), Mydealz.de (DE) и HotUKDeals (UK).\n\n"
    "Откройте «🔎 Найти предложения»: там можно написать запрос обычными словами\n"
    "или выбрать категорию из актуального каталога.\n"
    "Сменить регион поиска можно командой /region.\n\n"
    "На странице результатов нажмите «🔔 Отслеживать этот поиск».\n"
    "Сохранёнными поисками можно управлять через «📋 Мои подписки».\n\n"
    "<i>Часть ссылок на магазины — партнёрские: Ulovio получает комиссию, "
    "цена для вас не меняется.</i>"
)

MAX_QUERY_LENGTH = 200
SEARCH_COOLDOWN_SECONDS = 2.0


def _row_platform(row) -> str:
    """Read a stored platform from an sqlite3.Row or a plain dict."""
    try:
        return str(row["platform"] or "pl")
    except (IndexError, KeyError):
        return "pl"


class TelegramHandlers:
    def __init__(self, settings, database, search, pepper) -> None:
        self.settings = settings
        self.database = database
        self.search = search
        self.pepper = pepper
        self.catalog = PARENTS
        self.by_key = flatten(self.catalog)
        self._last_search_at: dict[int, float] = {}
        self.router = Router()
        self._register()

    def _bot_username(self) -> str:
        return getattr(self.settings, "bot_username", "ulovio_bot") or "ulovio_bot"

    async def refresh_catalog(self) -> None:
        try:
            self.catalog = await self.pepper.category_catalog()
            self.by_key = flatten(self.catalog)
        except Exception:
            logger.warning("Live category refresh failed; using verified parent snapshot")

    def _register(self) -> None:
        router = self.router
        router.message.register(self.start, CommandStart())
        router.message.register(self.region_command, Command("region"))
        router.message.register(self.referral_command, Command("ref"))
        router.message.register(self.referral_command, Command("invite"))
        router.message.register(self.categories, Command("categories"))
        router.message.register(self.ask_search, F.text == "🔎 Найти предложения")
        router.message.register(self.subscriptions, F.text == "📋 Мои подписки")
        router.message.register(self.help, Command("help"))
        router.message.register(self.help, F.text == "❓ Помощь")
        router.message.register(self.stats, F.text == "📊 Статистика")
        router.message.register(self.grant_command, Command("grant"))
        router.message.register(self.grant_command, Command("slots"))
        router.callback_query.register(self.set_region, F.data.startswith("reg:"))
        router.callback_query.register(self.share_deal_callback, F.data.startswith("share:"))
        router.callback_query.register(self.paginate, F.data.startswith("pg:"))
        router.callback_query.register(self.watch_search, F.data.startswith("ws:"))
        router.callback_query.register(self.category, F.data.startswith("cat:"))
        router.callback_query.register(self.watch_category, F.data.startswith("wc:"))
        router.callback_query.register(self.subscription_action, F.data.startswith("sub:"))
        router.callback_query.register(self.new_search, F.data == "new")
        router.message.register(self.unknown_command, F.text.startswith("/"))
        router.message.register(self.search_text, F.text)

    async def start(self, message: Message) -> None:
        admin = bool(message.from_user and message.from_user.id in self.settings.admin_ids)
        text = message.text or ""
        parts = text.split()
        if len(parts) > 1 and parts[1].startswith("ref_") and message.from_user:
            raw_ref = parts[1].removeprefix("ref_")
            if raw_ref.isdigit():
                referrer_id = int(raw_ref)
                if hasattr(self.database, "record_referral"):
                    recorded = await self.database.record_referral(
                        referrer_id, message.from_user.id
                    )
                    if recorded and message.bot:
                        with contextlib.suppress(Exception):
                            await message.bot.send_message(
                                referrer_id,
                                "🎉 <b>По вашей ссылке зарегистрировался новый пользователь!</b>\n"
                                "Вам начислено +2 слота для отслеживания скидок.",
                            )
        await message.answer(START_TEXT, reply_markup=main_menu(admin))

    async def referral_command(self, message: Message) -> None:
        if not message.from_user:
            return
        user_id = message.from_user.id
        count = 0
        limit = 3
        if hasattr(self.database, "get_referral_count"):
            count = await self.database.get_referral_count(user_id)
        if hasattr(self.database, "get_subscription_limit"):
            limit = await self.database.get_subscription_limit(user_id)
        badge = "<i>(вечный безлимит)</i>" if count >= 3 else f"<i>({limit} макс.)</i>"
        ref_link = f"https://t.me/{self._bot_username()}?start=ref_{user_id}"
        reply_text = (
            "🎁 <b>Приглашайте друзей в Ulovio и получайте бонусы!</b>\n\n"
            f"Ваша персональная ссылка:\n<code>{ref_link}</code>\n\n"
            "📊 <b>Ваша статистика:</b>\n"
            f"• Приглашено друзей: <b>{count}</b>\n"
            f"• Лимит активных подписок: <b>{limit}</b> {badge}\n\n"
            "За каждого приглашенного друга вы получаете <b>+2 слота</b> для отслеживания скидок.\n"
            "Пригласите 3 друзей, чтобы получить безлимит!"
        )
        markup = referral_keyboard(user_id, self._bot_username())
        await message.answer(reply_text, reply_markup=markup)

    async def region_command(self, message: Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        current = "pl"
        if hasattr(self.database, "get_user_platform"):
            current = await self.database.get_user_platform(user_id)
        platform = get_platform(current)
        await message.answer(
            f"Текущий регион поиска: {platform.flag} <b>{platform.name}</b>\n\n"
            "Выберите платформу Pepper Media Group для поиска скидок:",
            reply_markup=region_keyboard(current),
        )

    async def set_region(self, callback: CallbackQuery) -> None:
        _, code = (callback.data or "").split(":", 1)
        if code not in PLATFORMS:
            await callback.answer("Неизвестный регион", show_alert=True)
            return
        if hasattr(self.database, "set_user_platform"):
            await self.database.set_user_platform(callback.from_user.id, code)
        platform = get_platform(code)
        await callback.answer(f"Регион изменён: {platform.flag} {platform.name}", show_alert=True)
        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=region_keyboard(code))

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
            "поиск на паузу, возобновить или удалить.\n\n"
            "Команда /region переключает регион поиска (Польша, Германия или Великобритания).\n"
            "Команда /ref показывает вашу ссылку для приглашения друзей.\n\n"
            "💡 Можно уточнять свежесть: «сегодня», «со вчерашнего дня», «за неделю».\n\n"
            "<i>Ссылки на магазины могут быть партнёрскими: бот получает комиссию, "
            "цена для вас не меняется. Бот хранит только Telegram ID, поисковые запросы "
            "и подписки — они нужны для поиска и уведомлений.</i>"
        )

    async def unknown_command(self, message: Message) -> None:
        await message.answer(
            "Не знаю такую команду. Напишите запрос обычными словами или откройте "
            "«❓ Помощь».\n\nДоступно: /help, /region, /ref."
        )

    async def search_text(self, message: Message) -> None:
        if not message.text or not message.from_user:
            return
        query = message.text.strip()
        if not query:
            return
        if len(query) > MAX_QUERY_LENGTH:
            await message.answer(
                f"Запрос слишком длинный: {len(query)} символов. "
                f"Сократите его до {MAX_QUERY_LENGTH}."
            )
            return
        now = time.monotonic()
        last = self._last_search_at.get(message.from_user.id, 0.0)
        if now - last < SEARCH_COOLDOWN_SECONDS:
            await message.answer("Слишком часто. Подождите пару секунд и повторите.")
            return
        self._last_search_at[message.from_user.id] = now
        status = await message.answer("🔎 Ищу свежие предложения…")
        try:
            platform_code = "pl"
            if hasattr(self.database, "get_user_platform"):
                platform_code = await self.database.get_user_platform(message.from_user.id)
            try:
                result = await self.search.search(query, platform=platform_code)
            except TypeError:
                result = await self.search.search(query)
            await self.database.upsert_offers(result.offers)
            session_id = await self.database.create_session(
                message.from_user.id,
                query,
                result.plan,
                result.offers,
                self.settings.search_session_ttl_seconds,
            )
            spelling_notice = None
            if getattr(result, "spelling", None) and result.spelling.was_corrected:
                spelling_notice = (
                    f"✏️ <i>Показаны результаты для:</i> <b>{html.escape(result.spelling.effective_query)}</b>\n"
                    f"<i>(исправлена опечатка с «{html.escape(result.spelling.original_query)}»)</i>"
                )
            await self._render(status, session_id, result.offers, 0, spelling_notice=spelling_notice)
        except Exception:
            logger.exception("Interactive search failed")
            await status.edit_text("Pepper временно недоступен. Попробуйте ещё раз немного позже.")

    async def _render(
        self,
        message: Message,
        session_id: str,
        offers,
        page: int,
        *,
        watch: bool = True,
        category_key: str | None = None,
        spelling_notice: str | None = None,
    ) -> None:
        selected = self.search.page(offers, page)
        try:
            body = results_text(selected, len(offers), page, self.settings.timezone)
            if spelling_notice:
                body = f"{spelling_notice}\n\n{body}"
            await message.edit_text(
                body,
                reply_markup=result_keyboard(
                    session_id, selected, page, len(offers), watch=watch, category_key=category_key
                ),
            )
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc):
                return
            logger.exception("Result rendering failed")
            with contextlib.suppress(Exception):
                await message.edit_text(
                    "Не удалось отобразить результаты. Попробуйте выполнить поиск ещё раз."
                )
        except Exception:
            logger.exception("Result rendering failed")
            with contextlib.suppress(Exception):
                await message.edit_text(
                    "Не удалось отобразить результаты. Попробуйте выполнить поиск ещё раз."
                )

    async def paginate(self, callback: CallbackQuery) -> None:
        _, session_id, raw_page = (callback.data or "").split(":", 2)
        session = await self.database.get_session(session_id, callback.from_user.id)
        if not session or not callback.message:
            await callback.answer("Поиск устарел. Выполните его снова.", show_alert=True)
            return
        cat_key = None
        if session["plan"].intent == "category":
            cat_key = next((k for k, v in self.by_key.items() if v.path == session["query"]), None)
        await self._render(
            callback.message,
            session_id,
            session["offers"],
            int(raw_page),
            watch=True,
            category_key=cat_key,
        )
        with contextlib.suppress(Exception):
            await callback.answer()

    async def watch_search(self, callback: CallbackQuery) -> None:
        session_id = (callback.data or "").split(":", 1)[1]
        session = await self.database.get_session(session_id, callback.from_user.id)
        if not session:
            await callback.answer("Поиск устарел. Выполните его снова.", show_alert=True)
            return
        if hasattr(self.database, "find_subscription"):
            existing = await self.database.find_subscription(
                callback.from_user.id, "search", session["query"]
            )
            if existing:
                await callback.answer(
                    "Этот поиск уже отслеживается — управляйте им в «📋 Мои подписки».",
                    show_alert=True,
                )
                return
        if hasattr(self.database, "can_add_subscription"):
            can_add = await self.database.can_add_subscription(callback.from_user.id)
            if not can_add:
                limit = (
                    await self.database.get_subscription_limit(callback.from_user.id)
                    if hasattr(self.database, "get_subscription_limit")
                    else 3
                )
                await callback.answer(
                    f"Достигнут лимит активных подписок ({limit})!\n"
                    "Пригласите друга по команде /ref, чтобы получить +2 слота.",
                    show_alert=True,
                )
                return
        plan = session["plan"]
        platform_code = getattr(plan, "platform", "pl")
        try:
            await self.database.create_subscription(
                callback.from_user.id,
                "search",
                session["query"],
                session["query"],
                session["offers"],
                session["plan"],
                platform=platform_code,
            )
        except TypeError:
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
        if key == "root" and callback.message:
            await callback.message.edit_text(
                "Выберите категорию:", reply_markup=categories_keyboard(self.catalog)
            )
            await callback.answer()
            return
        category = self.by_key.get(key)
        if not category or not callback.message:
            await callback.answer("Категория недоступна", show_alert=True)
            return
        page = int(raw_page)
        if category.children and page == 0:
            keyboard = categories_keyboard(category.children, show_back=True)
            keyboard.inline_keyboard.insert(
                0,
                [InlineKeyboardButton(text="🔥 Все предложения", callback_data=f"cat:{key}:1")],
            )
            await callback.message.edit_text(
                f"{category.emoji} {html.escape(category.name)}", reply_markup=keyboard
            )
            await callback.answer()
            return
        try:
            platform_code = "pl"
            if hasattr(self.database, "get_user_platform"):
                platform_code = await self.database.get_user_platform(callback.from_user.id)
            try:
                offers = await self.pepper.category(
                    category.path, page=max(1, page), platform=platform_code
                )
            except TypeError:
                offers = await self.pepper.category(category.path, page=max(1, page))
            offers = sorted(offers, key=lambda item: item.sort_key)[
                : self.settings.search_result_cap
            ]

            async def enrich_item(item):
                try:
                    return await self.pepper.enrich(item, platform=platform_code)
                except TypeError:
                    return await self.pepper.enrich(item)

            enriched = await asyncio.gather(
                *(enrich_item(item) for item in offers),
                return_exceptions=True,
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
                platform=platform_code,
                queries=[PlannedQuery(query=category.path)],
            )
            session_id = await self.database.create_session(
                callback.from_user.id,
                category.path,
                plan,
                offers,
                self.settings.search_session_ttl_seconds,
            )
            await self._render(
                callback.message, session_id, offers, 0, watch=True, category_key=key
            )
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
        if hasattr(self.database, "find_subscription"):
            existing = await self.database.find_subscription(
                callback.from_user.id, "category", category.path
            )
            if existing:
                await callback.answer(
                    "Эта категория уже отслеживается — управляйте подпиской в «📋 Мои подписки».",
                    show_alert=True,
                )
                return
        if hasattr(self.database, "can_add_subscription"):
            can_add = await self.database.can_add_subscription(callback.from_user.id)
            if not can_add:
                limit = (
                    await self.database.get_subscription_limit(callback.from_user.id)
                    if hasattr(self.database, "get_subscription_limit")
                    else 3
                )
                await callback.answer(
                    f"Достигнут лимит активных подписок ({limit})!\n"
                    "Пригласите друга по команде /ref, чтобы получить +2 слота.",
                    show_alert=True,
                )
                return
        platform_code = "pl"
        if hasattr(self.database, "get_user_platform"):
            platform_code = await self.database.get_user_platform(callback.from_user.id)
        try:
            await self.database.create_subscription(
                callback.from_user.id,
                "category",
                category.name,
                category.path,
                session["offers"],
                platform=platform_code,
            )
        except TypeError:
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
            p_code = _row_platform(row)
            flag = f"{PLATFORMS[p_code].flag} " if p_code != "pl" and p_code in PLATFORMS else ""
            await message.answer(
                f"{flag}{icon} {html.escape(str(row['label']))} · {state}",
                reply_markup=subscription_actions(row["id"], bool(row["active"])),
            )

    async def subscription_action(self, callback: CallbackQuery) -> None:
        _, action, raw_id = (callback.data or "").split(":", 2)
        subscription_id = int(raw_id)
        changed = await self.database.set_subscription(
            subscription_id, callback.from_user.id, action
        )
        if not changed:
            await callback.answer(
                "Не удалось изменить подписку: она удалена или исчерпан лимит.",
                show_alert=True,
            )
            return
        if action == "delete":
            if callback.message:
                with contextlib.suppress(Exception):
                    await callback.message.edit_text("🗑 Подписка удалена.")
            await callback.answer("Удалено")
            return
        active = action == "resume"
        if callback.message:
            current = callback.message.text or ""
            current = (
                current.replace("· на паузе", "· активна")
                if active
                else current.replace("· активна", "· на паузе")
            )
            with contextlib.suppress(Exception):
                if current != (callback.message.text or ""):
                    await callback.message.edit_text(
                        current, reply_markup=subscription_actions(subscription_id, active)
                    )
                else:
                    await callback.message.edit_reply_markup(
                        reply_markup=subscription_actions(subscription_id, active)
                    )
        await callback.answer("Отслеживание возобновлено" if active else "Пауза включена")

    async def stats(self, message: Message) -> None:
        if not message.from_user or message.from_user.id not in self.settings.admin_ids:
            return
        stats = await self.database.stats()
        await message.answer("📊 " + "\n".join(f"{key}: {value}" for key, value in stats.items()))

    async def new_search(self, callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.message:
            await callback.message.answer("Что найти?")

    async def grant_command(self, message: Message) -> None:
        if not message.from_user or message.from_user.id not in self.settings.admin_ids:
            return
        text = message.text or ""
        parts = text.split()
        if len(parts) < 3:
            await message.answer(
                "Использование: <code>/grant &lt;user_id&gt; &lt;slots&gt;</code>\n"
                "Пример: <code>/grant 123456789 5</code>"
            )
            return
        target_raw = parts[1]
        slots_raw = parts[2]
        if not target_raw.isdigit() or not (
            slots_raw.isdigit()
            or (slots_raw.startswith("-") and slots_raw[1:].isdigit())
        ):
            await message.answer("Ошибка: user_id и slots должны быть числами.")
            return
        target_user_id = int(target_raw)
        slots = int(slots_raw)
        if hasattr(self.database, "grant_bonus_slots"):
            new_bonus = await self.database.grant_bonus_slots(
                target_user_id, slots, granted_by=message.from_user.id
            )
            new_total = (
                await self.database.get_subscription_limit(target_user_id)
                if hasattr(self.database, "get_subscription_limit")
                else new_bonus
            )
            sign = "+" if slots > 0 else ""
            await message.answer(
                f"✅ Пользователю <code>{target_user_id}</code> начислено {sign}{slots} слотов.\n"
                f"Бонусных слотов: <b>{new_bonus}</b>\n"
                f"Итоговый лимит: <b>{new_total}</b> подписок."
            )
            if message.bot:
                with contextlib.suppress(Exception):
                    await message.bot.send_message(
                        target_user_id,
                        f"🎉 <b>Администратор начислил вам {sign}{slots} слотов!</b>\n"
                        f"Ваш новый лимит: <b>{new_total}</b> подписок.",
                    )

    async def share_deal_callback(self, callback: CallbackQuery) -> None:
        if not callback.from_user:
            return
        parts = (callback.data or "").split(":")
        if len(parts) < 2:
            await callback.answer("Сессия поиска устарела.", show_alert=True)
            return
        session_id = parts[1]
        page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        session = await self.database.get_session(session_id, callback.from_user.id)
        if not session or not session.get("offers"):
            await callback.answer("Сессия поиска устарела.", show_alert=True)
            return
        offers = session["offers"]
        if self.search is not None:
            offers = self.search.page(offers, page) or offers
        top_offer = offers[0]
        user_id = callback.from_user.id
        ref_link = f"https://t.me/{self._bot_username()}?start=ref_{user_id}"
        deal_url = top_offer.pepper_url or top_offer.merchant_url or ref_link
        price_info = f" за {top_offer.display_price}" if top_offer.current_price else ""
        share_text = quote(
            f"Смотри какую скидку нашел через Ulovio: {top_offer.title}{price_info}\n\n"
            f"Ищи скидки в Польше и Германии в боте: {ref_link}"
        )
        share_url = (
            f"https://t.me/share/url?url={quote(deal_url, safe='')}&text={share_text}"
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📲 Отправить в чат Telegram ↗",
                        url=share_url,
                    )
                ]
            ]
        )
        if callback.message:
            await callback.message.answer(
                f"Поделиться скидкой на <b>{html.escape(top_offer.title)}</b>:\n\n"
                "Нажмите кнопку ниже, чтобы переслать ее с вашей реферальной ссылкой:",
                reply_markup=keyboard,
            )
        await callback.answer()
