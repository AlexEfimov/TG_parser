# Server Architecture — Production Deployment

**Server**: `redboxtgbot` — Ubuntu 24.04.4 LTS  
**IP**: `212.72.189.15` (SSH port `2296`)  
**Domain**: `efimov.mobi`  
**Deployed**: 2026-04-02  

---

## Network Topology

```
Internet
  │
  ├── :80/:443 ── Nginx on host (TLS termination, reverse proxy)
  │                 ├── tgp.efimov.mobi        → 127.0.0.1:8000  (tg_parser API)
  │                 ├── mcp.tgp.efimov.mobi    → 127.0.0.1:8080  (MCP Server)
  │                 ├── grafana.tgp.efimov.mobi → 127.0.0.1:3001  (Grafana)
  │                 ├── flowise.efimov.mobi     → (pre-existing)
  │                 ├── n8n.efimov.mobi         → (pre-existing)
  │                 └── hooks.efimov.mobi       → (pre-existing)
  │
  └── :2296 ── SSH

Docker network: tg_parser_network (bridge)
  │
  ├── tg_parser        :8000  → 127.0.0.1:8000  (REST API + Background Scheduler)
  ├── tg_parser_mcp    :8080  → 127.0.0.1:8080  (MCP Streamable HTTP)
  ├── tg_parser_bot    (no port, long polling)    (Telegram Bot — profile: bot)
  ├── tg_parser_postgres:5432 → 127.0.0.1:5432  (PostgreSQL 17 + pgvector)
  ├── tg_parser_prometheus:9090 (internal only, no host port)
  └── tg_parser_grafana :3000 → 127.0.0.1:3001  (Grafana)
```

All service ports bound to `127.0.0.1` — not accessible from internet.  
Only Nginx (:80/:443) is public-facing.

---

## Services

### PostgreSQL 17 + pgvector
- **Container**: `tg_parser_postgres`
- **Image**: `pgvector/pgvector:pg17`
- **Volume**: `tg_parser_pgvector17_data` (external, pre-created)
- **Database**: `tg_parser`
- **User**: `tg_parser_user`
- **Healthcheck**: `pg_isready`

### TG_parser API + Scheduler
- **Container**: `tg_parser`
- **Image**: `tg_parser:latest` (built from Dockerfile)
- **Port**: `127.0.0.1:8000`
- **URL**: `https://tgp.efimov.mobi`
- **Healthcheck**: `GET /health`
- **Volumes**: `./data`, `./.env`, `./prompts`, `./data/sessions`
- **Includes**: REST API, background APScheduler for incremental pipeline
- **LLM**: Anthropic (Haiku for processing, Sonnet for topicization)

### MCP Server
- **Container**: `tg_parser_mcp`
- **Image**: `tg_parser:latest`
- **Port**: `127.0.0.1:8080`
- **URL**: `https://mcp.tgp.efimov.mobi/mcp`
- **Transport**: Streamable HTTP (`stateless_http=True`, `json_response=True`)
- **Auth**: Bearer token (configured via `MCP_AUTH_TOKENS`)
- **Healthcheck**: `GET /health` (returns 200 for liveness, DB status informational)
- **Endpoints**:
  - `/mcp` — MCP protocol (JSON-RPC)
  - `/health` — liveness check
  - `/metrics` — Prometheus metrics
- **Tools** (17):
  - `search_knowledge_base` — semantic search
  - `ask_question` — RAG Q&A
  - `list_topics` / `get_topic_details` — topic navigation
  - `list_channels` — channel overview
  - `get_document` — full document content
  - `get_related_topics` — cross-channel topic links
  - `get_cross_channel_stats` — analytics
  - `add_channel` / `pause_channel` / `resume_channel` / `remove_channel` — channel management
  - `trigger_pipeline` / `get_pipeline_status` — pipeline control
  - `get_llm_config` / `set_llm_config` / `reset_llm_config` — runtime LLM provider/model (no restart)

### Telegram Bot (V1.2 — Full Operational Interface)
- **Container**: `tg_parser_bot`
- **Image**: `tg_parser:latest`
- **Port**: none (long polling, no inbound connections)
- **Profile**: `bot` (start with `--profile bot` or `COMPOSE_PROFILES=bot`)
- **Command**: `tg-parser bot`
- **Healthcheck**: `pgrep -f 'tg-parser bot'`
- **Env vars**: `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`, `BOT_ALLOWED_USERS`, `BOT_GEMINI_MODEL`, `BOT_RATE_LIMIT`, `BOT_REQUEST_TIMEOUT`
- **LLM**: Gemini for agent reasoning/tool-calling; OpenAI for embeddings (search/RAG); Anthropic optional (processing if configured via per-stage overrides)
- **Capabilities** (24 tools):
  - Read: Q&A, search, topics, channels, documents, related topics, cross-channel analytics, pipeline status
  - Write (two-phase confirmation): trigger pipeline, pause/resume channel, add/remove channel, set/reset LLM config
- **Security**: allowlist-only (`BOT_ALLOWED_USERS`), per-user rate limiting, two-phase confirmation for all write operations, explicit irreversibility warning for `remove_channel`

### Prometheus
- **Container**: `tg_parser_prometheus`
- **Image**: `prom/prometheus:v2.53.0`
- **Port**: internal only (9090, no host mapping)
- **Retention**: 30 days
- **Scrape targets** (per `docker/prometheus.yml` `scrape_configs`):
  - `tg_parser:8000/metrics` — job `tg_parser_api`, label `service: api`
  - `mcp:8080/metrics` — job `tg_parser_mcp`, label `service: mcp`
  - `tg_bot:8081/metrics` — job `tg_parser_bot`, label `service: bot`
    (added Session F, TD-bot-prometheus-scrape close commit `ec52060`;
    required for `tg_bot_gemini_empty_parts_total` Session E / BUG-006
    post-deploy watch via Prometheus query path; container runs on
    `--profile bot`)
