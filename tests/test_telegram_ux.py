from types import SimpleNamespace
from unittest.mock import AsyncMock

from loot_hunt.telegram.handlers import START_TEXT, TelegramHandlers


def handlers(database=None):
    settings = SimpleNamespace(admin_ids=frozenset(), timezone="Europe/Warsaw")
    return TelegramHandlers(settings, database, None, None)


async def test_find_offers_exposes_live_category_entry_point():
    message = SimpleNamespace(answer=AsyncMock())
    instance = handlers()
    await instance.ask_search(message)
    text = message.answer.await_args.args[0]
    keyboard = message.answer.await_args.kwargs["reply_markup"]
    assert "Можно написать запрос" in text and "Или выбрать категорию" in text
    assert len(keyboard.inline_keyboard) == len(instance.catalog)
    assert all(row[0].callback_data.startswith("cat:") for row in keyboard.inline_keyboard)


async def test_existing_category_subscription_remains_manageable():
    database = SimpleNamespace(
        subscriptions=AsyncMock(
            return_value=[{"id": 3, "kind": "category", "label": "Gaming", "active": 1}]
        )
    )
    message = SimpleNamespace(from_user=SimpleNamespace(id=7), answer=AsyncMock())
    await handlers(database).subscriptions(message)
    rendered = message.answer.await_args_list[-1].args[0]
    assert rendered == "📁 Gaming · активна"


def test_start_text_explains_new_navigation():
    assert "🔎 Найти предложения" in START_TEXT
    assert "🔔 Отслеживать этот поиск" in START_TEXT
    assert "📋 Мои подписки" in START_TEXT
    assert "Через Отслеживание" not in START_TEXT
