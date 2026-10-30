from __future__ import annotations

import os
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse


def _host_in(hostname: str, domain: str) -> bool:
    """Match the domain itself or any subdomain, never a lookalike like evil-allegro.pl."""
    return hostname == domain or hostname.endswith(f".{domain}")


AMAZON_DOMAINS = (
    "amazon.pl",
    "amazon.de",
    "amazon.co.uk",
    "amazon.com",
    "amazon.fr",
    "amazon.it",
    "amazon.es",
    "amazon.nl",
    "amazon.se",
    "amazon.be",
    "amazon.ca",
    "amazon.com.br",
    "amazon.com.mx",
    "amazon.com.au",
    "amazon.co.jp",
    "amazon.in",
    "amazon.sg",
    "amazon.ae",
    "amazon.sa",
    "amazon.eg",
    "amazon.com.tr",
)


def _amazon_host(hostname: str) -> bool:
    if hostname == "amzn.to" or hostname.endswith(".amzn.to"):
        return True
    return any(_host_in(hostname, domain) for domain in AMAZON_DOMAINS)


class AffiliateTransformer:
    def __init__(
        self,
        amazon_tags: dict[str, str] | None = None,
        allegro_prefix: str | None = None,
        awin_template: str | None = None,
    ) -> None:
        self.amazon_tags = (
            amazon_tags
            if amazon_tags is not None
            else {
                "pl": os.getenv("AMAZON_TAG_PL", "loothunt-pl-21"),
                "de": os.getenv("AMAZON_TAG_DE", "loothunt-de-21"),
                "uk": os.getenv("AMAZON_TAG_UK", "loothunt-uk-21"),
            }
        )
        self.allegro_prefix = (
            allegro_prefix
            if allegro_prefix is not None
            else os.getenv("ALLEGRO_AFFILIATE_PREFIX")
        )
        self.awin_template = (
            awin_template
            if awin_template is not None
            else os.getenv("AWIN_AFFILIATE_TEMPLATE")
        )

    def transform(self, url: str | None, platform_code: str = "pl") -> str | None:
        if not url:
            return None
        parsed = urlparse(url)
        if not parsed.netloc:
            return url
        hostname = (parsed.hostname or "").lower()

        # Never wrap a link twice: renders may re-apply the transformer to a stored URL.
        for prefix in self._wrapper_prefixes():
            if url.startswith(prefix):
                return url

        # Amazon Associates. Match only real Amazon labels: "notamazon.com" must stay untouched.
        if _amazon_host(hostname):
            tag = None
            if hostname.endswith(".pl"):
                tag = self.amazon_tags.get("pl")
            elif hostname.endswith(".de"):
                tag = self.amazon_tags.get("de")
            elif hostname.endswith(".co.uk") or hostname.endswith(".uk"):
                tag = self.amazon_tags.get("uk")
            else:
                tag = self.amazon_tags.get(platform_code) or self.amazon_tags.get("pl")

            if tag:
                params = dict(parse_qsl(parsed.query, keep_blank_values=True))
                if params.get("tag") == tag:
                    return url
                params["tag"] = tag
                new_query = urlencode(params)
                return urlunparse(parsed._replace(query=new_query))

        # Allegro Partner Network / Convertiser wrapper
        if _host_in(hostname, "allegro.pl") and self.allegro_prefix:
            return f"{self.allegro_prefix}{quote(url, safe='')}"

        # Generic Awin / network template
        if self.awin_template and "{url}" in self.awin_template:
            return self.awin_template.format(url=quote(url, safe=""))

        return url

    def _wrapper_prefixes(self) -> tuple[str, ...]:
        prefixes = []
        if self.allegro_prefix:
            prefixes.append(self.allegro_prefix)
        if self.awin_template and "{url}" in self.awin_template:
            prefixes.append(self.awin_template.split("{url}", 1)[0])
        return tuple(prefixes)
