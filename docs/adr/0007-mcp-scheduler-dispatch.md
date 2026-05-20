# ADR 0007 – MCP↔scheduler dispatch contract for one-shot pipeline jobs

## Статус

**Draft** (2026-05-21). Decision deferred to Wave 1 step 3.1 sprint
planning. This ADR captures the **options matrix** and the **blocker
context** for BUG-015; the final option choice is **not** part of Wave 1
step 3 main sprint (P-1 / P-2 / ENH-9 / BUG-022).

## Контекст

### Blocker: BUG-015 silent no-op

[`BUG_LOG.md` § BUG-015](../notes/BUG_LOG.md) documents a structural
gap: `tg_parser_mcp` container exposes a `trigger_pipeline(channel_id)`
MCP tool that returns `{triggered: true}` (HTTP 200) but performs **no
actual work**. The handler fires `asyncio.create_task(...)` locally
inside the MCP process; the task either dies when the JSON-RPC response
is sent (event-loop scope closes) or survives but cannot perform
ingestion because there is no Telethon-client session in the
`tg_parser_mcp` container.

Surfaced by the 2026-05-15 Claude MCP testing session
([`docs/notes/mcp_testing/2026-05-15_claude_session/01-bug-report.md` § ISSUE-1](../notes/mcp_testing/2026-05-15_claude_session/01-bug-report.md));
production reproduction 2026-05-14 ~05:43 UTC + ~06:00 UTC for channel
`profendocrinologist` — `trigger_pipeline` returned success twice, zero
ingestion happened until the natural 06:28 UTC cron tick.

### Why BUG-015 cannot be fixed without ADR

Three production containers are involved:

