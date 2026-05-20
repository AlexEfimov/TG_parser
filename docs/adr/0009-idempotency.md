# ADR 0009 – Idempotency policy for write operations (subscribe_*, HTTP API)

## Статус

**Draft** (2026-05-21). Decision scope-bound to Wave 1 step 3 sprint
(BUG-022 closure + P-1 / P-2 HTTP API design). This ADR defines the
**idempotency contract** for write tools across all four surfaces, with
particular focus on `subscribe_watchlist` / `subscribe_digest` (where
BUG-022 manifests) and the new HTTP API endpoints (where the contract
becomes public).

## Контекст

### BUG-022 evidence

[`BUG_LOG.md` § BUG-022](../notes/BUG_LOG.md) documents that
`subscribe_watchlist` / `subscribe_digest` re-running with identical
arguments **creates duplicate subscriptions** (different UUID, same
content). Reproduced 2026-05-15 in the Claude MCP testing session
(Phase 7); duplicates produce N× push amplification on every match.

Same session noted that `add_workspace_source` (F4-B Core) is correctly
idempotent via `ON CONFLICT (workspace_id, source_id) DO NOTHING` —
proving the pattern exists in the system but is not consistently
applied. ADR 0006 principle 4 («идемпотентность и журналы») is
explicitly violated by the subscribe-tools.

### Inconsistency surface inventory

Audit of write surfaces (per
[`PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md` § 2.1 master list](../notes/PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md)):

| Operation | Idempotent? | Mechanism |
|---|---|---|
| `add_channel` | ✅ Yes | UPSERT by `source_id` with `ON CONFLICT DO UPDATE` (reanimates soft-deleted source) |
| `remove_channel` | ✅ Yes (soft-delete) | UPDATE `deleted_at = now()`, second call no-op |
| `pause_channel` / `resume_channel` | ✅ Yes | Flag flip; second call no-op |
| `create_workspace` | ✅ Yes | `UNIQUE (owner_id, name)`; raises explicit duplicate error (deterministic) |
| `add_workspace_source` | ✅ Yes | Composite PK `(workspace_id, source_id)` + `ON CONFLICT DO NOTHING`; returns `changed: bool` |
| `remove_workspace_source` | ✅ Yes | DELETE; second call returns `changed: false` |
| `subscribe_watchlist` | ❌ **No** (BUG-022) | Plain INSERT; new UUID every call |
| `subscribe_digest` | ❌ **No** (BUG-022) | Plain INSERT; new UUID every call |
| `register_user` | ⚠️ Mixed | `UNIQUE (telegram_user_id)` raises error on duplicate (not silent no-op) |
| `update_user` | ✅ Trivially | UPDATE; deterministic in column-set |
| `set_llm_config` | ✅ Yes | In-memory state assignment; idempotent by definition |
| `add_user_auth` | ⚠️ Partial | `UNIQUE (user_id, kind, mapping)` raises duplicate error |
| `force_resummarize` (F5-C) | ⚠️ Partial | Advisory-lock returns `status='locked'` on concurrent; otherwise new version |

**Pattern:** «idempotent by upsert on natural key» dominates and is
correct (`add_channel`, `add_workspace_source`). `subscribe_*` is the
clear outlier.

### Why HTTP API forces the contract decision

P-1 / P-2 introduce `POST /api/v1/watchlists` + `POST /api/v1/digests`
to external clients. HTTP idempotency convention (RFC 9110 + Stripe-
style `Idempotency-Key` header) is established and widely understood;
the question is which mechanism we adopt.

Three concerns intersect:

1. **Natural-key idempotency** (the «if you call again with same logical
   intent, get same row») — closes BUG-022 at the service layer
   irrespective of surface.
