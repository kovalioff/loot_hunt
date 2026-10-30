from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram.exceptions import TelegramRetryAfter

from .formatting import notification_chunks
from .keyboards import notification_keyboard

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Send new offers in batches and respect Telegram flood control."""

    def __init__(
        self,
        bot: Any,
        timezone: str,
        *,
        max_attempts: int = 3,
        sleeper=asyncio.sleep,
    ) -> None:
        self.bot = bot
        self.timezone = timezone
        self.max_attempts = max(1, max_attempts)
        self._sleep = sleeper

    async def __call__(self, user_id: int, subscription_id: int, offers: list) -> None:
        if not offers:
            return
        header = (
            "🆕 <b>Новое предложение</b>"
            if len(offers) == 1
            else f"🆕 <b>Новые предложения: {len(offers)}</b>"
        )
        for chunk in notification_chunks(offers, self.timezone):
            await self._send(
                user_id,
                f"{header}\n\n{chunk}",
                notification_keyboard(subscription_id),
            )

    async def _send(self, user_id: int, text: str, reply_markup) -> None:
        for attempt in range(self.max_attempts):
            try:
                await self.bot.send_message(user_id, text, reply_markup=reply_markup)
                return
            except TelegramRetryAfter as exc:
                if attempt == self.max_attempts - 1:
                    raise
                logger.warning(
                    "Telegram flood control: retry after %s seconds (user %s)",
                    exc.retry_after,
                    user_id,
                )
                await self._sleep(exc.retry_after)