| Container | Owns | Lacks |
|---|---|---|
| `tg_parser` | Scheduler (cron + `incremental_pipeline`), Telethon-client session, full pipeline (ingest → process → topicize → embed → watchlist) | MCP server (deliberately — auth surface is HTTP/MCP, not internal) |
| `tg_parser_mcp` | MCP JSON-RPC server, read tools (search / ask / list / get_topic_details), F4-B workspace tools, F11 / F6 subscribe tools | Scheduler, Telethon-client session (until PR #81 added sessions volume — but session ownership semantics remain undefined for cross-container code-callback) |
| `tg_parser_bot` | aiogram bot, Gemini agent, in-process tool executor (incl. `trigger_pipeline` per `tg_parser/bot/tools.py:54`) | Same lack as MCP — runs `_run_pipeline_background` → `run_full_pipeline` in-process, also affected by the cross-container model |

There is **no shared queue, no event bus, no HTTP-API hook** on
`tg_parser` for one-shot scheduler jobs. The cross-container dispatch
contract is the architectural gap.

### Related symptoms blocked by the same gap

- **ENH-1 / ENH-2** (`trigger_topicization` / `trigger_link_topics` —
  see [`PARITY_DECISION_TRACKING.md` § O-3](../notes/PARITY_DECISION_TRACKING.md)
  and [`mcp_testing/2026-05-15_claude_session/02-enhancements.md`](../notes/mcp_testing/2026-05-15_claude_session/02-enhancements.md)).
  Same architectural cause — MCP cannot dispatch long-running scheduler
  jobs to `tg_parser`.
- **Bot `trigger_pipeline` tool** (`tg_parser/bot/tools.py:1373` →
  `run_full_pipeline`). Same code path; same defect. PR #81 partly
  mitigated by adding env + sessions volume to `tg_bot`, but the
  cross-container ownership model for Telethon `code_callback` remains
  structurally undefined.

### Why this ADR slot

The Wave 1 step 3 main sprint scope (P-1 / P-2 / ENH-9 / BUG-022) is
intentionally HTTP-API-CRUD-only. Step 3.1 sprint is where the
dispatch-contract decision actually lands. This ADR stub:

1. Locks the **problem statement** and **options matrix** so step 3.1
   planning sub-session does not re-discover.
2. Forces ENH-1 / ENH-2 / BUG-015 closure to wait for an explicit
   architectural decision rather than an opportunistic hack.
3. Maintains the «one architectural defect → one ADR» discipline
   established by ADR 0001..0006.

## Options matrix (decision deferred)

Five candidates considered; final option choice **must** be made in
step 3.1 planning sub-session.

### Option A — Pre-ADR safety patch (no real dispatch)

Replace `{triggered: true}` lie with
`{triggered: false, error_class: "DispatchNotImplemented", workaround: "..."}`.
Document the SSH workaround prominently in the response.

**Pros:**

- Closes the silent failure mode (operator immediately sees that no
  work was done).
- Zero infrastructure changes; one-PR fix (~10 LOC).
- Compatible with all downstream Options B-E (the safety patch can
  remain as fallback when dispatch infra is mid-deploy).

**Cons:**

- Does **not** fix the actual capability — operators still need SSH +
  CLI to dispatch ingestion.
- Slight UX downgrade for legitimate use-cases (previously naive
  callers thought it worked; now they get an error and must implement
  workaround).
- Itself a behaviour change that an ADR should authorize.

### Option B — HTTP API endpoint on `tg_parser` (`POST /api/v1/pipeline/trigger`)

Add a new internal HTTP endpoint to the `tg_parser` container; MCP /
Bot containers dispatch via HTTP call to `http://tg_parser:8000/...`
across the Docker compose network.

**Pros:**

- Natural extension of the existing `tg_parser/api/main.py` FastAPI
  surface (well-tested, auth-aware, Prometheus-instrumented).
- Aligned with [`PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md` § 4.B](../notes/PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md)
  P1 (Channels CRUD on API — `POST /api/v1/channels/{id}/pipeline/trigger`
  is in the same parity package).
- Same dispatch contract becomes reusable for ENH-1 / ENH-2 / future
  one-shot triggers (parametric endpoint).
- Auth boundary explicit (`tg_parser` API requires bearer or service
  token from MCP / Bot identity).

**Cons:**

- Requires internal service-to-service auth contract (MCP container
  needs a service identity to call `tg_parser` API; ad-hoc tokens are
  brittle).
- Cross-container HTTP call adds a hop; failure modes (network,
  timeout, retry) must be designed.
- Slight conceptual deduplication concern with existing
  `POST /api/v1/process` (which is sync-process-only — not a
  scheduler-trigger).

### Option C — Postgres LISTEN/NOTIFY shared queue

`tg_parser_mcp` writes a row to a `pipeline_jobs` table; `tg_parser`
container listens via `LISTEN pipeline_jobs` notification channel and
picks up the job.

**Pros:**

- No new infrastructure (Postgres already shared between containers).
- Natural fit for «one-shot job dispatch» pattern (job ID, status
  polling via `get_pipeline_status(job_id)`).
- Atomic with auth (the row carries the calling user_id from MCP
  context — no separate token).
- Pattern reusable for ENH-1 / ENH-2 / future long-running ops.

**Cons:**

- Connection-per-listener overhead (Postgres LISTEN is per-connection
  not per-pool).
- New table + new repo + migration + reconnect-on-disconnect logic.
- Less observable than HTTP (no FastAPI metrics; need custom
  Prometheus counters).
- Concurrency story unclear (multiple `tg_parser` instances would each
  receive the notification — need leader election or job-claim row
  pattern).

### Option D — Redis or message-queue (RabbitMQ / NATS)

Introduce a real queue. MCP enqueues; `tg_parser` worker dequeues.

**Pros:**

- Industry-standard pattern; rich tooling (DLQ, retries, observability).
- Decouples scheduler entirely — could scale `tg_parser` workers
  independently (F8-B prerequisite eventually).

**Cons:**

- New service in the Docker compose stack (Redis or RabbitMQ
  container, persistence config, health checks).
- Outside Wave 1 scope by a wide margin — this is F8-B territory.
- Premature optimization for current scale (~10 channels, ~28 ticks /
  day).

### Option E — In-process scheduler exposed via gRPC / RPC over Unix socket

MCP and `tg_parser` share a Unix socket volume; `tg_parser` exposes a
small RPC server on it; MCP dispatches via the socket.

**Pros:**

- Localhost-only (no network exposure).
- Faster than HTTP for small RPC.

**Cons:**

- New protocol surface (gRPC schema, codegen, two-language stub
  generation).
- Unusual pattern in Python ecosystem; adds operational complexity.
- Same auth challenge as Option B (need service identity).
- No real upside over Option B at current scale.

## Recommendation (preliminary, non-binding)

**Option A (pre-ADR safety patch) + Option B (HTTP API endpoint) as the
primary dispatch model**, layered:

1. **Land Option A first** as a Wave 1 step 3.1 mini-PR (~10 LOC).
   Closes the silent failure mode immediately; operator UX improves
   even before the real dispatch is built.
2. **Layer Option B on top** in the step 3.1 main sprint. HTTP endpoint
   becomes the canonical dispatch contract; ENH-1 / ENH-2 become
   parametric extensions of the same endpoint.
3. **Defer Options C / D / E** to F8-B (Redis + task queue, Wave 4)
   when scale signals warrant the operational complexity.

Rationale: Option B reuses existing surface (FastAPI), has the cleanest
auth story (bearer token from MCP / Bot identity → existing API auth),
and unblocks the largest set of downstream features (ENH-1 / ENH-2 / O-3
parity gap closure). Option A is non-conflicting safety; Options C / D /
E are over-engineering for current scale.

**This recommendation is preliminary.** Final decision deferred to step
3.1 planning sub-session with fresh evidence (any new signals from Wave
1 step 3 main sprint about HTTP API patterns).

## Open questions for step 3.1 planning

1. **Auth model for cross-container HTTP call** — service token
   pattern (MCP gets a long-lived token from `tg_parser`) vs JWT-style
   short-lived (MCP mints per-request) vs Docker-network-only IP
   allowlist. Cleanest: MCP forwards the caller's user identity (so
   audit + RBAC are preserved end-to-end).
