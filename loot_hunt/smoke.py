from __future__ import annotations

import argparse
import asyncio
import json

from .config import Settings
from .pepper.client import PepperClient
from .search.planner import SearchPlanner


async def smoke(kind: str, value: str) -> None:
    settings = Settings.from_env()
    pepper = PepperClient(timeout=settings.pepper_timeout_seconds)
    try:
        if kind == "search":
            offers = await pepper.search(value)
            print(f"active_offers={len(offers)}")
            for item in offers[:5]:
                enriched = await pepper.enrich(item)
                print(json.dumps(enriched.to_dict(), ensure_ascii=True))
        elif kind == "category":
            catalog = await pepper.category_catalog()
            print(f"parents={len(catalog)} children={sum(len(item.children) for item in catalog)}")
            offers = await pepper.category(value)
            print(f"active_offers={len(offers)}")
        elif kind == "detail":
            offer = await pepper.details(value)
            print(offer.to_dict() if offer else "detail_not_found")
        else:
            plan = await SearchPlanner(settings.gemini_api_key).plan(value)
            print(plan.model_dump_json(indent=2))
    finally:
        await pepper.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Optional live Loot Hunt smoke tests")
    parser.add_argument("kind", choices=("search", "category", "detail", "gemini"))
    parser.add_argument("value")
    args = parser.parse_args()
    asyncio.run(smoke(args.kind, args.value))
