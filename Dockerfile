# middler — runs on a Raspberry Pi 5 (arm64) or any amd64 host.
# Base image ships uv + Python 3.13. Only core deps are installed (alert-only);
# the heavy `embed`/`betfair` extras are added later, on the host, when needed.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# Install dependencies first (cached unless the lockfile changes).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Then the application code.
COPY middler ./middler
COPY config.yaml ./
RUN uv sync --frozen --no-dev && mkdir -p data logs reports

# The healthcheck proves the process can open its database.
HEALTHCHECK --interval=5m --timeout=30s --retries=3 --start-period=90s CMD uv run middler-healthcheck || exit 1

CMD ["uv", "run", "middler"]
