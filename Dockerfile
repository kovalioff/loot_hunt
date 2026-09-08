FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY loot_hunt ./loot_hunt
RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm
RUN groupadd --system loot && useradd --system --gid loot --home-dir /app loot
WORKDIR /app
COPY --from=builder --chown=loot:loot /app /app
RUN mkdir -p /data && chown loot:loot /data
USER loot
ENV PATH="/app/.venv/bin:$PATH" DATABASE_PATH=/data/loot_hunt.db PYTHONUNBUFFERED=1
VOLUME ["/data"]
CMD ["python", "-m", "loot_hunt.main"]
