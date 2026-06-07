# Getting Started — TG_parser (Wave 1.5)

**Version:** 4.4.0 | **Updated:** June 2026

TG_parser turns Telegram channels into a searchable knowledge base with RAG Q&A, digests, and watchlist alerts. This guide helps you pick the right entry path.

> **Hosted instance?** Your admin sends a personal link or token. Replace `{MCP_URL}`, `{BOT_USERNAME}`, and `{DIGEST_CHANNEL}` below with values from that message.

---

## Choose your path

| | **Track B — MCP curator** | **Track C — Digest consumer** | **Self-host** |
|---|---|---|---|
| **For** | Cursor / Claude users who want their own KB | Readers who want scheduled summaries | Operators deploying their own stack |
| **You need** | MCP bearer token from admin | Telegram only (C1) or bot access (C2) | Server, Telegram API, LLM keys |
| **Channels** | **Your own** (you add via MCP) | **Admin's curated** KB (read-only) | Your own |
| **Setup time** | ~15 min (+ pipeline wait) | ~2 min (subscribe) | Hours |
| **Guide** | [MCP_CONNECT.md](guides/MCP_CONNECT.md) | [DIGEST_CONSUMER.md](guides/DIGEST_CONSUMER.md) | [SELF_HOST.md](guides/SELF_HOST.md) |

```text
"I want to build my own KB with AI tools"     → Track B
"I want to read curated digests"            → Track C
"I want to run everything on my server"     → Self-host
```

---

## Track B — MCP curator (own channels)

**What you get:** connect TG_parser to Cursor, Claude Desktop, or Claude Code; add **your** Telegram channels; search and ask questions over **your** processed content.

**What you do NOT get:** access to the operator's existing production channels or their curated digest sources. Those are isolated by design (multi-tenancy).

### Quick flow

1. Receive MCP token from admin (out-of-band).
2. Follow [MCP_CONNECT.md](guides/MCP_CONNECT.md) — configure client, run smoke test (`whoami`).
3. Call `add_channel` with a **public** channel (or one the server Telegram account can join).
4. Wait for processing — check `get_pipeline_status` until `last_success_at` is set (typically 5–30 min), or ask admin to run `trigger_pipeline`.
5. Try `ask_question` or `search_knowledge_base`.

### Important limits (hosted)

- Ingestion uses the **server's** Telegram account — private channels without access fail silently or show errors in pipeline status.
- After `add_channel`, the KB is **empty** until the pipeline processes messages (cold start).
- Default limit: **3 channels** per user (`max_channels` set by admin).

### Can / cannot (Track B)

| Can | Cannot |
|-----|--------|
| `add_channel`, `pause_channel`, `remove_channel` (own) | See or query admin's prod channels |
| `ask_question`, `search_knowledge_base` (own KB) | `subscribe_digest` on admin's channel_ids |
| `trigger_pipeline`, `get_pipeline_status` (own) | Change LLM config (`admin` only) |
| `subscribe_watchlist`, workspaces (own channels) | Install software / change server config |

---

## Track C — Digest consumer (read-only)

**What you get:** scheduled LLM summaries from the operator's curated knowledge base — no MCP, no install.

**Sub-paths:**

| | **C1 — Public digest channel** (default) | **C2 — Private DM** |
|---|---|---|
| **Setup** | Subscribe to `{DIGEST_CHANNEL}` in Telegram | `/start` the bot; admin registers you |
| **Registration** | None | Admin creates your Telegram auth mapping |
| **Guide** | [DIGEST_CONSUMER.md](guides/DIGEST_CONSUMER.md) § C1 | [DIGEST_CONSUMER.md](guides/DIGEST_CONSUMER.md) § C2 + [BOT_USER.md](guides/BOT_USER.md) |

**Timing:** subscribing to a channel is instant; the **first digest** arrives on the next cron tick (e.g. daily 09:00 UTC — admin tells you the schedule).

---

## Self-host (operators)

Deploy your own instance: Docker Compose or local venv. See [SELF_HOST.md](guides/SELF_HOST.md) for the numbered checklist.

For full reference after install: [USER_GUIDE.md](USER_GUIDE.md), [PRODUCTION_DEPLOYMENT.md](../PRODUCTION_DEPLOYMENT.md), [ENV_VARIABLES_GUIDE.md](../ENV_VARIABLES_GUIDE.md).

---

## DB_HOST note (self-host / Docker)

| Context | `DB_HOST` value |
|---------|-----------------|
| CLI on host machine (`tg-parser …` locally) | `localhost` |
| Inside Docker Compose services | `postgres` (set automatically in compose; do not override in service env) |

Wrong `DB_HOST` in `.env` when running CLI on the host while Postgres runs in Docker → connection errors. Use `localhost` + published port `5432`.

---

## More documentation

| Doc | Purpose |
|-----|---------|
| [USER_GUIDE.md](USER_GUIDE.md) | Full feature reference |
| [MCP_AGENT_GUIDE.md](MCP_AGENT_GUIDE.md) | All 43 MCP tools (for agents) |
| [mcp-clients-compatibility.md](mcp-clients-compatibility.md) | Client compatibility matrix |
| [CHANGELOG.md](../CHANGELOG.md) | Release history |

**Internal dev notes** (`docs/notes/`) are for project maintainers — not required for end users.

---

## Feedback (Wave 1.5 validators)

Send friction observations to your admin in free text — no forms. Examples: «couldn't connect MCP», «digest was empty», «wanted to see full article».
