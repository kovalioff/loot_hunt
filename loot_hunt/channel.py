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
    ) -> None:
        self.bot = bot
        self.channel_id = channel_id
        self.min_temperature = min_temperature
        self._published_threads: set[str] = set()

    async def maybe_publish(
        self, offer: Offer, timezone: str = "Europe/Warsaw"
    ) -> bool:
        if not self.channel_id or not self.bot:
            return False
        if offer.thread_id in self._published_threads:
            return False
        if offer.temperature < self.min_temperature:
            return False

        card = offer_card(offer, timezone)
        post = (
            f"{card}\n\n"
            "🔎 <i>Ищете скидки под себя? Запустите бота @loot_hunt_bot</i>"
        )
        try:
            await self.bot.send_message(self.channel_id, post, parse_mode="HTML")
            self._published_threads.add(offer.thread_id)
            return True
        except Exception as exc:
            logger.warning("Channel auto-publish failed for %s: %s", offer.thread_id, exc)
            return False
