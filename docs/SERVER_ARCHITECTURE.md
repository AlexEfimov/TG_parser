# Server Architecture — Production Deployment

**Version:** 4.4.0 (generic template) | **Updated:** June 2026

This document describes a typical TG_parser production topology. Host-specific values (IP, domains, SSH ports) belong in the operator's **private runbook** — not in the public repository.

For Wave 1.5 admin checklists, see [WAVE1_5_VALIDATOR_ONBOARD.md](runbooks/WAVE1_5_VALIDATOR_ONBOARD.md).

---

## Network Topology

```
Internet
  │
  ├── :80/:443 ── Reverse proxy, TLS termination (see § Reverse proxy below)
  │                 ├── api.example.com     → 127.0.0.1:${API_PORT}      (tg_parser API)
  │                 ├── mcp.example.com     → 127.0.0.1:${MCP_PORT}      (MCP Server)
  │                 └── grafana.example.com → 127.0.0.1:${GRAFANA_PORT}  (Grafana)
  │
  └── :22 ── SSH (restrict port / keys in production)

Docker network: tg_parser_network (bridge)
  │
  ├── tg_parser        :8000  → 127.0.0.1:${API_PORT:-8000}      (REST API + Background Scheduler)
  ├── tg_parser_mcp    :8080  → 127.0.0.1:${MCP_PORT:-8080}      (MCP Streamable HTTP)
  ├── tg_parser_bot    (no port, long polling)    (Telegram Bot — profile: bot)
  ├── tg_parser_postgres :5432 → 127.0.0.1:${DB_PORT:-5432}      (PostgreSQL 17 + pgvector)
  ├── tg_parser_prometheus :9090 (internal only)
  └── tg_parser_grafana  :3000 → 127.0.0.1:${GRAFANA_PORT:-3000} (Grafana)
```

**Security default:** bind service ports to `127.0.0.1` — not accessible from the internet directly. Only the reverse proxy (:80/:443) is public-facing.

> ⚠️ The container port is fixed; the **published** loopback port is not. Grafana always listens on `3000` inside the container, but Compose publishes it as `${GRAFANA_PORT:-3000}` (`docker-compose.yml`), and a deployment may well publish it elsewhere. Never hard-code the host-side port into a proxy config from memory — read it: `docker compose port grafana 3000` (same for `tg_parser 8000` / `mcp 8080`).

---

## Reverse proxy

This is the reference for how TLS termination and routing must behave. It states **invariants**, not one host's configuration file: a snapshot of a live config rots the moment the host changes, and this project has already been bitten by two deploy documents disagreeing (BUG-090). Where a value is host-specific, the command to read the live truth is given instead of the value.

**Two supported shapes.** Either works; they are mutually exclusive because both want `:80/:443`.

| Shape | When | Consequence |
|---|---|---|
| **Proxy on the host** (Nginx, Caddy, anything) | TLS/routing already managed outside Docker, or the box hosts unrelated sites | The Compose `caddy` service must stay **off** — starting it fails to bind `:80/:443` |
| **In-stack Caddy** (`--profile production`) | Greenfield box dedicated to this stack | Nothing else may hold `:80/:443` |

**Invariants both shapes must satisfy:**

1. **One terminator, three names** — API, MCP and Grafana each get their own virtual host. All upstreams are loopback; no service port is published on a public interface.
2. **`/metrics` is not public on the API host.** The API vhost must answer `403` for `/metrics` while proxying everything else. Mirrors `docker/Caddyfile` and the pre-flight checklist in [PRODUCTION_DEPLOYMENT.md](../PRODUCTION_DEPLOYMENT.md). Verify: `curl -o /dev/null -w '%{http_code}\n' https://<api-host>/metrics` → `403`.
3. **The MCP vhost must not break streaming.** MCP is Streamable HTTP/SSE: the proxy needs HTTP/1.1, `Upgrade`/`Connection` pass-through, response buffering off, and a read timeout of minutes rather than seconds. A default 60s timeout silently truncates long tool calls.
4. **Upstream ports are read, not remembered** — see the warning above.
5. **Certificates are whatever the terminator reports.** With host Nginx + certbot: `certbot certificates` for inventory, renewal by the `certbot.timer` systemd unit. With in-stack Caddy: automatic, state in the `caddy_data` volume. Verify the live issuer/expiry from outside: `echo | openssl s_client -connect <host>:443 -servername <host> 2>/dev/null | openssl x509 -noout -issuer -dates`.

**These invariants have an executable form.** [`ops/verify-perimeter-invariants.sh`](../ops/verify-perimeter-invariants.sh) checks all five against the live perimeter and writes violations to the operator's alarm channel; silence means healthy. Prose does not fail, so the script — not this section — is what actually notices a drifted perimeter; this section stays the specification the script is written against, and it is the one to change first if a requirement is wrong. It discovers hosts and ports rather than hardcoding them, so it carries no host-specifics and runs on any installation. Precedent for closing this kind of gap with a two-directional check rather than more careful reading: BUG-089.

**Which shape a given deployment uses is host-specific** and therefore belongs in the operator's private runbook (see the note at the top of this document), together with the actual hostnames. To determine it on a running box: `ss -tlnp | grep -E ':80 |:443 '` and `docker ps --format '{{.Names}}' | grep caddy`.

> The reference deployment behind this repository runs the **host-proxy** shape (system Nginx + certbot); its Compose `caddy` service has never been started there. Recorded so nobody follows the in-stack path on that box by accident — the concrete evidence is in [BUG_LOG.md](notes/BUG_LOG.md) § BUG-090.

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
