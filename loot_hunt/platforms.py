from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Platform:
    code: str
    name: str
    domain: str
    currency: str
    currency_code: str
    country: str
    flag: str
    language: str
    approx_rate_to_pln: float
    forwarding_service_name: str | None = None
    forwarding_price_pln: float | None = None
    forwarding_url: str | None = None
    forwarding_note: str | None = None

    def to_pln(self, price: float | None) -> float | None:
        if price is None:
            return None
        return round(price * self.approx_rate_to_pln, 2)

    def format_price(self, price: float | None) -> str:
        if price is None:
            return ""
        formatted = f"{price:,.2f}".replace(",", " ").replace(".00", "")
        return f"{formatted} {self.currency}"

    def format_price_with_pln(self, price: float | None) -> str:
        if price is None:
            return ""
        base = self.format_price(price)
        if self.code == "pl" or self.approx_rate_to_pln == 1.0:
            return base
        pln = self.to_pln(price)
        pln_str = f"{pln:,.2f}".replace(",", " ").replace(".00", "") + " zł"
        return f"{base} (~{pln_str})"


PLATFORMS: dict[str, Platform] = {
    "pl": Platform(
        code="pl",
        name="Polska (Pepper.pl)",
        domain="https://www.pepper.pl",
        currency="zł",
        currency_code="PLN",
        country="PL",
        flag="🇵🇱",
        language="pl",
        approx_rate_to_pln=1.0,
        forwarding_service_name=None,
        forwarding_price_pln=None,
        forwarding_url=None,
        forwarding_note=None,
    ),
    "de": Platform(
        code="de",
        name="Niemcy (Mydealz.de)",
        domain="https://www.mydealz.de",
        currency="€",
        currency_code="EUR",
        country="DE",
        flag="🇩🇪",
        language="de",
        approx_rate_to_pln=4.30,
        forwarding_service_name="Bodycar1.com",
        forwarding_price_pln=46.0,
        forwarding_url="https://bodycar1.com/",
        forwarding_note="склад в Гёрлице → Paczkomat InPost до 25 кг",
    ),
    "uk": Platform(
        code="uk",
        name="UK (HotUKDeals.com)",
        domain="https://www.hotukdeals.com",
        currency="£",
        currency_code="GBP",
        country="GB",
        flag="🇬🇧",
        language="en",
        approx_rate_to_pln=5.15,
        forwarding_service_name="Meest Post",
        forwarding_price_pln=55.0,
        forwarding_url="https://www.meestpost.com/",
        forwarding_note="склад в Лондоне → Paczkomat InPost / курьер в Польшу",
    ),
}

DEFAULT_PLATFORM_CODE = "pl"


def get_platform(code: str | Platform | None = None) -> Platform:
    if isinstance(code, Platform):
        return code
    if not code:
        return PLATFORMS[DEFAULT_PLATFORM_CODE]
    normalized = str(code).lower().strip()
    return PLATFORMS.get(normalized, PLATFORMS[DEFAULT_PLATFORM_CODE])
