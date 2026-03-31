# Production Deployment Guide

**TG_parser v4.1 Production Deployment**

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
docker compose up starts 3 services:

┌─────────────────────────────────────────────────────┐
│                Docker Compose Stack                  │
│                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────┐  │
│  │  postgres     │  │  tg_parser   │  │   mcp     │  │
│  │  :5432        │  │  :8000       │  │   :8080   │  │
│  │  pgvector/pg17│  │  API +       │  │  Streamable│  │
│  │              │  │  Scheduler   │  │  HTTP     │  │
│  └──────┬───────┘  └──────┬───────┘  └─────┬─────┘  │
│         │                 │                 │        │
│         └────── tg_parser_network ──────────┘        │
└─────────────────────────────────────────────────────┘

External access:
  HTTP clients     → :8000 (REST API, /docs, /metrics)
  AI agents        → :8080/mcp (MCP Streamable HTTP)
  CLI one-shot     → docker compose run tg_parser <command>
```

| Service | Port | Purpose |
|---------|------|---------|
| **postgres** | 5432 | PostgreSQL 17 + pgvector |
| **tg_parser** | 8000 | REST API + Background Scheduler |
| **mcp** | 8080 | MCP Server (Streamable HTTP for AI agents) |

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

### Step 2: Configure Environment

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

### Step 3: Build and Start

```bash
# Build images and start all services
docker compose up -d --build

# Check all services are running
docker compose ps

# Expected output:
# tg_parser_postgres   running (healthy)
# tg_parser            running (healthy)
# tg_parser_mcp        running (healthy)
```

### Step 4: Verify Deployment

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

---

## SSL/TLS Configuration

### Nginx Reverse Proxy (Recommended)

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

---

## Monitoring

### Health Checks

```bash
# API health (returns JSON with status, version, timestamp)
curl http://localhost:8000/health

# Detailed status (database, LLM, agents, scheduler)
curl http://localhost:8000/status/detailed

# MCP port check
python3 -c "import socket; s=socket.create_connection(('localhost',8080),5); s.close(); print('OK')"
```

### Prometheus Metrics

TG_parser exposes metrics at `/metrics`:

```bash
curl http://localhost:8000/metrics
```

Prometheus scrape config:

```yaml
scrape_configs:
  - job_name: 'tg_parser'
    static_configs:
      - targets: ['localhost:8000']
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

- [ ] Strong database password (32+ characters)
- [ ] API keys configured (`API_KEY_REQUIRED=true`)
- [ ] MCP auth tokens configured (`MCP_AUTH_ENABLED=true`)
- [ ] Firewall: only 22, 8000, 8080 (or 80/443 with proxy)
- [ ] SSL/TLS enabled for public access
- [ ] Backups running and tested
- [ ] `LOG_FORMAT=json` for structured logging
- [ ] Rate limiting enabled
- [ ] CORS origins restricted to your domains
- [ ] Docker images from trusted sources only

---

**Document Version**: 2.0
**Last Updated**: March 30, 2026
**TG_parser Version**: v4.1
