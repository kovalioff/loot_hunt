from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .config import Settings
from .database import Database
from .pepper.client import PepperClient
from .search.planner import SearchPlanner
from .search.service import SearchService
from .telegram.formatting import offer_card
from .telegram.handlers import TelegramHandlers
from .watch.service import WatcherService


async def run() -> None:
    settings = Settings.from_env()
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is required")
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    database = Database(settings.database_path)
    await database.connect()
    pepper = PepperClient(
        timeout=settings.pepper_timeout_seconds,
        max_concurrency=settings.pepper_max_concurrency,
    )
    planner = SearchPlanner(settings.gemini_api_key)
    search = SearchService(planner, pepper, cap=settings.search_result_cap)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    handlers = TelegramHandlers(settings, database, search, pepper)
    dispatcher = Dispatcher()
    dispatcher.include_router(handlers.router)
    await handlers.refresh_catalog()

    async def notify(user_id: int, subscription_id: int, offer) -> None:
        buttons = []
        if offer.merchant_url:
            buttons.append(
                [InlineKeyboardButton(text="🛒 Открыть предложение", url=offer.merchant_url)]
            )
        buttons.append(
            [
                InlineKeyboardButton(
                    text="🔕 Отключить отслеживание", callback_data=f"sub:pause:{subscription_id}"
                )
            ]
        )
        await bot.send_message(
            user_id,
            "🆕 <b>Новое предложение</b>\n\n" + offer_card(offer, settings.timezone),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )

    watcher = WatcherService(database, search, pepper, notify)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(name, stop.set)
    watcher_task = asyncio.create_task(
        watcher.run(settings.watcher_interval_seconds, stop), name="subscription-watcher"
    )
    polling_task = asyncio.create_task(dispatcher.start_polling(bot), name="telegram-polling")
    try:
        await polling_task
    finally:
        stop.set()
        if dispatcher._polling:
            await dispatcher.stop_polling()
        await watcher_task
        await bot.session.close()
        await pepper.close()
        await database.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