2. **Network-retry idempotency** (the «if my HTTP client retries due to
   transient failure, don't double-create») — typical
   `Idempotency-Key` header semantics; required for any production
   HTTP integration.
3. **Cross-surface consistency** (the «MCP + Bot + CLI + HTTP all
   produce same outcome for same logical intent») — naturally falls
   out of (1) if natural key is the canonical idempotency key.

## Options matrix (decision converging)

Three candidates for the idempotency contract. Two are
complementary (B + C). Final choice in Wave 1 step 3 execution
sub-session.

### Option A — Pure natural-key upsert (subscribe-side fix only)

Add `UNIQUE (user_id, name)` constraint on `watch_interests` +
`digest_subscriptions`. Service layer pre-flight `find_by_user_and_name`
→ if exists, UPDATE mutable fields and return existing UUID with
`created: false`; else INSERT.

**Pros:**

- Closes BUG-022 at the smallest possible surface.
- Defensive: even if HTTP client retries without `Idempotency-Key`,
  the natural-key constraint prevents duplicates.
- Aligns with `add_workspace_source` pattern (proven in F4-B Core).
- Zero new HTTP convention; existing MCP / Bot / CLI signatures
  unchanged.

**Cons:**

- Does not address **transient network retries** for HTTP clients
  (e.g. client times out at 10s but server already inserted; client
  retries; second call gets `created: false` — but client has no way
  to know «my first call succeeded»). Workable but suboptimal.
- Forces users to choose a `name` (probably already required by the
  current API, but worth confirming).
- Doesn't generalize to operations where natural key is ambiguous
  (e.g., `trigger_pipeline` — same channel can be legitimately
  triggered twice in 1 minute).

### Option B — `Idempotency-Key` HTTP header (Stripe-style)

Add support for `Idempotency-Key: <client-generated-uuid>` HTTP header
on `POST` endpoints. Server stores `(idempotency_key, user_id,
response_body)` in a small table with TTL (e.g., 24h); on repeated
request with same key → return stored response, no DB write.

**Pros:**

- Standard pattern; ecosystem expects it for production HTTP APIs.
- Generalizes to any POST endpoint (not just subscribe-*).
- Addresses **transient network retries** correctly — client retries
  with same key get exactly the same response (including UUID).
- Works orthogonally to natural-key constraint (both can coexist).

**Cons:**

- New table + repo + TTL cleanup job.
- Only applies to HTTP surface (MCP / Bot / CLI don't have headers).
- Client must remember to generate + send the key (Stripe SDKs do
  this; raw curl users may not).
- Doesn't close BUG-022 on its own: a client that just calls twice
  **without** the header (and at the MCP / Bot / CLI surface) still
  duplicates.

### Option C — Hybrid: natural-key upsert (always) + `Idempotency-Key` (HTTP optional)

Layer Option A (natural-key upsert at the service layer — closes
BUG-022 everywhere) **plus** Option B (HTTP `Idempotency-Key`
header — closes the network-retry concern for HTTP clients only).

**Pros:**

- Closes BUG-022 across all four surfaces (Option A).
- Adds HTTP convenience for production clients (Option B).
- Both mechanisms are independently useful; together they form a
  belt-and-suspenders contract.
- ADR 0006 principle 4 («идемпотентность и журналы») fully honoured.

**Cons:**

- Two mechanisms to document and test (but the cost is small).
- HTTP header semantics need precise spec (what counts as «same
  request body» if `Idempotency-Key` matches but body differs? — see
  open questions).

## Recommendation (preliminary, non-binding)

**Option C (hybrid).**

1. **Natural-key upsert** (Option A) lands first — closes BUG-022
   surface-agnostic. Service layer: `subscribe_watchlist` /
   `subscribe_digest` pre-flight check `find_by_user_and_name`;
   UPDATE mutable fields if exists; INSERT otherwise. Return shape
   `{subscription_id, created: bool, changed_fields: list[str]}`.
2. **DB constraint as defense in depth:** Alembic adds `UNIQUE
   (user_id, name)` on both tables. Race-condition window between
   pre-flight check and INSERT becomes a clean `IntegrityError` we
   catch and retry as UPDATE.
3. **HTTP `Idempotency-Key` header** (Option B) lands in the same
   sprint for HTTP surface. New `idempotency_keys` table:
   `(key, user_id, request_hash, response_body, created_at)` with 24h
   TTL. Middleware-level interception on all POST endpoints
   (not just subscribe-*).
4. **MCP / Bot / CLI surfaces** rely on Option A alone (no header
   equivalent needed).

Rationale: ADR 0006 principle 4 is explicit; partial mechanisms (just A
or just B) leave gaps. The hybrid is small enough to land in the same
sprint (BUG-022 + P-1 + P-2 + ENH-9). Cost: ~50 LOC in service layer +
~80 LOC for HTTP middleware + 1 migration + ~10 tests.

**This recommendation is preliminary.** Final decision in step 3
execution sub-session.

## Open questions for step 3 execution sub-session

1. **`Idempotency-Key` body-hash check** — if same key, different
   request body → return `422 Unprocessable Entity` (mismatched
   request) or treat as separate (different idempotency)? Stripe-style:
   return cached response, ignore body. Per-spec: return 422.
   Lean: 422 (safer — caller can resolve by changing key or aligning
   body).
2. **TTL for `idempotency_keys` table** — 24h industry default. Make
   configurable via env? Probably no (KISS).
3. **Cleanup of stale `idempotency_keys` rows** — periodic job (every
   1h, DELETE `created_at < now() - 24h`). Add to scheduler tick or
   separate cron?
4. **Migration ordering for `UNIQUE (user_id, name)` on existing rows**
   — if there are existing duplicates from BUG-022, the migration will
   fail. Mitigations: (a) pre-migration cleanup script (admin runs to
   dedupe); (b) staged migration (add column, dedupe, then add
   constraint). Lean: (a) — explicit cleanup is auditable.
5. **`changed_fields` shape** — for `subscribe_*` updates, what does
   the return look like? Lean: `{subscription_id, created: bool,
   changed_fields: ["description", "keywords"]}` — empty list if
   identical (true no-op).
6. **Response shape contract** — same shape on first call (`created:
   true, changed_fields: []`) and on subsequent identical calls
   (`created: false, changed_fields: []`)? Yes — clients can rely on
   `created` to log/notify; `changed_fields` to know what actually
   updated.
7. **Idempotency for DELETE / PATCH endpoints** — strict
   `Idempotency-Key` is most useful for POST/PUT. Lean: DELETE is
   naturally idempotent (second delete is no-op or 404); PATCH usage
   on these endpoints is unclear in step 3 scope, defer.
8. **MCP / Bot / CLI return shape** — `subscribe_watchlist(...)` MCP
   tool currently returns `{subscription_id, ...}`. Add
   `created: bool` to return → tiny breaking change for callers that
   matched the exact shape. Lean: additive (callers using positional
   parsing don't break; structured parsing gets an extra field).
9. **Idempotency for `trigger_pipeline`** — out of scope of this ADR
   (lives in ADR 0007); but mention that ADR 0007 should reuse the
   same `Idempotency-Key` middleware once it lands.

## Test strategy (preliminary)

- **Service layer (Option A):** call `subscribe_watchlist(user, name,
  args1)` then `subscribe_watchlist(user, name, args1)` → same
  subscription_id, `created: false`, `changed_fields: []`.
- **Same name, different args:** second call updates → same
  subscription_id, `created: false`, `changed_fields: ["keywords"]`.
- **Race condition:** simulate concurrent inserts (asyncio.gather) →
  exactly one creates, others UPDATE; no `IntegrityError` propagated.
- **HTTP middleware (Option B):** POST with `Idempotency-Key: foo`,
  then POST same body with same key → identical response, no second
  DB write. POST same key, different body → 422.
- **TTL:** entry created → advance clock 25h → entry deleted by
  cleanup job; new POST with same key proceeds normally.
- **Cross-surface:** MCP `subscribe_watchlist` then HTTP
  `POST /watchlists` with same `(user, name)` → same subscription
  (verifies service-layer-level idempotency).
- **Backward-compat:** existing callers that don't pass
  `Idempotency-Key` get default «no-key» behaviour (still
  natural-key idempotent at service layer).

## Последствия (preliminary)

### Положительные (when Option C lands)

- BUG-022 closed across all four surfaces.
- ADR 0006 principle 4 fully honoured for subscribe-tools.
- HTTP API ships with production-grade idempotency (matches client
  expectations from Stripe / Square / Plaid / standard SaaS API
  conventions).
- Generalizable pattern: `Idempotency-Key` middleware can be reused
  for ADR 0007 (trigger_pipeline) and future POST endpoints.
- Karpathy-like (principle 4 + principle 6 — emit
  `tg_idempotency_keys_hit_total{result}` counter for observability
  of «how often clients actually retry»).

### Отрицательные / accepted debt

- New `idempotency_keys` table + cleanup job (small but additive
  operational surface).
- One Alembic migration with pre-migration cleanup step (BUG-022
  duplicate rows must be manually deduped first — admin runbook
  needed).
- `subscribe_*` return shape gains a `created: bool` field;
  documented but additive (not breaking).
- Two mechanisms (service-level + HTTP-level) — small docs surface
  increase.

### Что НЕ меняется этим ADR (when it lands)

- Existing MCP / Bot / CLI subscribe-tool argument shape (other than
  the additive return field).
- F11 / F6 match-scoring / digest-format logic.
- ADR 0007 dispatch contract (the `Idempotency-Key` middleware is
  reusable but is wired in step 3.1, not step 3).
- F4-B Core workspace tools (already idempotent; no change).

## Ссылки

- [`docs/notes/BUG_LOG.md` § BUG-022](../notes/BUG_LOG.md) — primary blocker.
- [`docs/notes/mcp_testing/2026-05-15_claude_session/01-bug-report.md` § ISSUE-10](../notes/mcp_testing/2026-05-15_claude_session/01-bug-report.md) — session evidence.
- [`docs/notes/mcp_testing/2026-05-15_claude_session/02-enhancements.md` § O-7](../notes/mcp_testing/2026-05-15_claude_session/02-enhancements.md) — architectural observation about idempotency asymmetry.
- [`docs/notes/PARITY_DECISION_TRACKING.md` § P-1 / P-2](../notes/PARITY_DECISION_TRACKING.md) — primary parity package.
- [`docs/notes/PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md` § 2.1](../notes/PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md) — write-surface inventory.
- [RFC 9110 § 9.2.2 «Idempotent Methods»](https://datatracker.ietf.org/doc/html/rfc9110#section-9.2.2) — HTTP standards background.
- [Stripe API Idempotency](https://stripe.com/docs/api/idempotent_requests) — industry-precedent `Idempotency-Key` pattern.
- ADR 0006 (Living-KB principles) — principle 4 («идемпотентность и журналы»).
- ADR 0007 (mcp-scheduler-dispatch) — companion ADR; `Idempotency-Key` middleware reused there.
- ADR 0008 (subscription-target-model) — companion ADR; natural key (`user_id`, `name`) reused there.

## История

| Дата | Изменение |
|------|-----------|
| 2026-05-21 | Draft created in S1 planning sub-session. Captures problem statement (BUG-022 + HTTP API contract design) + 3-option matrix + preliminary Option C (hybrid) recommendation. Final shape locked in step 3 execution sub-session. |
