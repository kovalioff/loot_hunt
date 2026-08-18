from __future__ import annotations

import asyncio
import logging
import random
from urllib.parse import quote, urljoin, urlparse

from curl_cffi.requests import Session
from curl_cffi.requests.exceptions import RequestException

from .categories import PARENTS, Category, category_from_group
from .models import Offer
from .parser import BASE_URL, detail_from_page, initial_state, listing_threads, normalize_offer

logger = logging.getLogger(__name__)


class PepperError(RuntimeError):
    pass


class PepperClient:
    def __init__(self, *, timeout: int = 25, max_concurrency: int = 4) -> None:
        self.timeout = timeout
        self._session = Session(impersonate="chrome")
        self._ready = False
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def close(self) -> None:
        await asyncio.to_thread(self._session.close)

    def _get(self, url: str, *, allow_redirects: bool = True):
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                if not self._ready:
                    warm = self._session.get(BASE_URL, timeout=self.timeout)
                    warm.raise_for_status()
                    self._ready = True
                response = self._session.get(
                    url, timeout=self.timeout, allow_redirects=allow_redirects
                )
                if response.status_code in {418, 429, 503} and attempt < 2:
                    self._ready = False
                    continue
                response.raise_for_status()
                return response
            except RequestException as exc:
                last_error = exc
                if attempt < 2:
                    import time

                    time.sleep((2**attempt) + random.random())
        raise PepperError(f"Pepper request failed for {url}: {last_error}")

    async def _page(self, url: str) -> str:
        async with self._semaphore:
            response = await asyncio.to_thread(self._get, url)
            return response.text

    async def search(self, query: str, *, page: int = 1) -> list[Offer]:
        url = f"{BASE_URL}/search?q={quote(query)}"
        if page > 1:
            url += f"&page={page}"
        return await self._listing(url)

    async def category(self, path: str, *, page: int = 1) -> list[Offer]:
        url = urljoin(BASE_URL, path)
        if page > 1:
            url += ("&" if "?" in url else "?") + f"page={page}"
        return await self._listing(url)

    async def _listing(self, url: str) -> list[Offer]:
        page = await self._page(url)
        offers: list[Offer] = []
        for raw in listing_threads(page):
            offer = normalize_offer(raw)
            if offer and not offer.is_expired:
                if offer.pepper_url and offer.pepper_url.startswith("/"):
                    offer.pepper_url = urljoin(BASE_URL, offer.pepper_url)
                offers.append(offer)
        return offers

    async def details(self, pepper_url: str) -> Offer | None:
        return detail_from_page(await self._page(pepper_url), pepper_url)

    async def enrich(self, offer: Offer) -> Offer:
        if not offer.pepper_url or (offer.merchant_url and offer.coupon_code):
            return offer
        detail = await self.details(offer.pepper_url)
        if not detail:
            return offer
        for field in Offer.__dataclass_fields__:
            value = getattr(detail, field)
            if value not in (None, "", 0, False) or field == "is_expired":
                setattr(offer, field, value)
        offer.merchant_url = await self.resolve_merchant_url(offer.merchant_url)
        return offer

    async def resolve_merchant_url(self, url: str | None) -> str | None:
        if not url:
            return None
        parsed = urlparse(url)
        if not parsed.netloc.endswith("pepper.pl"):
            return url
        try:
            async with self._semaphore:
                response = await asyncio.to_thread(self._get, url)
            final = str(response.url)
            return final if final and not urlparse(final).netloc.endswith("pepper.pl") else None
        except PepperError:
            return None

    async def category_catalog(self) -> tuple[Category, ...]:
        async def load(parent: Category) -> Category:
            try:
                state = initial_state(await self._page(urljoin(BASE_URL, parent.path)))
                group = state.get("group")
                return (
                    category_from_group(group, fallback=parent)
                    if isinstance(group, dict)
                    else parent
                )
            except Exception:
                logger.warning("Category refresh failed for %s", parent.path)
                return parent

        return tuple(await asyncio.gather(*(load(parent) for parent in PARENTS)))
