from __future__ import annotations

import logging
from typing import Any

from loot_hunt.pepper.models import Offer
from loot_hunt.telegram.formatting import offer_card

logger = logging.getLogger(__name__)


class ChannelPublisher:
    """Publishes viral/hot deals (temperature >= min_temperature) to a Telegram channel."""

    def __init__(
        self,
        bot: Any,
        channel_id: str | None,
        *,
        min_temperature: float = 300.0,
        timezone: str = "Europe/Warsaw",
        bot_username: str = "ulovio_bot",
        database: Any | None = None,
    ) -> None:
        self.bot = bot
        self.channel_id = channel_id
        self.min_temperature = min_temperature
        self.timezone = timezone
        self.bot_username = bot_username.lstrip("@") or "ulovio_bot"
        self.database = database
        self._published_threads: set[str] = set()

    async def maybe_publish(self, offer: Offer, timezone: str | None = None) -> bool:
        if not self.channel_id or not self.bot:
            return False
        if offer.thread_id in self._published_threads:
            return False
        if self.database is not None:
            try:
                if await self.database.was_channel_published(offer.thread_id):
                    self._published_threads.add(offer.thread_id)
                    return False
            except Exception as exc:
                logger.warning("Channel dedupe lookup failed for %s: %s", offer.thread_id, exc)
        if offer.temperature < self.min_temperature:
            return False

        card = offer_card(offer, timezone or self.timezone)
        post = (
            f"{card}\n\n"
            f"🔎 <i>Ищете скидки под себя? Запустите бота @{self.bot_username}</i>"
        )
        try:
            await self.bot.send_message(self.channel_id, post, parse_mode="HTML")
            self._published_threads.add(offer.thread_id)
        except Exception as exc:
            logger.warning("Channel auto-publish failed for %s: %s", offer.thread_id, exc)
            return False
        if self.database is not None:
            try:
                await self.database.mark_channel_published(offer.thread_id)
            except Exception as exc:
                logger.warning("Channel dedupe write failed for %s: %s", offer.thread_id, exc)
        return True
