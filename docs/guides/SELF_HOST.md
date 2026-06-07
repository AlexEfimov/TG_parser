# Self-Host — Operator Checklist

**Version:** 4.4.0 | **Audience:** operators deploying their own TG_parser instance

Numbered checklist for a fresh install. For hosted validators (Wave 1.5 Track B/C), you do **not** need this — see [GETTING_STARTED.md](../GETTING_STARTED.md).

Full detail: [README.md](../../README.md), [PRODUCTION_DEPLOYMENT.md](../../PRODUCTION_DEPLOYMENT.md).

---

## Prerequisites

- [ ] Docker 24+ and Docker Compose v2 **or** Python 3.12 + PostgreSQL 17 + pgvector
- [ ] Telegram API credentials from https://my.telegram.org/apps
- [ ] At least one LLM API key (OpenAI recommended — also used for embeddings by default)
- [ ] Optional: `@BotFather` token for bot profile; domain for TLS

---

## Docker Compose path (recommended)

### 1. Clone and configure

```bash
git clone <repo-url>
cd TG_parser
cp .env.example .env
# Edit .env — set DB_PASSWORD, TELEGRAM_*, LLM keys
```

### 2. Create external Postgres volume

```bash
docker volume create tg_parser_pgvector17_data
```

### 3. Start stack

```bash
docker compose up -d --build
```

Default stack: `postgres`, `tg_parser` (API + scheduler), `mcp`, `prometheus`, `grafana`.

Optional profiles:

```bash
docker compose --profile bot up -d        # Telegram bot
docker compose --profile production up -d # Caddy TLS reverse proxy
docker compose --profile ollama up -d     # Local Ollama LLM
```

### 4. Initialize database (required)

Migrations are **not** auto-applied on container start:

```bash
docker compose run --rm tg_parser init
# equivalent:
docker compose run --rm tg_parser db upgrade --db all
```

### 5. Telegram authorization (interactive)

```bash
mkdir -p data/sessions
docker compose run --rm tg_parser auth
# Enter OTP from Telegram app
```

### 6. Multi-tenancy (if using MCP auth)

```bash
docker compose run --rm tg_parser migrate-users --dry-run
docker compose run --rm tg_parser migrate-users
```

Set in `.env`:

```env
MCP_AUTH_ENABLED=true
MCP_AUTH_TOKENS='{"your-token":"admin"}'
API_KEY_REQUIRED=true
API_KEYS='{"your-api-key":"admin"}'
```

### 7. Add first channel

```bash
docker compose run --rm tg_parser add-source --source-id mychan --channel-id @public_channel
docker compose run --rm tg_parser run --source mychan --out ./output
```

Or via MCP: `add_channel` → `trigger_pipeline`.

---

## Local venv path

### 1. Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env
```

### 2. Database

```bash
docker compose up -d postgres
# .env on host:
# DB_HOST=localhost
# DB_PORT=5432
tg-parser init
```

> **DB_HOST:** use `localhost` for host CLI; Docker services use `postgres` internally (see [GETTING_STARTED.md](../GETTING_STARTED.md)).

### 3. Auth and run

```bash
tg-parser auth
tg-parser add-source --source-id mychan --channel-id @channel
tg-parser run --source mychan --out ./output
```

---

## Smoke test

- [ ] `curl http://localhost:8000/health` → 200
- [ ] MCP `whoami` or `curl` with bearer token
- [ ] `list_channels` shows added source
- [ ] `ask_question` returns results after pipeline

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| API restart loop | Check `DB_HOST=postgres` inside compose; `DB_PASSWORD` set |
| MCP healthy, API unhealthy | Run `init` / `db upgrade --db all` |
| Empty search results | Pipeline not run; `trigger_pipeline` or wait for scheduler |
| Telethon auth fails | `docker compose run --rm tg_parser auth --force` |

See [USER_GUIDE.md](../USER_GUIDE.md) § Troubleshooting.

---

## Wave 1.5 note

Self-host validators are optional (0–1 power user). Log install friction with tag `[track-selfhost]` per [WAVE1_5_VALIDATOR_ONBOARD.md](../runbooks/WAVE1_5_VALIDATOR_ONBOARD.md).
