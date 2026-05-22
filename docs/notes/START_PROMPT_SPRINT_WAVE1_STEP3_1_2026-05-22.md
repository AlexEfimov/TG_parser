# Sprint Wave 1 step 3.1 — MCP↔scheduler dispatch (ADR 0007)

> ✅ **Planning landed 2026-05-22** — pushed to `origin/main` as
> `84f63ff`. ADR 0007 ratified **Accepted** (Option A + B layered).
> **Execution:** fresh chat via
> [`START_PROMPT_EXECUTION_WAVE1_STEP3_1_2026-05-22.md`](START_PROMPT_EXECUTION_WAVE1_STEP3_1_2026-05-22.md)
> + [`CHECKLIST_WAVE1_STEP3_1_2026-05-22.md`](CHECKLIST_WAVE1_STEP3_1_2026-05-22.md).

---

## §1 — Sprint identity

**Дата подготовки:** 2026-05-22 (S3.1 planning sub-session).
**Тип сессии:** Architectural fix (~1 сессия; **Single PR + 2–3 atomic commits**).
**Wave 1 step:** 3.1 (per [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) sequence after step 3).
**HEAD на старт execution:** `84f63ff` или позже на `origin/main` (planning docs commit; code baseline = PR #89 `a30abd5` + docs-only `84f63ff`).
**Baseline pytest (verified S3.1 pre-flight @ `84f63ff`):** `2175 passed / 311 skipped / 0 failed` default; `2477 / 9 / 0` with `TEST_POSTGRES=1`.
**Execution branch (suggested):** `fix/wave1-step3-1-mcp-dispatch-2026-05-22` off `origin/main`.

**Closes:**

| ID | Summary |
|---|---|
| **BUG-015** | MCP `trigger_pipeline` silent no-op → honest dispatch via HTTP |
| **ENH-1** | MCP `trigger_topicization` tool |
| **ENH-2** | MCP `trigger_link_topics` tool |
| **O-3** | MCP write-tool asymmetry ([`PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md) § 3) |

**Parent ADR:** [`docs/adr/0007-mcp-scheduler-dispatch.md`](../adr/0007-mcp-scheduler-dispatch.md) — **Accepted 2026-05-22**.

**Precedent sprint prompt:** [`START_PROMPT_SPRINT_WAVE1_STEP3_2026-05-21.md`](START_PROMPT_SPRINT_WAVE1_STEP3_2026-05-21.md).

**Phase C note:** Wave 1 step 3 deploy + 24h watch may still be **OPEN** when execution starts — orthogonal; do not block step 3.1 code on watch closure.

---

## §2 — Scope

### In scope (locked)

**Phase A — Option A safety patch (~10 LOC, commit 1/N):**

- MCP `trigger_pipeline` in `tg_parser/mcp_server.py` (and bot `tg_parser/bot/tools.py` proxy if still lying): when HTTP dispatch unavailable, return `triggered=false`, `error_class=DispatchNotImplemented`, `workaround` pointing to operator SSH path below — **never** `{triggered: true}` without verified job acceptance.
- **Operator workaround (until commit 2/3 deploy):** `docker compose exec tg_parser tg-parser ingest --source <channel_id>` on VPS (`tg_parser` container, not `tg_parser_mcp`); or wait ≤1h for scheduler tick. See [`mcp_testing/2026-05-15_claude_session/04-operational-runbook.md`](mcp_testing/2026-05-15_claude_session/04-operational-runbook.md) § 1, § 5.
- USER_GUIDE / MCP_AGENT_GUIDE: one-line operator warning until Phase B lands (**remove warning after commit 2**, when HTTP dispatch is live).

**Phase B — Option B HTTP dispatch (commit 2/N + 3/N):**

- `POST /api/v1/pipeline/trigger` on `tg_parser` container (FastAPI, existing auth `X-API-Key` → `CurrentUser`).
- Request body (locked):

```json
{
  "channel_id": "profendocrinologist",
  "job": "full_pipeline | topicization | link_topics",
  "force": false
}
```

- Response (async, locked):

```json
{
  "job_id": "<uuid>",
  "created": true,
  "status": "queued"
}
```

- **`created` semantics (locked):** first successful enqueue → `created: true`. Replay with same `Idempotency-Key` header and identical body → same `job_id`, `created: false`, `status` unchanged. MCP/Bot calls **without** `Idempotency-Key` → each POST is independent (expect `created: true` per call unless API adds optional in-flight dedup later).
- Poll via existing `get_pipeline_status` where applicable; extend status payload **only if** required for `job` discriminator (prefer minimal delta).
- MCP + Bot: thin HTTP client to `http://tg_parser:8000` on Docker network; forward caller identity (reuse same `X-API-Key` the external client used, or internal service key mapping — see Q1).
- **ENH-1 / ENH-2:** register MCP tools calling same endpoint with `job=topicization` / `job=link_topics`.
- Integration test: compose harness — MCP `trigger_pipeline` → logs on `tg_parser` show pipeline start within 60s.
- Prometheus: `tg_pipeline_trigger_total{job,result,surface}` (surface=mcp|bot|api).

**Auth / idempotency (locked from ADR 0007 open questions):**

| Q | Decision |
|---|---|
| Cross-container auth | **A:** MCP/Bot forward the end-user `X-API-Key` (or MCP token resolved to same user) on internal HTTP call — preserves RBAC audit trail. No new service-token type in MVP. |
| Idempotency on trigger | **Optional** `Idempotency-Key` on POST (same middleware as step 3); not required for MCP (no header). |
| Async shape | Return `job_id` immediately; scheduler runs work in `tg_parser` process. |
| Telethon re-auth | Typed error directing operator to SSH on `tg_parser` container; no MCP-side `code_callback`. |
| Backpressure | Per-user rate limit on trigger endpoint (reuse rate_limit middleware pattern); `429` + `Retry-After`. |

### Out of scope (hard anti-scope)

| Item | Where |
|---|---|
| Redis / NATS queue (Option D) | F8-B / Wave 4 |
| Postgres LISTEN/NOTIFY (Option C) | Deferred |
| gRPC Unix socket (Option E) | Rejected |
| Channels CRUD API (P1 package) | Future parity sprint |
| `topicization.py` / `pipeline_service.py` scheduler BUG-013/14 fixes | Unless required by dispatch wiring only |
| ADR 0008 polymorphic targets | Wave 1 step 4 |
| Wave 1 step 4 shareable digest | After step 3.1 |

---

## §3 — Locked design decisions (Q1–Q5)

### Q1 — Endpoint path `[CONFIRMED 2026-05-22]`

`POST /api/v1/pipeline/trigger` — parametric `job` enum, not three separate paths (KISS, one auth/rate-limit/metrics surface).

### Q2 — Job enum `[CONFIRMED 2026-05-22]`

| `job` value | Maps to |
|---|---|
| `full_pipeline` | `run_full_pipeline` (BUG-015 primary) |
| `topicization` | CLI `tg-parser topicize` equivalent (ENH-1) |
| `link_topics` | CLI `tg-parser link-topics` equivalent (ENH-2) |

### Q3 — MCP implementation `[CONFIRMED 2026-05-22]`

Replace `asyncio.create_task(_run_pipeline_background)` in `mcp_server.py` with `httpx` POST to internal API. Delete or gate dead in-process runner behind feature flag **removed** in same PR (no dual path).

### Q4 — Bot tool `[CONFIRMED 2026-05-22]`

`tg_parser/bot/tools.py` `trigger_pipeline` → same HTTP proxy (mirror MCP).

### Q5 — Tests `[CONFIRMED 2026-05-22]`

- `tests/test_api_pipeline_trigger.py` — auth, 403 cross-tenant, job enum, rate limit, idempotency optional.
- `tests/test_mcp_pipeline_dispatch.py` — mock `httpx` or testcontainers dual-container (prefer mock at unit layer + one integration marked `@pytest.mark.postgres` or compose if existing harness).
- Regression: existing `test_api_watchlists` / `test_f11*` unchanged.

---

## §4 — PR shape

| Commit | Scope |
|---|---|
| **1/3** | Option A: honest failure responses + docs warning |
| **2/3** | `POST /api/v1/pipeline/trigger` + scheduler wiring + metrics + tests |
| **3/3** | MCP ENH-1/ENH-2 + proxy refactor + bot proxy + BUG_LOG/PARITY closure rows |

**Estimate:** ~400–700 LOC, ~20–30 tests.

---

## §5 — Acceptance criteria

1. MCP `trigger_pipeline(channel_id)` after deploy → ingestion log line on **`tg_parser`** container within 60s (not `tg_parser_mcp`).
2. `trigger_topicization` / `trigger_link_topics` MCP tools exist and return same async job contract.
3. BUG-015 row in [`BUG_LOG.md`](BUG_LOG.md) → **resolved** with PR SHA.
4. [`PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md) § O-3 → marked closed в step 3.1 row.
5. `2175+ / 0 failed` pytest default; ruff clean.
6. Production smoke (optional in execution): one MCP trigger via Cursor MCP server post-deploy.

---

## §6 — Pre-flight gate

```bash
cd /Users/alexanderefimov/TG_parser
git fetch origin && git checkout main && git pull --ff-only origin main
git rev-parse HEAD   # expect 84f63ff or later
.venv/bin/pytest -q 2>&1 | tail -3   # expect 2175+ passed, 0 failed
ruff format --check . && ruff check .
```

**Phase C / step 3 watch:** if Wave 1 step 3 deploy + 24h watch still OPEN — **do not block** step 3.1 code or PR on watch closure (orthogonal).

**Do not touch:** `pyproject.toml`, `uv.lock`, `docs/methodology/**`.

---

## §7 — After step 3.1

Per strategy § 5.1:

1. **Wave 1 step 4** — Shareable Digest (`publish_to_channel`, ADR 0008).
2. **Wave 1.5** — Operational dogfooding (HTTP API + MCP).
3. **Wave 1 closure** — aggregate DONE marker.

---

## §8 — История

| Дата | Изменение |
|------|-----------|
| 2026-05-22 | Planning prompt created (S3.1). ADR 0007 Accepted. Locks Option A+B, Q1–Q5, PR 3-commit shape. |
| 2026-05-22 | Self-review: HEAD → `84f63ff`, `created` idempotency semantics, operator workaround + file paths, execution entrypoint + checklist split out. Pushed `84f63ff` to `origin/main`. |
