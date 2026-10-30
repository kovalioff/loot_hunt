from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessage

from loot_hunt.pepper.models import Offer
from loot_hunt.telegram.formatting import notification_chunks
from loot_hunt.telegram.notifier import TelegramNotifier


def retry_after(seconds: int = 2) -> TelegramRetryAfter:
    return TelegramRetryAfter(
        SendMessage(chat_id=1, text="x"), "Too Many Requests: retry later", retry_after=seconds
    )


async def test_notifier_batches_offers_into_one_message():
    bot = SimpleNamespace(send_message=AsyncMock())
    notifier = TelegramNotifier(bot, "Europe/Warsaw")

    await notifier(
        7,
        3,
        [Offer("1", "One", current_price=10), Offer("2", "Two", current_price=20)],
    )

    bot.send_message.assert_awaited_once()
    text = bot.send_message.await_args.args[1]
    assert "Новые предложения: 2" in text
    assert "One" in text and "Two" in text
    keyboard = bot.send_message.await_args.kwargs["reply_markup"]
    assert keyboard.inline_keyboard[0][0].callback_data == "sub:pause:3"


async def test_notifier_splits_messages_to_telegram_limit():
    offers = [
        Offer(str(index), f"Offer {index} " + "x" * 600, current_price=1)
        for index in range(12)
    ]

    chunks = notification_chunks(offers, "Europe/Warsaw")

    assert len(chunks) > 1
    assert all(len(chunk) <= 3800 for chunk in chunks)
    combined = "\n".join(chunks)
    assert all(f"Offer {index} " in combined for index in range(12))


async def test_notifier_retries_after_flood_control():
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=[retry_after(2), None]))
    slept = []

    async def sleeper(seconds):
        slept.append(seconds)

    notifier = TelegramNotifier(bot, "Europe/Warsaw", sleeper=sleeper)

    await notifier(7, 3, [Offer("1", "One")])

    assert bot.send_message.await_count == 2
    assert slept == [2]


async def test_notifier_gives_up_after_max_attempts():
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=retry_after(1)))

    async def sleeper(seconds):
        return None

    notifier = TelegramNotifier(bot, "Europe/Warsaw", max_attempts=2, sleeper=sleeper)

    with pytest.raises(TelegramRetryAfter):
        await notifier(7, 3, [Offer("1", "One")])
    assert bot.send_message.await_count == 2
