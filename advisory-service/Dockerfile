# syntax=docker/dockerfile:1
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=0 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install uv (pinned via official image binary)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 1. Install dependencies first (better layer caching).
#    README.md is required by `uv_build` (project readme).
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# 2. Copy application source, models, and env files, then install the project itself.
COPY src ./src
COPY models ./models
COPY .env.dev ./.env.dev
COPY .env.prod ./.env.prod
COPY .env.docker ./.env.docker
RUN uv sync --frozen --no-dev

# 3. Runtime hardening + writable dirs for the file log handler (logs/*.log) and csv export.
RUN useradd -m -u 10001 appuser \
    && mkdir -p logs raw_data \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Single worker on purpose: lifespan starts an AsyncIOScheduler, which would
# duplicate jobs under multiple workers. Scale via replicas, not workers.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "__import__('urllib.request', fromlist=['urlopen']).urlopen('http://127.0.0.1:8000/api/v1/advisory/ping', timeout=4)"

CMD ["fastapi", "run", "src/advisory_service/__init__.py", "--host", "0.0.0.0", "--port", "8000"]
