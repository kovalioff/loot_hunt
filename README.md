# Loot Hunt

Loot Hunt is a Russian-language Telegram bot for Russian-speaking expats in Poland. It finds and monitors deals on Pepper.pl (PL), Mydealz.de (DE), and HotUKDeals (UK), so a deal found abroad can be bought there and delivered to Poland.

The bot searches individual deal threads, shows fresh offers in deterministic order, links to the merchant when the platform exposes a real destination, and alerts only for newly discovered thread IDs.

## What it does

- **Search in plain Russian**: type “дешёвый монитор” or pick a live category. Without Gemini the bot uses a built-in Russian→Polish keyword map; with Gemini it additionally extracts hard constraints, soft concepts, and a `fresh`/`cheap`/`hot` sort mode.
- **Relative freshness**: “сегодня”, “со вчерашнего дня”, and “за неделю” are checked against each offer’s `published_at`; month and travel-date constraints are checked against the title and merchant URL.
- **Subscriptions**: a search or category can be watched. Re-tapping the watch button does not create a duplicate, paused subscriptions can be resumed, and Telegram-blocked users are paused automatically.
- **Batched notifications**: new offers for one subscription arrive in one message (split only when Telegram’s length limit requires it), with automatic retry on flood-control (`429`) responses.
- **Multi-region**: `/region` switches between Poland, Germany, and the United Kingdom. Category subscriptions remember the region they were created in.
- **Channel auto-publishing**: when `DEALS_CHANNEL_ID` is set, deals above `MIN_CHANNEL_TEMPERATURE` are posted to the channel once; published thread IDs are persisted so a restart does not repost them.
- **Growth loop**: `/ref` shows a personal invite link; each invited friend adds two subscription slots.

## Architecture

- `pepper/` uses a warmed `curl_cffi` browser-like session, parses current Vue listing state and `window.__INITIAL_STATE__`, and normalizes offers.
- `search/` gives Gemini one narrow job: turn one natural-language request into at most eight Polish search queries plus hard constraints, soft concepts, and a `fresh`/`cheap`/`hot` sort mode. Python performs bounded page-1/page-2 retrieval, optional sparse category fallback, deterministic scoring, deduplication, and ranking. Exact model tokens and explicit hard terms reject on mismatch; category, object, label, query, and soft-term matches add score. Deterministic (no-LLM) plans set `keyword_mode` and accept offers by query-token coverage, so a Polish title still matches without a category. Price bounds stay on the plan and are applied to offers instead of becoming hard constraints.
- `telegram/` provides five-offer pages, compact callback IDs, category browsing inside “Найти предложения”, merchant links on escaped store names, subscription controls, a batched notifier, and share links that point at the viewed deal plus the user’s referral link.
- `watch/` replays persisted search plans or category paths. It never has a planner dependency and therefore cannot call Gemini.
- SQLite stores offer cache, subscriptions, baseline/seen thread IDs, and short-lived search sessions. Subscriptions are unique per `(user, kind, source)`; duplicates from older databases are collapsed on startup. No comments, reviews, product identity, ratings, or price-history tables exist.

Pepper pages remain the live source of truth. A verified 15-parent snapshot is used if dynamic category navigation extraction is unavailable; the live page-state parser supports arbitrary nested category depth.

## Setup

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env
uv sync
uv run loot-hunt
```

Set `BOT_TOKEN`; `GEMINI_API_KEY` is optional. Without Gemini, or whenever Gemini fails, the deterministic planner maps the request to Polish queries and the search still works. Other useful settings are `BOT_USERNAME` (used in referral/share links; defaults to `loot_hunt_bot`), `DATABASE_PATH`, `WATCHER_INTERVAL_SECONDS` (default `3600`), `APP_TIMEZONE`, `LOG_LEVEL`, `DEALS_CHANNEL_ID`, `MIN_CHANNEL_TEMPERATURE`, and comma-separated `ADMIN_IDS`.

## Tests and live smoke checks

Default tests are fully offline and never call Gemini or Pepper:

```bash
uv run pytest -q
uv run ruff check .
```

CI runs the same checks on every push and pull request, then builds the Docker image.

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

## Monetization and privacy

Merchant links may be affiliate links (Amazon Associates, Awin, Allegro Partner Network). The
bot earns a commission on qualifying purchases; the price is the same for the user. The
disclosure is also shown in `/start` and `/help`.

The bot stores a Telegram user ID, search queries, subscriptions, and a short-lived offer/session
cache — only what is needed to run searches and notifications. It does not store message history.
Deleting a subscription removes the tracked search; expired sessions are purged automatically, and
cached offers that were not seen for 30 days are deleted.

## Docker

```bash
docker compose up --build -d
```

The image runs as a non-root user, reads secrets only from the environment, persists SQLite in the `loot-hunt-data` volume, and handles normal container termination through asyncio shutdown.
