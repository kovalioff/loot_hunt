from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from urllib.parse import quote, urljoin, urlparse

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException

from loot_hunt.affiliate import AffiliateTransformer
from loot_hunt.extractors import ExtractedProductInfo, extract_product_microdata
from loot_hunt.platforms import Platform, get_platform

from .categories import PARENTS, Category, category_from_group
from .models import Offer
from .parser import (
    PEPPER_DOMAINS,
    detail_from_page,
    initial_state,
    listing_threads,
    normalize_offer,
)

logger = logging.getLogger(__name__)


class PepperError(RuntimeError):
    pass


class PepperClient:
    def __init__(
        self,
        *,
        timeout: int = 25,
        max_concurrency: int = 4,
        platform: Platform | str = "pl",
        affiliate: AffiliateTransformer | None = None,
    ) -> None:
        self.timeout = timeout
        self.platform = get_platform(platform)
        self.affiliate = affiliate or AffiliateTransformer()
        self._session = AsyncSession(impersonate="chrome")
        self._warmed_hosts: set[str] = set()
        self._warmup_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def close(self) -> None:
        await self._session.close()

    async def _get(self, url: str, *, allow_redirects: bool = True):
        parsed = urlparse(url)
        host = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else self.platform.domain
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                if host not in self._warmed_hosts:
                    async with self._warmup_lock:
                        if host not in self._warmed_hosts:
                            warm = await self._session.get(host, timeout=self.timeout)
                            warm.raise_for_status()
                            self._warmed_hosts.add(host)
                response = await self._session.get(
                    url, timeout=self.timeout, allow_redirects=allow_redirects
                )
                if response.status_code in {418, 429, 503} and attempt < 2:
                    self._warmed_hosts.discard(host)
                    delay = (2**attempt) + random.uniform(1.0, 3.0)
                    if retry_after := response.headers.get("Retry-After"):
                        with contextlib.suppress(ValueError):
                            delay = max(delay, float(retry_after))
                    await asyncio.sleep(delay)
                    continue
                response.raise_for_status()
                return response
            except RequestException as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep((2**attempt) + random.random())
        raise PepperError(f"Pepper request failed for {url}: {last_error}")

    async def _page(self, url: str) -> str:
        async with self._semaphore:
            response = await self._get(url)
            return response.text

    async def search(
        self,
        query: str,
        *,
        page: int = 1,
        group_id: str | None = None,
        platform: Platform | str | None = None,
    ) -> list[Offer]:
        target = get_platform(platform) if platform else self.platform
        url = f"{target.domain}/search?q={quote(query)}"
        if group_id:
            url += f"&groups={quote(group_id)}"
        if page > 1:
            url += f"&page={page}"
        return await self._listing(url, target)

    async def category(
        self,
        path: str,
        *,
        page: int = 1,
        platform: Platform | str | None = None,
    ) -> list[Offer]:
        target = get_platform(platform) if platform else self.platform
        url = urljoin(target.domain, path)
        if page > 1:
            url += ("&" if "?" in url else "?") + f"page={page}"
        return await self._listing(url, target)

    async def _listing(self, url: str, target: Platform) -> list[Offer]:
        page = await self._page(url)
        offers: list[Offer] = []
        for raw in listing_threads(page):
            offer = normalize_offer(raw, platform_code=target.code, base_url=target.domain)
            if offer and not offer.is_expired:
                if offer.pepper_url and offer.pepper_url.startswith("/"):
                    offer.pepper_url = urljoin(target.domain, offer.pepper_url)
                offers.append(offer)
        return offers

    async def details(
        self,
        pepper_url: str,
        *,
        platform: Platform | str | None = None,
    ) -> Offer | None:
        target = get_platform(platform) if platform else self.platform
        return detail_from_page(
            await self._page(pepper_url),
            pepper_url,
            platform_code=target.code,
            base_url=target.domain,
        )

    async def enrich(
        self,
        offer: Offer,
        *,
        platform: Platform | str | None = None,
    ) -> Offer:
        if not offer.pepper_url:
            return offer
        target = get_platform(platform or offer.platform_code)
        if not offer.merchant_url:
            detail = await self.details(offer.pepper_url, platform=target)
            if detail:
                for field in Offer.__dataclass_fields__:
                    value = getattr(detail, field)
                    if value not in (None, "", 0, False) or field == "is_expired":
                        setattr(offer, field, value)
        if offer.merchant_url:
            parsed = urlparse(offer.merchant_url)
            if any(parsed.netloc.lower().endswith(d) for d in PEPPER_DOMAINS):
                resolved_url, microdata = await self.resolve_merchant_info(
                    offer.merchant_url, current_price=offer.current_price, platform=target
                )
                offer.merchant_url = resolved_url
                if microdata:
                    if microdata.ean and not offer.ean:
                        offer.ean = microdata.ean
                    if microdata.omnibus_price:
                        offer.omnibus_price = microdata.omnibus_price
                        offer.fair_discount_pct = microdata.fair_discount_pct
                        offer.is_fake_discount = microdata.is_fake_discount
        if offer.merchant_url:
            offer.merchant_url = self.affiliate.transform(
                offer.merchant_url, platform_code=target.code
            )
        return offer

    async def resolve_merchant_info(
        self,
        url: str | None,
        *,
        current_price: float | None = None,
        platform: Platform | str | None = None,
    ) -> tuple[str | None, ExtractedProductInfo | None]:
        if not url:
            return None, None
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if not any(netloc.endswith(d) for d in PEPPER_DOMAINS):
            return url, None
        try:
            async with self._semaphore:
                response = await self._get(url)
            final = str(response.url)
            final_netloc = urlparse(final).netloc.lower()
            if final and not any(final_netloc.endswith(d) for d in PEPPER_DOMAINS):
                microdata = extract_product_microdata(response.text, current_price=current_price)
                return final, microdata
            return None, None
        except PepperError:
            return None, None

    async def resolve_merchant_url(
        self,
        url: str | None,
        *,
        platform: Platform | str | None = None,
    ) -> str | None:
        final_url, _ = await self.resolve_merchant_info(url, platform=platform)
        return final_url

    async def category_catalog(
        self, platform: Platform | str | None = None
    ) -> tuple[Category, ...]:
        target = get_platform(platform) if platform else self.platform

        async def load(parent: Category) -> Category:
            try:
                state = initial_state(await self._page(urljoin(target.domain, parent.path)))
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
