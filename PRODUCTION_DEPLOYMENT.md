# Production Deployment Guide

**TG_parser v4.2 Production Deployment**

Complete guide for deploying TG_parser with PostgreSQL, REST API, and MCP server in production.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Architecture](#architecture)
- [Server Setup](#server-setup)
- [Application Deployment](#application-deployment)
- [Connecting AI Agents](#connecting-ai-agents)
- [SSL/TLS Configuration](#ssltls-configuration)
- [Monitoring](#monitoring)
- [Backup Strategy](#backup-strategy)
- [Troubleshooting](#troubleshooting)
- [Rollback Procedures](#rollback-procedures)
- [Maintenance](#maintenance)
- [Security Checklist](#security-checklist)

---

## Prerequisites

### Hardware Requirements

**Minimum:**
- CPU: 2 cores
- RAM: 4 GB
- Disk: 20 GB SSD
- Network: 100 Mbps

**Recommended (5+ channels):**
- CPU: 4+ cores
- RAM: 8+ GB
- Disk: 50+ GB SSD
- Network: 1 Gbps

### Software Requirements

- **OS**: Ubuntu 22.04 LTS (recommended) or any Docker-compatible Linux
- **Docker**: 24.0+
- **Docker Compose**: v2.0+
- **Domain**: Optional, for HTTPS setup
- **SSL Certificate**: Let's Encrypt (free, automated)

---

## Architecture

```
docker compose up -d starts 5 services (default, no profiles):

┌──────────────────────────────────────────────────────────────────────────┐
│                        Docker Compose Stack                              │
│                                                                          │
│  ┌───────────┐ ┌───────────┐ ┌─────────┐ ┌────────────┐ ┌───────────┐  │
│  │ postgres   │ │ tg_parser │ │  mcp    │ │ prometheus │ │  grafana  │  │
│  │ :5432      │ │ :8000     │ │ :8080   │ │ (internal) │ │ :3000     │  │
│  │ pgvector17 │ │ API +     │ │Streamble│ │ scrape     │ │ dashboards│  │
│  │            │ │ Scheduler │ │ HTTP    │ │ metrics    │ │           │  │
│  └─────┬──────┘ └─────┬─────┘ └────┬───┘ └─────┬──────┘ └─────┬─────┘  │
│        └──────────── tg_parser_network ─────────────────────────┘        │
└──────────────────────────────────────────────────────────────────────────┘

Profiles (optional add-ons):
  --profile bot         → tg_bot (Telegram Bot, long polling)
  --profile production  → caddy  (reverse proxy, auto-TLS)
  --profile ollama      → ollama (local LLM)

External access (localhost):
  HTTP clients     → :8000 (REST API, /docs, /metrics)
  AI agents        → :8080/mcp (MCP Streamable HTTP)
  Grafana          → :3000 (dashboards)
  CLI one-shot     → docker compose run tg_parser <command>
```

| Service | Port | Profiles | Purpose |
|---------|------|----------|---------|
| **postgres** | 5432 | default | PostgreSQL 17 + pgvector |
| **tg_parser** | 8000 | default | REST API + Background Scheduler |
| **mcp** | 8080 | default | MCP Server (Streamable HTTP for AI agents) |
| **prometheus** | — (internal) | default | Metrics collection |
| **grafana** | 3000 | default | Monitoring dashboards |
| **tg_bot** | — | `bot` | Telegram Bot (Gemini agent, long polling) |
| **caddy** | 80, 443 | `production` | Reverse proxy + auto-TLS |
| **ollama** | 11434 | `ollama` | Local LLM inference |

---

## Server Setup

### 1. Install Docker

```bash
sudo apt update && sudo apt upgrade -y

curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Install Docker Compose (v2)
sudo apt install docker-compose-plugin

docker --version
docker compose version
```

### 2. Configure Firewall

```bash
sudo ufw allow 22/tcp     # SSH
sudo ufw allow 8000/tcp   # API (or 80/443 if using reverse proxy)
sudo ufw allow 8080/tcp   # MCP Server
sudo ufw enable
```

### 3. Create Application Directory

```bash
sudo mkdir -p /opt/tg_parser
cd /opt/tg_parser
sudo chown $USER:$USER /opt/tg_parser
mkdir -p data/output data/archive
```

---

## Application Deployment

### Step 1: Clone Repository

```bash
cd /opt/tg_parser
git clone https://github.com/your-org/tg_parser.git .
```

### Step 2: Create PostgreSQL Volume

The PostgreSQL data is stored in an external Docker volume (survives `docker compose down -v`):

```bash
docker volume create tg_parser_pgvector17_data
```

### Step 3: Configure Environment

```bash
cp env.production.example .env
nano .env
```

**Critical settings to configure:**

```env
# Database
DB_HOST=postgres
DB_PASSWORD=CHANGE_THIS_TO_SECURE_PASSWORD_32_CHARS_MIN

# LLM Provider
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-proj-YOUR_KEY_HERE

# Telegram (for ingestion)
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=+1234567890

# API Security
API_KEY_REQUIRED=true
API_KEYS={"YOUR_API_KEY":"production"}

# MCP Security
MCP_AUTH_ENABLED=true
MCP_AUTH_TOKENS={"YOUR_MCP_TOKEN":"production_agent"}

# Logging
LOG_FORMAT=json
LOG_LEVEL=INFO
```

### Step 4: Build and Start

```bash
# Build images and start all services
docker compose up -d --build

# Check all services are running
docker compose ps

# Expected output (5 default services):
# tg_parser_postgres   running (healthy)
# tg_parser            running (healthy)
# tg_parser_mcp        running (healthy)
# tg_parser_prometheus running
# tg_parser_grafana    running
```

### Step 5: Verify Deployment

```bash
# Check API health
curl http://localhost:8000/health
# {"status": "ok", ...}

# Check detailed status
curl http://localhost:8000/status/detailed

# Check MCP is listening
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
# Should return 200

# Check Prometheus metrics
curl http://localhost:8000/metrics
```

### Step 5: Run Database Migrations (if upgrading)

```bash
docker compose exec tg_parser tg-parser db upgrade --db all
docker compose exec tg_parser tg-parser db current --db all
```

### Step 6: Telegram Authorization

Telegram requires an interactive one-time authorization (entering a confirmation code). This cannot be done via `docker compose up` (stdin is closed). Use `docker compose run` instead:

```bash
# 1. Create sessions directory on host
mkdir -p data/sessions

# 2. Run interactive auth (prompts for Telegram confirmation code)
docker compose run --rm tg_parser auth

# 3. Enter the code sent to your Telegram app
# Session file is saved to ./data/sessions/

# 4. Verify session was created
ls -la data/sessions/

# 5. Now ingestion works non-interactively
docker compose run --rm tg_parser ingest --source my_channel --limit 5
```

**Re-authorization** (expired session or changed phone):

```bash
docker compose run --rm tg_parser auth --force
```

The `--force` flag deletes the old session file before re-authenticating.

### Running CLI Commands

The `tg_parser` container can run any CLI command via `docker compose run`:

```bash
# List connected channels
docker compose run --rm tg_parser list-sources

# Add a new channel
docker compose run --rm tg_parser add-source --channel my_channel

# Run full pipeline
docker compose run --rm tg_parser run --source my_channel --out /app/data/output

# Trigger incremental processing
docker compose run --rm tg_parser process --channel my_channel
```

---

## Connecting AI Agents

### Claude Desktop

Add to `claude_desktop_config.json` (Settings > Connectors for remote servers):

**Local connection (stdio, server on same machine):**
```json
{
  "mcpServers": {
    "tg-parser": {
      "command": "docker",
      "args": ["compose", "run", "--rm", "tg_parser", "mcp"]
    }
  }
}
```

**Remote connection (Streamable HTTP):**

In Claude Desktop, go to Settings > Connectors and add:
- URL: `http://your-server:8080/mcp`
- Or with HTTPS: `https://your-domain.com/mcp`

If `MCP_AUTH_ENABLED=true`, include the bearer token in the connection settings.

### Claude Code

```bash
claude mcp add --transport http tg-parser http://your-server:8080/mcp \
  --header "Authorization: Bearer YOUR_MCP_TOKEN"
```

### Cursor

Add to `.cursor/mcp.json` in your project:

```json
{
  "mcpServers": {
    "tg-parser": {
      "url": "http://your-server:8080/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_TOKEN"
      }
    }
  }
}
```

### Available MCP Tools

| Tool | Description |
|------|-------------|
| `search_knowledge_base` | Semantic search across the knowledge base |
| `ask_question` | RAG Q&A with source citations |
| `list_topics` | Browse topic catalog |
| `get_topic_details` | Full topic card with bundle items |
| `list_channels` | Connected channels with statistics |
| `get_document` | Full document content |
| `add_channel` | Connect a new Telegram channel |
| `pause_channel` / `resume_channel` | Control channel processing |
| `remove_channel` | Permanently remove a channel and its data |
| `trigger_pipeline` | Start processing pipeline |
| `get_pipeline_status` | Check pipeline progress |
| `get_llm_config` | Current LLM provider/model per stage |
| `set_llm_config` | Switch LLM provider/model at runtime (no restart) |
| `reset_llm_config` | Revert runtime LLM overrides to `.env` defaults |

---

## SSL/TLS Configuration

The repository ships **Caddy** in `docker-compose.yml` (`profiles: [production]`). That is the path aligned with the compose file: one stack, automatic Let’s Encrypt.

Use **host Nginx** (or another edge proxy) when TLS and routing are already managed outside Docker — for example a shared server where API/MCP/Grafana are separate vhosts (see `docs/SERVER_ARCHITECTURE.md` for a real Nginx layout).

### Option A: Caddy (Docker Compose — recommended for greenfield)

1. Point DNS `A`/`AAAA` records for your three hostnames to this server’s public IP.

2. Add to `.env` (same variables as in `docker-compose.yml` for the `caddy` service):

```env
DOMAIN_MCP=mcp.example.com
DOMAIN_API=api.example.com
DOMAIN_GRAFANA=grafana.example.com
```

3. Open **80** and **443** (and **443/udp** for HTTP/3) on the host firewall — Caddy binds them inside the `caddy` container.

4. Start the production profile (builds app images if needed, starts Caddy with `docker/Caddyfile`):

```bash
docker compose --profile production up -d --build
```

Caddy terminates TLS and proxies:

| Hostname (env) | Upstream service |
|----------------|------------------|
| `DOMAIN_MCP` | `mcp:8080` (MCP Streamable HTTP, path `/mcp`) |
| `DOMAIN_API` | `tg_parser:8000` (`/metrics` blocked with 403) |
| `DOMAIN_GRAFANA` | `grafana:3000` |

Certificates are obtained and renewed automatically by Caddy.

### Option B: Nginx on the host (alternative)

```bash
sudo apt install nginx certbot python3-certbot-nginx
sudo nano /etc/nginx/sites-available/tg_parser
```

```nginx
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;

    # REST API
    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /health { proxy_pass http://localhost:8000; }
    location /status { proxy_pass http://localhost:8000; }
    location /docs { proxy_pass http://localhost:8000; }
    location /metrics { proxy_pass http://localhost:8000; }

    # MCP Server
    location /mcp {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/tg_parser /etc/nginx/sites-enabled/
sudo certbot --nginx -d your-domain.com
sudo nginx -t && sudo systemctl reload nginx
```

With host Nginx you typically **do not** enable the Docker `caddy` profile, to avoid two processes binding ports 80/443.

---

## Monitoring

Prometheus and Grafana start by default with `docker compose up -d` (no profile needed).

### Health Checks

```bash
# API health (returns JSON with status, version, timestamp)
curl http://localhost:8000/health

# Detailed status (database, LLM, agents, scheduler)
curl http://localhost:8000/status/detailed

# MCP port check
python3 -c "import socket; s=socket.create_connection(('localhost',8080),5); s.close(); print('OK')"
```

### Prometheus + Grafana

Prometheus scrapes two targets inside Docker network (configured in `docker/prometheus.yml`):
- `tg_parser:8000/metrics` — API + Scheduler metrics
- `mcp:8080/metrics` — MCP server metrics

Grafana is available at `http://localhost:${GRAFANA_PORT:-3000}` with provisioned dashboards in `docker/grafana/dashboards/`.

Default credentials: `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` from `.env`.

```bash
# Check API metrics directly
curl http://localhost:8000/metrics

# Check Grafana is up
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/api/health
```

### Docker Health Status

```bash
# All containers health at a glance
docker compose ps

# Resource usage
docker stats --no-stream
```

---

## Backup Strategy

### Database Backups

The repository includes ready-to-use scripts in `docker/`:

```bash
# One-time backup
./docker/backup.sh

# Custom output directory and 14-day retention
./docker/backup.sh /custom/backups 14

# List existing backups
tg-parser db list-backups
```

Backups are saved to `data/backups/postgres_YYYYMMDD_HHMMSS.sql.gz` with automatic rotation (default: 7 days).

**Automated daily backups (cron):**

```bash
# Add to crontab (daily at 2 AM)
(crontab -l 2>/dev/null; echo "0 2 * * * /opt/tg_parser/docker/backup.sh >> /var/log/tg_parser_backup.log 2>&1") | crontab -
```

### Restore from Backup

```bash
# Interactive restore (stops services, restores, verifies counts, restarts)
./docker/restore.sh data/backups/postgres_20260331_020000.sql.gz
```

Or manually:

```bash
docker compose stop tg_parser mcp

gunzip -c data/backups/postgres_20260331_020000.sql.gz | \
  docker compose exec -T postgres psql -U tg_parser_user -d tg_parser --quiet

docker compose start tg_parser mcp
```

---

## Troubleshooting

### Services Won't Start

```bash
# Check logs for each service
docker compose logs postgres
docker compose logs tg_parser
docker compose logs mcp

# Rebuild if code changed
docker compose build --no-cache
docker compose up -d
```

### Database Connection Errors

```bash
docker compose ps postgres              # Is it running?
docker compose logs postgres             # Check logs
docker compose exec postgres psql -U tg_parser_user -d tg_parser  # Manual connect
```

### MCP Not Responding

```bash
docker compose logs mcp
docker compose restart mcp

# Test MCP manually
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
```

### High Memory Usage

```bash
docker stats --no-stream

# Reduce pool sizes in .env
DB_POOL_SIZE=3
DB_MAX_OVERFLOW=5

docker compose restart tg_parser mcp
```

---

## Rollback Procedures

```bash
# Stop services
docker compose down

# Checkout previous version
git checkout v4.0.0

# Restore database if schema changed
gunzip < data/backups/postgres_backup.sql.gz | \
  docker compose exec -T postgres psql -U tg_parser_user tg_parser

# Rebuild and restart
docker compose build
docker compose up -d

# Verify
curl http://localhost:8000/health
```

### Emergency Shutdown

```bash
docker compose down          # Graceful
docker compose kill          # Force (if hanging)
docker ps -a                 # Verify all stopped
```

---

## Maintenance

**Weekly:**
- Check disk space: `df -h`
- Review logs: `docker compose logs --tail=100`
- Verify backups: `ls -la data/backups/`

**Monthly:**
- Update Docker images: `docker compose pull`
- Test backup restoration
- Review database size: `docker compose exec postgres psql -U tg_parser_user -d tg_parser -c "SELECT pg_size_pretty(pg_database_size('tg_parser'));"`

### Updating

```bash
git pull origin main
docker compose build
docker compose exec tg_parser tg-parser db upgrade --db all  # if migrations
docker compose up -d
```

---

## Security Checklist

### Critical (must be set before any public access)

- [ ] `API_KEY_REQUIRED=true` — all API endpoints require `X-API-Key` header
- [ ] `API_KEYS={"your-secure-key":"client-name"}` — at least one API key configured
- [ ] `MCP_AUTH_ENABLED=true` — MCP server requires bearer token
- [ ] `MCP_AUTH_TOKENS={"your-token":"agent-name"}` — at least one MCP token
- [ ] `BOT_ALLOWED_USERS=id1,id2` — Telegram user IDs for bot access (empty = open to all)
- [ ] Strong database password (`DB_PASSWORD`, 32+ characters)

### High (should be set for production)

- [ ] `CORS_ORIGINS=["https://yourdomain.com"]` — restrict to your domains (default `["*"]`)
- [ ] `RATE_LIMIT_ENABLED=true` — prevent abuse
- [ ] SSL/TLS enabled for public access (Nginx + Let's Encrypt or Caddy)
- [ ] Firewall: only ports 22 (SSH), 80/443 (HTTP/HTTPS with proxy)
- [ ] All service ports bound to `127.0.0.1` (not exposed publicly)
- [ ] `LOG_FORMAT=json` for structured logging
- [ ] `LOG_LEVEL=INFO` (not DEBUG in production)

### Standard

- [ ] Backups running and tested (`docker/backup.sh` via cron)
- [ ] Docker images from trusted sources only
- [ ] Nginx `/metrics` endpoints blocked (403)

**Note:** The application logs security warnings on startup when `API_KEY_REQUIRED`, `MCP_AUTH_ENABLED`, or `CORS_ORIGINS` are not configured for production.

---

## Phase 3: Telegram Bot (Gemini Agent)

Phase 3 adds a Telegram bot that serves as a human interface to the knowledge base. The bot uses Gemini function-calling to reason about user requests and invoke internal services.

### Architecture

```
Telegram User  →  aiogram (long polling)  →  Gemini Agent  →  Internal services
                                                               ├─ retrieval_service (search, Q&A)
                                                               ├─ topic_card_repo (topics)
                                                               ├─ channel_service (channels)
                                                               └─ analytics_service (stats)
```

The bot runs as a separate `tg_bot` Docker service sharing the same image and database.

### Setup

#### 1. Create a Telegram Bot

1. Open [@BotFather](https://t.me/BotFather) in Telegram
2. Send `/newbot`, follow prompts to name your bot
3. Copy the bot token

#### 2. Configure Environment

Add to your `.env`:

```env
# Bot token from BotFather
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11

# Gemini API key (required for agent reasoning)
GEMINI_API_KEY=your-gemini-api-key

# Allowlist: comma-separated Telegram user IDs
# Find your ID via @userinfobot
BOT_ALLOWED_USERS=123456789,987654321

# Optional tuning
BOT_GEMINI_MODEL=gemini-2.5-flash
BOT_REQUEST_TIMEOUT=60
BOT_RATE_LIMIT=10
```

#### 3. Start the Bot

The bot is behind a Docker Compose profile (`bot`) to avoid crash-loops when
env vars are not yet configured.

```bash
# Start the bot (alongside existing services)
docker compose --profile bot up -d tg_bot

# Check logs
docker compose --profile bot logs -f tg_bot

# Or standalone via CLI (outside Docker)
tg-parser bot
```

To always start the bot with `docker compose up -d`, add to `.env`:
```env
COMPOSE_PROFILES=bot
```

#### 4. Verify

Send `/start` to your bot in Telegram. You should see the greeting message.

### Bot Capabilities (V1.2)

| Capability | Example |
|------------|---------|
| Q&A | "Что известно про APOE?" |
| Search | "Найди материалы про витамин D" |
| Topics | "Покажи темы по каналу genotek" |
| Channels | "Покажи список каналов" |
| Topic details | "Расскажи подробнее про тему X" |
| Related topics | "Какие темы связаны с Y?" |
| Analytics | "Кросс-канальная статистика" |
| Pipeline status | "Статус пайплайна для genotek" |
| Trigger pipeline | "Запусти обработку genotek" (two-step confirmation) |
| Pause / resume channel | "Поставь канал genotek на паузу" (two-step confirmation) |
| Add channel | "Добавь канал new_channel" (two-step confirmation) |
| Remove channel | "Удали канал old_channel" (two-step confirmation, **irreversible**) |
| View LLM config | "Покажи LLM конфиг" (read-only) |
| Switch LLM | "Переключи LLM на openai" (two-step confirmation) |
| Reset LLM config | "Сбрось LLM конфиг" (two-step confirmation) |

### Security

- **Allowlist**: Only users listed in `BOT_ALLOWED_USERS` can interact with the bot. Empty list = allow all (dev only).
- **Rate limiting**: Configurable per-user rate limit (`BOT_RATE_LIMIT` requests/minute).
- **Write operations**: All write operations require a two-phase tool flow (`confirm=false` preview, then user confirmation, then `confirm=true`). This includes: pipeline trigger, pause/resume, add/remove channel, and LLM config changes.
- **Destructive operations**: `remove_channel` permanently deletes all channel data (documents, topics, embeddings). The preview step explicitly warns the user about irreversibility and shows data counts.

### Monitoring

```bash
# Bot container status
docker compose ps tg_bot

# Bot logs (structured JSON in production)
docker compose logs --tail=50 tg_bot

# Restart if needed
docker compose restart tg_bot
```

### Troubleshooting

| Issue | Solution |
|-------|----------|
| Bot not responding | Check `TELEGRAM_BOT_TOKEN` is valid; check logs for errors |
| "Access denied" | Add your Telegram user ID to `BOT_ALLOWED_USERS` |
| Slow responses | Gemini API latency; check `BOT_REQUEST_TIMEOUT`; try a faster model |
| Empty answers | Verify database has processed documents and embeddings |
| Rate limit errors | Increase `BOT_RATE_LIMIT` or wait |

---

**Document Version**: 3.0
**Last Updated**: April 3, 2026
**TG_parser Version**: v4.2
