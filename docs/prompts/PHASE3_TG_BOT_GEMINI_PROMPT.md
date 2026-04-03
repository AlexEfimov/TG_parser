# Session: Phase 3 — Gemini TG Bot Implementation

## Purpose of this session

Implement the Phase 3 Telegram bot as described in `docs/notes/PHASE3_IMPLEMENTATION_PLAN.md`.

This is an **implementation session**. The plan is already agreed.

**Branch:** `feature/phase3-tg-bot` — all Phase 3 commits go here.

---

## Baseline: what is already done

- **Phase 1-2 complete**: TG_parser runs on a remote server; REST API, MCP (Streamable HTTP + bearer auth), PostgreSQL, Grafana/Prometheus, Nginx TLS, backups, Telegram user session on server.
- **MCP** is reachable at `https://mcp.tgp.efimov.mobi/mcp` (and from Docker network as `mcp:8080`).
- **17 MCP tools** already implemented in `tg_parser/mcp_server.py`.
- **Gemini** is already supported in the codebase as an LLM provider via `GEMINI_API_KEY`.
- Architecture reference: `docs/SERVER_ARCHITECTURE.md`.
- Master strategy: `.cursor/plans/tg_parser_go-live_strategy_d15ac21a.plan.md`.

---

## Agreed decisions

- **LLM backend:** Gemini (`GEMINI_API_KEY`)
- **Deployment:** new `tg_bot` service in `docker-compose.yml`
- **Bot framework:** `aiogram`
- **Access:** allowlist-only
- **Telegram updates:** long polling
- **Architecture:** agent/orchestrator layer over internal services (NOT just `retrieval_service.answer()`)
- **UX:** free-form chat, structured-first answers, source-backed responses

---

## What to implement (V1.0 — Agentic read-heavy MVP)

### Agent / Orchestrator layer

The core of the bot is an **agent layer** that uses Gemini for reasoning and tool selection. It receives a free-form user message and decides which internal capabilities to invoke.

V1.0 capabilities (read-only, matching existing MCP tools internally):

| Capability | Internal service | MCP tool equivalent |
|------------|-----------------|---------------------|
| Q&A | `retrieval_service.answer()` | `ask_question` |
| Search | `retrieval_service.search()` | `search_knowledge_base` |
| List topics | topic repo queries | `list_topics` |
| Topic details | topic repo + bundle | `get_topic_details` |
| List channels | channel repo | `list_channels` |
| Get document | processed doc repo | `get_document` |
| Related topics | topic link repo | `get_related_topics` |
| Cross-channel stats | analytics service | `get_cross_channel_stats` |

The agent should use Gemini function-calling / tool-use to select the right capability based on the user's message.

### Response formatter

All responses should be **structured**:
- Summary / key finding
- Key points (bullet list)
- Sources / references (when applicable)
- Split into multiple Telegram messages if > 4096 chars

### Aiogram handlers

- `/start` — greeting and capabilities description
- `/help` — what the bot can do, known limitations
- Text messages — route through agent layer
- Allowlist middleware — reject unknown users
- Rate limiting middleware
- Logging middleware — `telegram_user_id`, `request_id`

### Settings and env

New fields in `tg_parser/config/settings.py`:
- `TELEGRAM_BOT_TOKEN`
- `BOT_ALLOWED_USERS` — comma-separated list of Telegram user IDs
- `BOT_REQUEST_TIMEOUT`
- `BOT_MAX_MESSAGE_LENGTH`
- `BOT_RATE_LIMIT`

### CLI entrypoint

Add `tg-parser bot` command in `tg_parser/cli/app.py`.

### Docker service

Add `tg_bot` service in `docker-compose.yml`:
- Same image as `tg_parser`
- `command: bot`
- `depends_on: postgres`
- `restart: unless-stopped`
- Network: `tg_parser_network`
- Env: `LLM_PROVIDER=gemini`, `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, bot-specific vars

### Documentation

- `.env.example` — new bot section
- `env.production.example` — new bot section
- `PRODUCTION_DEPLOYMENT.md` — Phase 3 subsection

---

## Reference files in repo

- `docker-compose.yml` — add `tg_bot` service
- `tg_parser/mcp_server.py` — reference for tool signatures and internal service calls
- `tg_parser/services/retrieval_service.py` — search and answer
- `tg_parser/services/analytics_service.py` — cross-channel stats
- `tg_parser/config/settings.py` — add bot settings
- `tg_parser/cli/app.py` — add bot CLI command
- `pyproject.toml` — add `aiogram` dependency
- `PRODUCTION_DEPLOYMENT.md` — add Phase 3 docs

---

## Instruction for the AI assistant

> Read this file and `docs/notes/PHASE3_IMPLEMENTATION_PLAN.md` fully. Implement V1.0 of the Telegram bot: agent/orchestrator layer with Gemini tool-calling, aiogram handlers, settings, CLI entrypoint, docker-compose service, and documentation updates. Use `tg_parser/mcp_server.py` as a reference for how internal services are called (but do NOT route through MCP protocol — call services directly). Do not expand scope beyond V1.0 read-only capabilities.
