# Multi-stage build for TG_parser
# D2: Production-ready Docker image

# ---------------------------------------------------------------------------
# Builder stage — install dependencies from pyproject.toml
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY tg_parser/ ./tg_parser/
COPY prompts/ ./prompts/

RUN pip install --user --no-cache-dir .

# ---------------------------------------------------------------------------
# Production stage — minimal runtime image
# ---------------------------------------------------------------------------
FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

COPY tg_parser/ ./tg_parser/
COPY prompts/ ./prompts/

RUN mkdir -p /app/data

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["tg-parser"]
CMD ["api", "--host", "0.0.0.0", "--port", "8000"]
