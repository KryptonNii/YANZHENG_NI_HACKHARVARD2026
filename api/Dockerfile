# syntax=docker/dockerfile:1.7
# TrialPilot — ONE image: FastAPI under /api + the built web app at /. Build context = repo root.
#
#   docker compose up --build                              (root docker-compose.yml, port 127.0.0.1:8000)
#   docker build -f api/Dockerfile -t trialpilot .         (the ignore file is api/Dockerfile.dockerignore)
#   docker run --rm -p 127.0.0.1:8000:8000 -v tp-data:/data trialpilot
#
# Runs live by default; DEMO_OFFLINE=1 explicitly selects cached fixtures. SQLite lives in /data.

# ---------------------------------------------------------------- 1. web (React + Vite) build
FROM node:20-bookworm-slim AS web
WORKDIR /src/web
RUN corepack enable && corepack prepare pnpm@9.15.9 --activate
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
# The command center bundles two fixtures from outside web/ (src/features/command/lockStory.ts).
COPY data/fixtures/ops/lock_recovery_evidence.json data/fixtures/ops/lock_recovery_story.json /src/data/fixtures/ops/
# `vite build` only (the type check runs in CI, `pnpm build` = tsc -b && vite build).
RUN pnpm exec vite build

# ---------------------------------------------------------------- 2. Python API
FROM python:3.12-slim-bookworm AS app
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/api/.venv \
    PYTHONUNBUFFERED=1
WORKDIR /app

# Dependencies first (cached unless a manifest or lock changes).
COPY contracts/pyproject.toml contracts/
COPY engine/pyproject.toml engine/
COPY api/pyproject.toml api/uv.lock api/
RUN mkdir -p contracts/trialpilot_contracts engine/trialpilot_engine api/trialpilot_api \
 && touch contracts/trialpilot_contracts/__init__.py engine/trialpilot_engine/__init__.py \
          api/trialpilot_api/__init__.py \
 && uv sync --project api --frozen --no-dev

# Sources + data (filtered by api/Dockerfile.dockerignore), then the built web app.
COPY . .
RUN uv sync --project api --frozen --no-dev
COPY --from=web /src/web/dist /app/web/dist

RUN useradd --create-home --uid 1000 tp \
 && mkdir -p /data /app/var \
 && chown -R tp:tp /data /app/var
USER tp

ENV TP_REPO_ROOT=/app \
    TP_DATA_DIR=/data \
    DEMO_OFFLINE=0 \
    TP_LOG_JSON=1 \
    PATH="/app/api/.venv/bin:${PATH}"
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"

# Seed (idempotent: DB schema, parameter library, fixture designs) then serve.
CMD ["sh", "-c", "python -m trialpilot_api.seed; exec uvicorn trialpilot_api.main:app --host 0.0.0.0 --port 8000"]
