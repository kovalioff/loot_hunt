# Loot Hunt

Loot Hunt is a Russian-language Telegram bot that finds and monitors active Pepper.pl offers. It searches individual Pepper threads, shows fresh deals in deterministic order, links to the merchant when Pepper exposes a real destination, and alerts only for newly discovered thread IDs.

## Architecture

- `pepper/` uses a warmed `curl_cffi` browser-like session, parses current Vue listing state and `window.__INITIAL_STATE__`, and normalizes offers.
- `search/` gives Gemini one narrow job: turn one natural-language request into at most eight Polish Pepper search queries plus hard constraints, soft concepts, and a `fresh`/`cheap`/`hot` sort mode. Python performs bounded page-1/page-2 retrieval, optional sparse category fallback, deterministic scoring, deduplication, and ranking. Exact model tokens and explicit hard terms reject on mismatch; category, object, label, query, and soft-term matches add score. Adjacent unwanted content and compatibility-target wording are rejected without another AI call.
- `telegram/` provides five-offer pages, compact callback IDs, category browsing inside “Найти предложения”, merchant links on escaped store names, and subscription controls.
- `watch/` replays persisted search plans or category paths. It never has a planner dependency and therefore cannot call Gemini.
- SQLite stores offer cache, subscriptions, baseline/seen thread IDs, and short-lived search sessions. No comments, reviews, product identity, ratings, or price-history tables exist.

Pepper pages remain the live source of truth. A verified 15-parent snapshot is used if dynamic category navigation extraction is unavailable; the live page-state parser supports arbitrary nested category depth.

## Setup

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env
uv sync
uv run loot-hunt
```

Set `BOT_TOKEN`; `GEMINI_API_KEY` is optional. Without Gemini, or whenever Gemini fails, the original user text is sent directly to Pepper. Other useful settings are `DATABASE_PATH`, `WATCHER_INTERVAL_SECONDS` (default `3600`), `APP_TIMEZONE`, `LOG_LEVEL`, and comma-separated `ADMIN_IDS`.

## Tests and live smoke checks

Default tests are fully offline and never call Gemini or Pepper:

```bash
uv run pytest -q
uv run ruff check .
```

Optional manual checks (live network; Gemini only for the last command):

```bash
uv run loot-hunt-smoke search "Makita DDF484"
uv run loot-hunt-smoke category "/grupa/elektronika"
uv run loot-hunt-smoke detail "https://www.pepper.pl/promocje/example-123"
uv run loot-hunt-smoke gemini "ищу отдых в европе"
uv run loot-hunt-smoke explain "куда дешево слетать в сентябре"
```

`explain` prints the one-call plan, every Pepper query/page and count, candidate scores and
rejection reasons, final sort mode, and displayed offers. Retrieval is bounded to two search
pages per planned query, twelve Pepper listing requests, and 120 unique raw candidates.

## Docker

```bash
docker compose up --build -d
```

The image runs as a non-root user, reads secrets only from the environment, persists SQLite in the `loot-hunt-data` volume, and handles normal container termination through asyncio shutdown.
