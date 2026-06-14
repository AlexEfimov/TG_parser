# Multi-stage build for TG_parser
# D2: Production-ready Docker image
#
# Dependency reproducibility (#295, Phase 2): the builder installs the exact,
# hash-pinned set resolved in uv.lock via `uv sync --frozen` (no resolver
# freedom). `--frozen` fails the build if uv.lock is stale vs pyproject.toml,
# so a clean rebuild can never silently pull a newer transitive (e.g. the
# fastapi 0.137 / instrumentator 8.0.0 incident). uv.lock MUST be in the build
# context (it was removed from .dockerignore).

# ---------------------------------------------------------------------------
# Builder stage — install dependencies from the lockfile (uv-native)
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /uvx /bin/

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

ENV UV_LINK_MODE=copy \
    UV_PYTHON=3.12 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# Layer 1: deps only (cached unless pyproject.toml/uv.lock change) — NO project
# code yet, so a code-only change does not re-run the expensive dep install.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Layer 2: project source + install the package itself (changes often).
COPY tg_parser/ ./tg_parser/
COPY prompts/ ./prompts/
RUN uv sync --frozen --no-dev --no-editable

# ---------------------------------------------------------------------------
# Production stage — minimal runtime image (carries only the resolved venv)
# ---------------------------------------------------------------------------
FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

COPY tg_parser/ ./tg_parser/
COPY prompts/ ./prompts/
COPY migrations/ ./migrations/

RUN mkdir -p /app/data

ENTRYPOINT ["tg-parser"]
CMD ["api", "--host", "0.0.0.0", "--port", "8000"]
