from __future__ import annotations

import os
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse


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

        # Amazon Associates
        if "amazon." in hostname or hostname.endswith("amzn.to"):
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
                params["tag"] = tag
                new_query = urlencode(params)
                return urlunparse(parsed._replace(query=new_query))

        # Allegro Partner Network / Convertiser wrapper
        if (hostname.endswith("allegro.pl") or hostname == "allegro.pl") and self.allegro_prefix:
            return f"{self.allegro_prefix}{quote(url, safe='')}"

        # Generic Awin / network template
        if self.awin_template and "{url}" in self.awin_template:
            return self.awin_template.format(url=quote(url, safe=""))

        return url
