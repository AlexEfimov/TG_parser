# Server Architecture — Production Deployment

**Version:** 4.4.0 (generic template) | **Updated:** June 2026

This document describes a typical TG_parser production topology. Host-specific values (IP, domains, SSH ports) belong in the operator's **private runbook** — not in the public repository.

For Wave 1.5 admin checklists, see [WAVE1_5_VALIDATOR_ONBOARD.md](runbooks/WAVE1_5_VALIDATOR_ONBOARD.md).

---

## Network Topology

```
Internet
  │
  ├── :80/:443 ── Reverse proxy on host (Nginx or Caddy — TLS termination)
  │                 ├── api.example.com     → 127.0.0.1:8000  (tg_parser API)
  │                 ├── mcp.example.com     → 127.0.0.1:8080  (MCP Server)
  │                 └── grafana.example.com → 127.0.0.1:3000  (Grafana)
  │
  └── :22 ── SSH (restrict port / keys in production)

Docker network: tg_parser_network (bridge)
  │
  ├── tg_parser        :8000  → 127.0.0.1:8000  (REST API + Background Scheduler)
  ├── tg_parser_mcp    :8080  → 127.0.0.1:8080  (MCP Streamable HTTP)
  ├── tg_parser_bot    (no port, long polling)    (Telegram Bot — profile: bot)
  ├── tg_parser_postgres :5432 → 127.0.0.1:5432  (PostgreSQL 17 + pgvector)
  ├── tg_parser_prometheus :9090 (internal only)
  └── tg_parser_grafana  :3000 → 127.0.0.1:3000  (Grafana)
```

**Security default:** bind service ports to `127.0.0.1` — not accessible from the internet directly. Only the reverse proxy (:80/:443) is public-facing.

Alternative: use Compose `--profile production` for in-stack **Caddy** instead of host Nginx.

---

## Services

### PostgreSQL 17 + pgvector
- **Container**: `tg_parser_postgres`
- **Image**: `pgvector/pgvector:pg17`
- **Volume**: `tg_parser_pgvector17_data` (external, pre-created)
- **Healthcheck**: `pg_isready`

### TG_parser API + Scheduler
- **Container**: `tg_parser`
- **Default CMD**: `api --host 0.0.0.0 --port 8000`
- **Healthcheck**: `GET /health`

### MCP Server
- **Container**: `tg_parser_mcp`
- **CMD**: `mcp --host 0.0.0.0 --port 8080`
- **Transport**: Streamable HTTP
- **Auth**: Bearer token when `MCP_AUTH_ENABLED=true`

### Telegram Bot (optional)
- **Profile**: `bot`
- **CMD**: `bot`
- Long polling — no published port

### Monitoring
- **Prometheus** + **Grafana** — included in default `docker compose up`
- Dashboards under `docker/grafana/dashboards/`

---

## Deployment checklist

1. `docker volume create tg_parser_pgvector17_data`
2. Configure `.env` (see [ENV_VARIABLES_GUIDE.md](../ENV_VARIABLES_GUIDE.md))
3. `docker compose up -d --build`
4. `docker compose run --rm tg_parser init`
5. `docker compose run --rm tg_parser auth`
6. `docker compose run --rm tg_parser migrate-users` (multi-tenancy)
7. Configure reverse proxy + TLS for API and MCP endpoints

Full guide: [PRODUCTION_DEPLOYMENT.md](../PRODUCTION_DEPLOYMENT.md).

---

## Operator-private overlay

Maintain a **local** (gitignored) note with your deployment specifics:

| Field | Your value (not in repo) |
|-------|--------------------------|
| Server hostname | |
| Public IP / SSH port | |
| API domain | |
| MCP URL | |
| Grafana URL | |
| Digest channel @handle | |
| Bot @username | |

---

## Related documentation

- [PRODUCTION_DEPLOYMENT.md](../PRODUCTION_DEPLOYMENT.md)
- [docs/guides/SELF_HOST.md](guides/SELF_HOST.md)
- [docs/GETTING_STARTED.md](GETTING_STARTED.md)