- **Config**: `docker/prometheus.yml`

### Grafana
- **Container**: `tg_parser_grafana`
- **Image**: `grafana/grafana:11.1.0`
- **Port**: `127.0.0.1:3001` (remapped from default 3000 — port conflict with pre-existing service)
- **URL**: `https://grafana.tgp.efimov.mobi`
- **Admin**: `admin` / (see `.env`)
- **Datasource**: Prometheus (auto-provisioned, UID: `prometheus`)
- **Dashboards** (auto-provisioned):
  - **System**: HTTP request rate, error rate, latency percentiles, DB pool, active jobs
  - **Pipeline**: Messages processed, topics created, LLM requests/duration/tokens, scheduler tasks

### Caddy (optional — not used on this server)
- Defined in `docker-compose.yml` under `profiles: [production]`.
- On **this** host, TLS is done by **Nginx** (pre-existing); the Caddy service is not started.
- For a greenfield deploy without host Nginx, use `docker compose --profile production up -d` and set `DOMAIN_MCP`, `DOMAIN_API`, `DOMAIN_GRAFANA` in `.env` — see `PRODUCTION_DEPLOYMENT.md` (SSL/TLS → Option A).

---

## Nginx Configuration

Host **Nginx** (not the optional Docker Caddy). Three site configs in `/etc/nginx/sites-enabled/`:

### tgp-api (`tgp.efimov.mobi`)
- Proxies to `127.0.0.1:8000`
- Blocks `/metrics` (returns 403)
- TLS via Let's Encrypt (certbot)

### tgp-mcp (`mcp.tgp.efimov.mobi`)
- Proxies to `127.0.0.1:8080`
- WebSocket/SSE support (`Upgrade`, `Connection` headers)
- `proxy_read_timeout 300s` (long-running MCP requests)
- TLS via Let's Encrypt

### tgp-grafana (`grafana.tgp.efimov.mobi`)
- Proxies to `127.0.0.1:3001`
- WebSocket support (Grafana live)
- TLS via Let's Encrypt

**Certificate**: `/etc/letsencrypt/live/tgp.efimov.mobi/` (expires 2026-07-01, auto-renewal via certbot timer)

---

## TLS & Security

- All TLS via **Let's Encrypt** (certbot + nginx plugin, auto-renewal)
- Service ports bound to **127.0.0.1** — no direct internet access to Docker services
- `/metrics` endpoints blocked from public access (Nginx returns 403 for API)
- MCP requires **Bearer token** authentication
- Grafana sign-up disabled (`GF_USERS_ALLOW_SIGN_UP=false`)
- PostgreSQL accessible only within Docker network + localhost

---

## MCP Client Connections

### Cursor IDE
- **Config**: `~/.cursor/mcp.json`
- **Type**: `http` (direct Streamable HTTP)
- **URL**: `https://mcp.tgp.efimov.mobi/mcp`
- **Auth**: Bearer token in `Authorization` header

### Claude Desktop
- **Config**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Type**: `stdio` via `npx mcp-remote` (proxy bridge)
- **Reason**: Claude Desktop v1.2.x doesn't support remote HTTP MCP in config
- **Command**: `npx -y mcp-remote https://mcp.tgp.efimov.mobi/mcp --header "Authorization: Bearer ..."`

---

## Monitoring & Metrics

### Prometheus Metrics (wired)
- **HTTP**: request rate, latency percentiles, error rate, in-progress requests (via `prometheus-fastapi-instrumentator`)
- **LLM**: request count, duration, input/output tokens per provider/model (via `InstrumentedLLMClient`)
- **Pipeline**: messages processed (success/error), topics created
- **Scheduler**: task executions (success/error)

### Not yet wired
- `record_agent_task` — agent orchestration metrics (secondary processing path, low priority)

---

## Backup & Operations

### Database Backup
- **Script**: `docker/backup.sh`
- **Schedule**: cron `0 2 * * *` (daily at 02:00)
- **Location**: `~/TG_parser/data/backups/`
- **Retention**: 7 days (automatic rotation)
- **Log**: `/var/log/tg_parser_backup.log`

### Telegram Session
- **File**: `data/sessions/tg_parser_session.session`
- **Auth**: `docker compose run --rm tg_parser auth` (interactive)
- **Persisted** via bind mount to host filesystem

### Updating
```bash
cd ~/TG_parser
git pull
docker compose up -d --build
# If Caddy profile needed: docker compose --profile production up -d --build
```

---

## Filesystem Layout (Server)

```
~/TG_parser/
├── .env                     # Production secrets (not in git)
├── docker-compose.yml       # Service definitions
├── Dockerfile               # App image
├── docker/
│   ├── Caddyfile            # Caddy config (use with compose profile production; Nginx used on this host)
│   ├── prometheus.yml       # Prometheus scrape config
│   ├── grafana/
│   │   ├── provisioning/    # Datasource + dashboard auto-provisioning
│   │   └── dashboards/      # system.json, pipeline.json
│   ├── backup.sh            # DB backup script
│   └── init-db.sh           # PostgreSQL init (pgvector extension)
├── data/
│   ├── sessions/            # Telegram session files
│   └── backups/             # Daily DB backups
├── prompts/                 # LLM prompt templates
└── tg_parser/               # Application source code
```

---

## Resource Usage

| Resource | Value |
|---|---|
| Disk total | 19 GB |
| Disk used | ~10 GB (57%) |
| RAM total | 3.8 GB |
| RAM available | ~2.6 GB |
| Docker containers | 5 running |
| Docker volumes | 6 (postgres, prometheus, grafana, caddy x2, ollama) |