2. **Idempotency** — does `POST /api/v1/pipeline/trigger` accept the
   same `Idempotency-Key` pattern as ADR 0009? If `subscribe_*`
   endpoints use it, `trigger_pipeline` should too (consistency).
3. **Response shape** — synchronous (block until job_id assigned, then
   return) vs async (return job_id immediately, status polled via
   existing `get_pipeline_status`). Lean toward async to match existing
   F2 export pattern.
4. **Telethon `code_callback` ownership** — surfaced as BUG-015's
   downstream subset. When MCP-triggered ingestion needs to re-auth
   (Telethon session expired), which container owns the code-callback
   flow? Probably must stay in `tg_parser` (where the session file
   lives); MCP returns a typed error directing the operator to SSH.
5. **Backpressure** — if MCP fires 100 `trigger_pipeline` calls in 1s,
   what protects the scheduler? Probably: token-bucket per user_id at
   the API layer; reject with `429` + `Retry-After`.

## Test strategy (preliminary)

When step 3.1 sprint implements Option B:

- **Integration test** via docker-compose harness: both containers up,
  MCP `trigger_pipeline(channel_id="<X>")` → assert
  `docker logs tg_parser` shows `Starting ingestion: source=<X>`
  within 60s.
- **Auth test:** MCP call without valid bearer → 401 from `tg_parser`
  API; with mismatched user_id (cross-tenant) → 403.
- **Idempotency test:** same `Idempotency-Key` twice → second call
  returns same job_id with `created: false`.
- **Backpressure test:** N parallel calls → at most M dispatched, rest
  return `429`.

## Последствия (preliminary)

### Положительные (when Option A + B land)

- BUG-015 closed: `trigger_pipeline` actually works.
- ENH-1 / ENH-2 unblocked: `trigger_topicization` / `trigger_link_topics`
  become natural extensions of the same dispatch endpoint.
- O-3 parity gap [`PARITY_DECISION_TRACKING.md` § 3](../notes/PARITY_DECISION_TRACKING.md)
  closed in the same surface (HTTP API).
- Karpathy-like principle 7 (graceful degradation) restored — MCP no
  longer lies about success.

### Отрицательные / accepted debt

- Service-to-service auth contract adds a small surface area (one new
  token type or one new identity-forwarding pattern).
- Cross-container HTTP introduces a network failure mode that the
  current single-container pattern does not have.
- Long-running ops (ingestion of a 10k-message channel can take
  minutes) need async-job semantics; the existing `get_pipeline_status`
  surface is reused but is currently per-source not per-job.

### Что НЕ меняется этим ADR (when it lands)

- Scheduler internal logic (per-task `AsyncSession`, BUG-013/14/24
  fixes) untouched.
- F4-B Core workspace scoping logic untouched.
- Bot `trigger_pipeline` tool surface untouched (it becomes a thin
  proxy to the new HTTP endpoint).
- The natural cron scheduler tick continues to be the dominant
  dispatch mechanism; this ADR addresses the «start now» escape
  hatch only.

## Ссылки

- [`docs/notes/BUG_LOG.md` § BUG-015](../notes/BUG_LOG.md) — primary blocker.
- [`docs/notes/BUG_LOG.md` § BUG-016](../notes/BUG_LOG.md) — env-drift, fixed by PR #81; same cross-container cluster.
- [`docs/notes/PARITY_DECISION_TRACKING.md` § O-3](../notes/PARITY_DECISION_TRACKING.md) — MCP write-tool asymmetry.
- [`docs/notes/PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md` § 4.B P1](../notes/PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md) — Channels CRUD on API (related parity package).
- [`docs/notes/mcp_testing/2026-05-15_claude_session/01-bug-report.md` § ISSUE-1](../notes/mcp_testing/2026-05-15_claude_session/01-bug-report.md) — original session evidence.
- [`docs/notes/mcp_testing/2026-05-15_claude_session/02-enhancements.md`](../notes/mcp_testing/2026-05-15_claude_session/02-enhancements.md) — ENH-1 / ENH-2.
- [`docs/notes/mcp_testing/2026-05-15_claude_session/03-investigation-log.md` § Phase 3](../notes/mcp_testing/2026-05-15_claude_session/03-investigation-log.md) — architectural walk.
- [`docs/notes/REVIEW_2026-05-16_BUG013_14_24_DONE.md` § 4.2](../notes/REVIEW_2026-05-16_BUG013_14_24_DONE.md) — BUG-015 deferred to ADR-0007-gated sprint.
- ADR 0001 (overall architecture), ADR 0004 (hexagonal), ADR 0006 (Living-KB) — context for «dispatch contract» as architectural decision.

## История

| Дата | Изменение |
|------|-----------|
| 2026-05-21 | Draft created in S1 planning sub-session. Captures problem statement + 5-option matrix + preliminary recommendation (Option A + B). Decision deferred to Wave 1 step 3.1 sprint planning. |
