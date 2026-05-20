# Sprint Wave 1 step 3 — Surface Parity (HTTP API for F11 Watchlist + F6 Digest + ENH-9 workspace_id + BUG-022 idempotency)

> ✅ **Planning landed 2026-05-21** — Wave 1 step 3 sprint prompt
> produced by S1 doc-drift cleanup + planning sub-session (parent
> session S1 → S2 → S3 → S4 → S5). Branch:
> `docs/wave1-step3-planning-2026-05-21`. C1 (drift cleanup) +
> C2 (ADR 0007 / 0008 / 0009 drafts) + C3 (this artifact + CHANGELOG)
> co-landed in the same branch. Execution sub-session opens in a fresh
> chat after the user reviews this prompt and confirms scope.
>
> Sections below describe the locked-now sprint plan. Open questions
> are explicitly marked `[OPEN]` for execution sub-session — do **not**
> resolve them inside this prompt.

---

## §1 — Sprint identity

**Дата подготовки промпта:** 21 мая 2026 (S1 planning sub-session ~0.5 сессии — drift cleanup tail + planning).
**Тип сессии:** Surface parity (~1–2 сессии; **Single PR + 4–5 atomic commits** — mirror Session F4-B Core pattern).
**Wave 1 step:** 3 (per audience-driven roadmap).
**HEAD на момент написания промпта:** `9068cbf` на `origin/main` (PR #85 doc hygiene merged); branch HEAD `f025a80` (ADR drafts).
**HEAD на момент старта S3 execution sub-session (pre-flight 2026-05-21):** `4d567ce` на `origin/main`. Между планированием и execution также landed:
- PR [#86](https://github.com/AlexEfimov/TG_parser/pull/86) (S1 planning artifacts merged 2026-05-21, SHA `d7a18f9`) — этот prompt + ADR drafts 0007/0008/0009 + drift cleanup.
- PR [#87](https://github.com/AlexEfimov/TG_parser/pull/87) (S2 quick-wins merged 2026-05-21, SHA `2e9213c`) — closed BUG-017/018/023; +13 tests; baseline стал `2147 passed, 258 skipped`.
- Docs backfill commit `4d567ce` (closure SHAs для BUG_LOG rows).
**Closes:** Wave 1 step 3 «Surface Parity» (HTTP API for watchlist + digest + ENH-9 + BUG-022). Audience drivers A4 (AI Agent Builder, primary) + A6 (Domain Curator, secondary, via channel-target enabler for Wave 1 step 4).
**Parent planning sub-session:** S1 chat 2026-05-21 (this prompt + ADR drafts 0007 / 0008 / 0009 + doc-drift cleanup).
**DONE marker предыдущего шага:** [`REVIEW_2026-05-14_WAVE1_STEP2_DONE.md`](REVIEW_2026-05-14_WAVE1_STEP2_DONE.md) (F4-B Core watch closed GREEN 2026-05-14).

**Прецеденты (читать перед стартом):**

- [`PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md) § 1 P-1 / P-2 (pre-references) + § 3 O-1 / O-3 (observations).
- [`PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md`](PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md) § 4.B (API gap B-10 / B-11) + § 6 P2 (combined F6 + F11 API CRUD package) + § 7 ADR-0006 check.
- [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) Wave 1 step 3 description.
- [`HANDOFF_POST_MCP_INTAKE_2026-05-15.md`](HANDOFF_POST_MCP_INTAKE_2026-05-15.md) (untracked but in workspace — ENH-9 + BUG-022 scope source; do **NOT** include as canonical reference in commits, reference its tracked downstream artifacts instead: BUG_LOG § BUG-022, ENH-9 in mcp_testing snapshot).
- [`docs/adr/0007-mcp-scheduler-dispatch.md`](../adr/0007-mcp-scheduler-dispatch.md) — Draft; **NOT** for this sprint, references only.
- [`docs/adr/0008-subscription-target-model.md`](../adr/0008-subscription-target-model.md) — Draft; partial use (Q5 chat_id-only locked here; full polymorphic target deferred).
- [`docs/adr/0009-idempotency.md`](../adr/0009-idempotency.md) — Draft; primary input for BUG-022 + HTTP idempotency design.
- [`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md) — 7 principles, mandatory checklist.
- [`START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md`](START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md) — **format-precedent** for this prompt (~1200 lines).

---

## §2 — Scope

### What's in this sprint (locked)

**P-1 — Watchlist HTTP API** (F11 → REST):

- `POST /api/v1/watchlists` — subscribe (returns `{watchlist_id, created: bool, changed_fields: list[str]}`)
- `GET /api/v1/watchlists` — list current user's interests
- `GET /api/v1/watchlists/{id}` — single interest detail
- `DELETE /api/v1/watchlists/{id}` — unsubscribe (soft-delete; preserves `watch_matches`)
- `GET /api/v1/watchlists/{id}/matches` — match history (paginated, `since=ISO8601`)

**P-2 — Digest HTTP API** (F6 → REST):

- `POST /api/v1/digests` — subscribe
- `GET /api/v1/digests` — list
- `GET /api/v1/digests/{id}` — single detail
- `DELETE /api/v1/digests/{id}` — unsubscribe (delete subscription row, preserve audit trail elsewhere if applicable)

**ENH-9 — `workspace_id` on `subscribe_*`** (across all 4 surfaces):

- `subscribe_watchlist(... workspace_id: str | None = None)` + same for `subscribe_digest`.
- New optional column `watch_interests.workspace_id UUID NULL` FK to `workspaces.id` ON DELETE SET NULL (interest survives workspace deletion).
- Semantics: `workspace_id=None` → behaviour identical to today (no workspace association). `workspace_id=<valid>` → match scoring still uses explicit `channel_ids[]` (no auto-expansion in this sprint — deferred to Wave 2); the column is used for: (a) push-payload hyperlinks back to workspace dashboard, (b) future RBAC. `workspace_id=<unknown / foreign>` → 404-like `WorkspaceNotFound` (mirror F4-B Q2 EC2).
- Add to MCP + CLI + Bot + new HTTP surfaces.

**BUG-022 — `subscribe_*` idempotency** (per ADR 0009 Option C hybrid):

- Service-layer: `subscribe_watchlist` upsert on `(user_id, title)`; `subscribe_digest` upsert on `(owner_id, name)`. Return `{id, created: bool, changed_fields: list[str]}` on both.
- DB: Alembic adds `UNIQUE (user_id, title)` on `watch_interests` and `UNIQUE (owner_id, name)` on `digest_subscriptions` (asymmetry mirrors each table's existing schema — `WatchInterest.title`, `DigestSubscription.name`). Pre-migration cleanup: admin runbook step to dedupe existing duplicates per table (if any in prod).
- HTTP-layer: `Idempotency-Key` header middleware on the new P-1 / P-2 POST endpoints (new `idempotency_keys` table, 24h TTL, body-hash mismatch → 422). Scope intentionally narrow per Open Q-7 in §8 — broader rollout in a future PR.

### What's NOT in this sprint (deferred)

| Item | Why deferred | Where it goes |
|---|---|---|
| **BUG-015** (MCP `trigger_pipeline` silent no-op) | ADR 0007 dispatch contract decision deferred to step 3.1 | Wave 1 step 3.1 sprint, post-ADR-0007 ratify |
| **ENH-1 / ENH-2** (`trigger_topicization` / `trigger_link_topics` on MCP) | Same architectural blocker as BUG-015 | Step 3.1 sprint |
| **O-3 parity** (MCP write-tool asymmetry) | Same blocker | Step 3.1 sprint |
| **ADR 0007 ratification** (status Draft → Accepted) | Decision needs more evidence; step 3 doesn't pressure-test it | Step 3.1 planning sub-session |
| **Polymorphic target** (ADR 0008 Option B full implementation — channel_id / webhook_url) | Scope creep; step 3 ships `chat_id` shape; A4 webhook + Wave 1 step 4 channel publish go after | Wave 2A (A4-focused) + Wave 1 step 4 (shareable digest) respectively |
| **Channels CRUD on API** (P1 from prep doc — `POST /channels` etc.) | Out of P-1 / P-2 narrow scope; HEAD already has read GETs | Future parity sprint after Wave 1 |
| **F1 / F2 / F8 / F9 / F12** features | Backlog | `FUTURE_FEATURES.md` |
| **F4-B Sharing** (workspace_members M2M) | Wave 2C по signal'у A3 (Team) | Wave 2C |
| **Bot workspace UX** (slash-commands, natural-language switching) | Q3 = skip-MVP locked in F4-B Core | Future bot sprint per UX signal |
| **O-1 atomic `move_workspace_source`** | No signal accumulated | Wave 2 |
| **Long-running ops via job pattern** (`embed`, `link-topics` to MCP / Bot) | Step 3.1 + F8-B prereqs | Wave 2A / F8-B |
| **CLI gap closure** (A-1..A-13 from prep doc) | Not audience-A4-driven; separate hygiene pass | Future CLI parity sprint |

---

## §3 — Locked design decisions (Q1..Q9)

> These 9 decisions are **locked** in S1 planning sub-session
> 2026-05-21 and **cannot flip mid-sprint** without a new planning
> round-trip. Any substantive issue during execution → STOP, report,
> wait for new planning sub-session.

### Q1 — Auth model for HTTP API endpoints `[CONFIRMED 2026-05-21]`: **A (existing FastAPI `X-API-Key` contract via `resolve_current_user`)**

Reuse the existing FastAPI auth dependency
[`tg_parser/api/auth.py::resolve_current_user`](../../tg_parser/api/auth.py)
already wired into `GET /api/v1/topics`, `POST /api/v1/process`, etc. The
header is `X-API-Key: <api-key>` (verified `APIKeyHeader(name="X-API-Key")`
in `tg_parser/api/auth.py:24`), resolved to `CurrentUser` via
[`tg_parser/auth/resolvers.py`](../../tg_parser/auth/resolvers.py)
(`resolve_user_by_auth("api_key", hashed_key)`). All new P-1 / P-2
endpoints register `user: CurrentUser = Depends(resolve_current_user)` →
scope to caller's `user_id` automatically. No new auth surface; no new
header.

**Rejected:**
- `Authorization: Bearer <token>` style — not the project convention; would require new dependency, breaks parity with existing endpoints.
- OAuth (deferred to Wave 2A per audience-driven roadmap).

### Q2 — Idempotency `[CONFIRMED 2026-05-21]`: **C (hybrid per ADR 0009)**

- **Service layer (natural-key upsert):** asymmetric natural keys per
  table (mirrors Q6 naming):
  - `watch_interests`: `UNIQUE (user_id, title)` (table column is
    `user_id`; label field is `title`).
  - `digest_subscriptions`: `UNIQUE (owner_id, name)` (table column is
    `owner_id`; label field is `name`).

  Service layer: `subscribe_watchlist` does pre-flight
  `find_by_user_and_title(user_id, title)` → if exists, UPDATE mutable
  fields and return existing UUID with `created: false` +
  `changed_fields`. `subscribe_digest` mirrors with
  `find_by_owner_and_name(owner_id, name)`. Else INSERT. Race condition
  closes with DB `UNIQUE` constraint caught as `IntegrityError` → retry
  as UPDATE.
- **HTTP layer (`Idempotency-Key` header):** `Idempotency-Key:
  <client-uuid>` HTTP header optional on POST endpoints. New
  `idempotency_keys` table: `(key TEXT PK, user_id UUID FK,
  request_hash TEXT, response_body JSONB, created_at TIMESTAMPTZ
  DEFAULT now())` with 24h TTL via periodic cleanup. On repeated
  request: same key + same body → cached response; same key +
  different body → 422.
- **Cross-surface:** MCP / Bot / CLI rely on service-layer mechanism
  alone (no header equivalent). HTTP middleware is HTTP-only.

**Rationale:** ADR 0006 principle 4. ADR 0009 Option C analysis.

### Q3 — `workspace_id` semantics on `subscribe_*` `[CONFIRMED 2026-05-21]`: **A (optional FK, no auto-expansion in this sprint)**

`workspace_id: str | None = None` parameter on `subscribe_watchlist` /
`subscribe_digest` across all 4 surfaces.

**Storage (locked):**

- `watch_interests.workspace_id UUID NULL` FK → `workspaces.id` ON DELETE SET NULL.
- `digest_subscriptions.workspace_id UUID NULL` FK → `workspaces.id` ON DELETE SET NULL.
- Both columns nullable + additive; existing rows get `NULL` on migration.

**Semantics (locked):**

- `None` (default) → today's behaviour bit-for-bit (interest /
  subscription stored with `workspace_id IS NULL`). No regression for
  existing callers.
- Valid `workspace_id` (owned by user OR admin) → store FK. `channel_ids`
  still required (no auto-expansion to `workspace.channel_ids` —
  deferred to Wave 2 per Q7 / Q8 from F4-B Core). Used for:
  (a) push-payload hyperlinks to workspace dashboard (added in payload
  JSON), (b) future workspace-scoped RBAC (out of MVP).
- Unknown / foreign `workspace_id` → `WorkspaceNotFound` 404-like
  (mirror F4-B Q2 EC2; reuse `assert_workspace_access` helper from
  [`tg_parser/auth/ownership.py:70`](../../tg_parser/auth/ownership.py)).
- Workspace deletion → interest / subscription survives with
  `workspace_id` set to `NULL` (ON DELETE SET NULL).

**Rejected:**

- B (`workspace_id` replaces `channel_ids[]` — auto-expansion) → too
  big for this sprint; semantic ambiguity (what if workspace channels
  change after subscription? — covered explicitly in Wave 2).
- C (skip integration entirely) → ENH-9 signal already strong enough
  per [`mcp_testing/2026-05-15_claude_session/02-enhancements.md`](mcp_testing/2026-05-15_claude_session/02-enhancements.md).

### Q4 — API base path `[CONFIRMED 2026-05-21]`: **A (`/api/v1/*` + Stripe-style flat resource names)**

- `/api/v1/watchlists` (collection) + `/{id}` (single) + `/{id}/matches` (sub-resource).
- `/api/v1/digests` (collection) + `/{id}`.
- Pluralization: lowercase plural English (mirror existing
  `/api/v1/users`, `/api/v1/channels`, `/api/v1/topics`).

**Rejected:**

- `/api/v1/watchlist` (singular) — inconsistent with existing endpoints.
- `/api/v1/f11/watchlists` (feature-prefixed) — leaks internal codename.
- Nested under user (`/api/v1/users/{me}/watchlists`) — adds verbosity
  with no benefit; auth already scopes to user.

### Q5 — HTTP versioning `[CONFIRMED 2026-05-21]`: **A (v1 namespace; breaking changes → v2 future)**

Endpoints ship under `/api/v1/*` prefix (matches existing API). Any
future breaking change to subscribe payload shape (e.g., when ADR 0008
polymorphic `target` lands) introduces `/api/v2/*` parallel surface;
`/api/v1/*` deprecates per separate ADR (TBD).

In this sprint specifically: target field stays `chat_id: int` (per Q6);
adding `workspace_id` is **additive** (optional field, default
`None`) — not a breaking change.

### Q6 — Target field shape in this sprint `[CONFIRMED 2026-05-21]`: **A (chat_id only; ADR 0008 polymorphic deferred)**

`POST /api/v1/watchlists` request body — mirror existing
`subscribe_watchlist` MCP signature (`title` not `name`; see
`tg_parser/mcp_server.py:2728-2736`, `tg_parser/domain/models.py:721`
`WatchInterest.title: str = Field(min_length=1, max_length=300)`):

```json
{
  "title": "string",
  "channel_ids": ["string"],
  "chat_id": 123456789,
  "keywords": ["string"],
  "description": "string",
  "exclude_keywords": ["string"],
  "threshold": 0.6,
  "workspace_id": null
}
```

`POST /api/v1/digests` request body — mirror existing `subscribe_digest`
MCP signature (`name`; see `tg_parser/mcp_server.py:2477-2486`,
`tg_parser/domain/models.py:638` `DigestSubscription.name: str =
Field(min_length=1, max_length=200)`):

```json
{
  "name": "string",
  "channel_ids": ["string"],
  "chat_id": 123456789,
  "cron_expression": "0 9 * * *",
  "timezone": "UTC",
  "format": "summary",
  "language": "ru",
  "workspace_id": null
}
```

> **Naming asymmetry — locked, not unified in this sprint.** Watchlist's
> label field is `title` (F11 surface convention); digest's is `name`
> (F6 surface convention). Both domain models pre-date Wave 1 step 3 and
> are exposed across MCP / CLI / Bot already. Unifying them would be a
> breaking change for existing callers — deferred. HTTP API mirrors each
> surface's existing field for backward-compat shim symmetry. Test plan
> in §5 + idempotency natural-key in Q2 explicitly carry this asymmetry.

**No `webhook_url`, no `channel_id` target, no polymorphic `target` discriminator.**
ADR 0008 Option B full implementation deferred to Wave 2A (A4 webhook
enabler) + Wave 1 step 4 (channel publish enabler — same shape, but
focused on aiogram `send_message(channel_id, ...)`).

**Rationale:** Step 3 scope discipline. Adding the polymorphic target
in this sprint risks scope creep — better to ship narrow + iterate.
HTTP versioning (Q5) means v2 can flip the shape later without
breaking v1 callers.

### Q7 — Response shape `[CONFIRMED 2026-05-21]`: **A (Pydantic models + standard envelope)**

Success response (POST):

```json
{
  "watchlist_id": "uuid",
  "created": true,
  "changed_fields": []
}
```

On idempotent re-call: `created: false`, `changed_fields: ["keywords"]`
(or empty list if true no-op).

Success response (GET single): full domain model (`WatchInterest` /
`DigestSubscription` Pydantic).

Success response (GET list): `{"items": [...], "total": N}` (offset/limit
pagination via `?offset=&limit=` query, default `limit=50`).

Success response (DELETE): `204 No Content`.

Error response (all endpoints): existing FastAPI `HTTPException` shape
(consistent with rest of API):

```json
{
  "detail": "human-readable message",
  "error_class": "WorkspaceNotFound | ValidationError | ConflictError | ..."
}
```

**Pydantic models:** add new request/response models to the existing
flat schemas module [`tg_parser/api/schemas.py`](../../tg_parser/api/schemas.py)
(current repo convention — one flat schemas file, NOT a `schemas/`
package). New classes: `WatchlistCreateRequest`, `WatchlistResponse`,
`WatchlistListResponse`, `WatchlistMatchItem`, `WatchlistMatchesResponse`,
`DigestCreateRequest`, `DigestResponse`, `DigestListResponse`. Mirror
domain models (`WatchInterest`, `DigestSubscription`) + explicit
request / response separation per existing `ProcessRequest` /
`ProcessResponse` precedent. If execution sub-session prefers splitting
into `tg_parser/api/schemas/` package — that is a small refactor outside
this sprint's locked scope and should be flagged as a separate hygiene
PR.

### Q8 — DELETE semantics `[CONFIRMED 2026-05-21]`: **A (soft for watchlists, hard for digests)**

Mirror existing service-layer behaviour:

- **`DELETE /api/v1/watchlists/{id}`** → `watchlist_service.unsubscribe(id)` which today soft-deletes (`is_active = False`); preserves `watch_matches`. Match-history endpoint `GET /watchlists/{id}/matches` continues to serve historical matches for soft-deleted interests (read-only).
- **`DELETE /api/v1/digests/{id}`** → `digest_service.unsubscribe(id)` which today **deletes** the row (no audit equivalent for digest sends — they live as separate observability metrics). Hard delete.

Both endpoints: 204 No Content on success. 404 on unknown id (or
foreign — 404-like, never 403 to not leak existence; mirror F4-B
pattern).

### Q9 — Test surface `[CONFIRMED 2026-05-21]`: **A (FastAPI TestClient + service-layer unit + idempotency contract)**

Test files (new):

- `tests/test_api_watchlists.py` — FastAPI TestClient for all 5 P-1 endpoints; auth happy-path (valid `X-API-Key`) / missing key (401 when `api_key_required=True`) / invalid key (403) / cross-tenant (404-like via `WorkspaceNotFound`); `workspace_id` semantics (None / valid / unknown); idempotency natural-key (`title`-based) + `Idempotency-Key` header.
- `tests/test_api_digests.py` — same for P-2 endpoints (idempotency natural-key is `name`-based for digests).
- `tests/test_subscribe_idempotency.py` — service-layer for `subscribe_watchlist` (key = `(user_id, title)`) and `subscribe_digest` (key = `(owner_id, name)`); same-key-different-args → UPDATE; same-key-same-args → no-op; race-condition (asyncio.gather); shared across all 4 surfaces.
- `tests/test_idempotency_key_middleware.py` — HTTP `Idempotency-Key` middleware (cache hit / cache miss / body-hash mismatch 422 / TTL expiry; only 2xx responses cached — 4xx/5xx pass through; R-2 risk mitigation).
- `tests/test_watchlist_workspace_id.py` — ENH-9 across MCP / Bot / CLI / HTTP — `workspace_id` None / valid / unknown / foreign; payload includes `workspace_id` link when set; workspace deletion → `workspace_id` becomes NULL (ON DELETE SET NULL FK).

Approx **40–50 new tests** across these files. Mirror F4-B Core test pyramid density.

**Rejected:** end-to-end testcontainers test (overkill for this scope;
covered by existing CI integration smoke).

---

## §4 — ADR draft pointers

| ADR | Status | Role in this sprint |
|---|---|---|
| [`docs/adr/0007-mcp-scheduler-dispatch.md`](../adr/0007-mcp-scheduler-dispatch.md) | **Draft** | Reference only; **NOT** ratified in this sprint. Step 3.1 decision. |
| [`docs/adr/0008-subscription-target-model.md`](../adr/0008-subscription-target-model.md) | **Draft** | Partial use: chat_id-only target locked (Q6). Polymorphic target deferred. Final shape locked in execution sub-session via Q-and-A on `target` field. |
| [`docs/adr/0009-idempotency.md`](../adr/0009-idempotency.md) | **Draft → likely Accepted in execution sub-session** | Primary input for Q2. Service-layer + HTTP-layer mechanisms both in scope. ADR may flip to Accepted at end of sprint if no surprises. |

Each ADR draft contains options matrix + preliminary recommendation.
Execution sub-session should re-read each draft, then either:

1. Promote to **Accepted** if implementation aligns with preliminary
   recommendation (most likely for 0009).
2. Add a new draft entry with «decision in execution sub-session
   2026-05-XX» if the implementation deviates (most likely for 0008
   where chat_id-only is a deliberate narrow choice).
3. Keep as Draft for next planning round-trip (most likely for 0007).

---

## §5 — Test plan

### Test pyramid

**Service-layer unit (idempotency core):**

- `subscribe_watchlist(user, title, args)` × `subscribe_watchlist(user, title, args)` → same `watchlist_id`, `created: false`, `changed_fields: []` (key: `(user_id, title)`).
- `subscribe_digest(user, name, args)` × `subscribe_digest(user, name, args)` → same `digest_id`, `created: false`, `changed_fields: []` (key: `(owner_id, name)`).
- Same key, different args → same id, `created: false`, `changed_fields: ["description", "keywords"]` (only fields that actually changed).
- Race condition (asyncio.gather 10 parallel inserts with same key) → exactly one CREATE wins, others UPDATE; no `IntegrityError` propagated; final state deterministic.
- Different key → different ids, both `created: true`.

**HTTP contract (FastAPI TestClient):**

- `POST /api/v1/watchlists` happy-path with `X-API-Key: <valid>` → 201 Created + body shape.
- `POST /api/v1/watchlists` without `X-API-Key` header AND `api_key_required=True` → 401.
- `POST /api/v1/watchlists` with invalid `X-API-Key` → 403.
- `POST /api/v1/watchlists` with cross-tenant `workspace_id` → 404-like (`error_class=WorkspaceNotFound`).
- `POST /api/v1/watchlists` with `Idempotency-Key: foo` → 201; same body + key → cached response, no second DB write; same key, different body → 422.
- `GET /api/v1/watchlists` → list scoped to current user (`X-API-Key`-resolved).
- `GET /api/v1/watchlists/{id}` foreign id → 404-like (never 403, mirror F4-B pattern).
- `DELETE /api/v1/watchlists/{id}` → 204; matches preserved (soft-delete).
- `GET /api/v1/watchlists/{id}/matches?since=ISO8601` → paginated list.
- Same matrix for `/api/v1/digests` (without `/matches`; DELETE is hard-delete per Q8).

**Workspace scoping (ENH-9):**

- `subscribe_watchlist(workspace_id=<my-ws>)` → row written with FK.
- `subscribe_watchlist(workspace_id=<other-user-ws>)` → 404-like.
- `subscribe_watchlist(workspace_id=<deleted-ws>)` → 404-like.
- After `delete_workspace(ws)`, existing interest with that workspace_id → `workspace_id` becomes NULL (ON DELETE SET NULL FK).

**Backward-compat:**

- Existing MCP `subscribe_watchlist(name, channel_ids, chat_id)` without `workspace_id` arg → identical row shape to today's behaviour (workspace_id NULL).
- Existing CLI `tg-parser watchlist add ...` without `--workspace-id` flag → same.
- Existing Bot `subscribe_watchlist` tool invocation → same.

### Pre-flight gate-1 (before starting sprint)

```bash
cd /Users/alexanderefimov/TG_parser
git log -1 --format='%H %s' main
# Expected: 4d567ce docs(bug-log): backfill BUG-018/017/023 closure SHAs post-PR #87 merge
# (post-S2 baseline; pre-flight 2026-05-21 confirmed S1 PR #86 + S2 PR #87 landed)

# 24h watch on tg_parser_bot (mirror F4-B Core pre-flight)
ssh prod 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query?query=up{service=\"bot\"}" | python3 -m json.tool'
# Expected: result vector, value=1

ssh prod 'docker logs --since 72h tg_parser_bot 2>&1 | grep -cE "confirm_flow_mismatch|gemini_empty|gemini_no_candidates|gemini_blocked|gemini_api_error"'
# Expected: 0

# Local stack + baseline
docker compose ps  # tg_parser_postgres healthy
docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser \
  -c "SELECT * FROM alembic_version_ingestion;"
# Expected: e9f0a1b2c3d5 (F4-B Core head, will be down_revision for ENH-9 migration)

.venv/bin/pytest -q --tb=line | tail -5
# Expected: 2147 passed, 258 skipped, 0 failed (post-S2 baseline at SHA 4d567ce)
```

### Quality bar

- All new tests PASS in default mode + Postgres mode (TEST_POSTGRES gate).
- Baseline + ~40–50 new tests; **0 regressions** на existing tests (especially `tests/test_f4_*.py`, `tests/test_f4b_*.py`, `tests/test_f11_*.py`, `tests/test_f6_*.py`).
- `ruff format` + `ruff check .` clean.
- CI green (5/5 jobs).
- Pre-merge alembic upgrade smoke: `tg-parser db check --db ingestion` returns clean.
- Pre-merge alembic downgrade smoke: roll back ENH-9 migration → `subscribe_*` still works on `workspace_id` column dropped (graceful degradation).

---

## §6 — Acceptance signals + 24h watch

### Acceptance criteria (sprint closure)

1. **All 5 P-1 endpoints** respond with shapes per Q7. End-to-end
   `curl` smoke against production VPS (after deploy):
   `POST /api/v1/watchlists`, `GET /api/v1/watchlists`, `GET .../{id}`,
   `DELETE .../{id}`, `GET .../{id}/matches`.
2. **All 4 P-2 endpoints** respond with shapes per Q7. Same smoke.
3. **ENH-9 workspace_id** present in DB on at least one production
   subscription created with explicit `workspace_id` (operator-driven
   smoke).
4. **BUG-022 idempotency closed** — production `curl` smoke: same body
   POST'd twice with same `Idempotency-Key` → identical response;
   no duplicate row.
5. **MCP / Bot / CLI surfaces** continue to work on legacy `chat_id`
   shape (regression-guarded test + manual smoke).
6. **CHANGELOG entry** + **DONE marker** (`REVIEW_2026-05-XX_WAVE1_STEP3_DONE.md`)
   landed before PR merge.

### 24h post-deploy watch (mirror F4-B Core pattern)

**Container target:** `tg_parser_bot` (existing) + `tg_parser` (API endpoint emit).

**Metrics to watch:**

- `tg_idempotency_keys_hit_total{result=hit|miss|mismatch}` — new
  counter; expect `hit` non-zero only if external clients actually
  retry. `mismatch` should be very rare (0 in normal traffic).
- `tg_watchlist_subscribe_total{result=created|updated|nochange}` — new
  counter on service layer.
- `tg_digest_subscribe_total{result=...}` — same for digests.
- Existing F11 / F6 metrics (`tg_watchlist_score`, `tg_digest_runs_total`)
  — should not regress.
- HTTP error rate (`tg_api_requests_total{status=5xx}` on new
  endpoints) — must be 0 over 24h baseline.

**Watch window:** open at deploy timestamp, close 24h later. Per-source
state via `get_pipeline_status` continues to behave (regression guard).

### DONE marker template

After 24h watch GREEN, produce `docs/notes/REVIEW_2026-05-XX_WAVE1_STEP3_DONE.md`
mirroring [`REVIEW_2026-05-14_WAVE1_STEP2_DONE.md`](REVIEW_2026-05-14_WAVE1_STEP2_DONE.md):

- § 1: closed bugs / features (BUG-022 → closed; ENH-9 → landed; P-1
  / P-2 → landed).
- § 2: acceptance signals table.
- § 3: post-watch state (per-endpoint health).
- § 4: known partials (none expected; if surfaces emerge → file new
  bug, separate sprint).
- § 5: cross-references.
- § 6: lessons learned.
- § 7: pre-next-step (Wave 1 step 4 — shareable digest) readiness.

---

## §7 — Out-of-scope / follow-ups

> Same hard anti-scope discipline as F4-B Core sprint. Any UX-soft
> pressure during execution → STOP, log signal as observation in
> `PARITY_DECISION_TRACKING.md` (or `BUG_LOG.md` if it's a real bug),
> do **not** flip scope.

1. **BUG-015 / ENH-1 / ENH-2 / O-3** — Wave 1 step 3.1 sprint, post ADR 0007 ratify.
2. **ADR 0007 ratify** — Wave 1 step 3.1 planning sub-session.
3. **ADR 0008 polymorphic target** (channel_id / webhook_url) — Wave 1 step 4 (channel publish) + Wave 2A (webhook for A4).
4. **F4-B Sharing** — Wave 2C по A3 signal.
5. **Bot workspace UX** — future bot sprint per UX signal.
6. **O-1 atomic `move_workspace_source`** — Wave 2.
7. **Long-running ops job pattern** (`embed`, `link-topics` on MCP/Bot) — Wave 2A / F8-B.
8. **CLI gap A-1..A-13** — separate CLI parity sprint after Wave 1.
9. **OAuth for MCP / HTTP API** — Wave 2A.
10. **Webhook delivery semantics** (retry policy, HMAC, dead-letter) — Wave 2A (depends on ADR 0008 Option B implementation).

---

## §8 — Locked decisions appendix

### Karpathy 7-checklist (ADR 0006)

| Contract \ Principle | 1. Persistent | 2. Provenance | 3. Cheap retrieval | 4. Idempotency | 5. Living loop | 6. Observability | 7. Graceful degradation |
|---|---|---|---|---|---|---|---|
| **HTTP API P-1 / P-2 endpoints** | PASS — thin wrapper over existing services; new Pydantic schemas in `api/schemas/` | PASS — payloads carry `subscription_id`, `user_id`, `created_at` | PASS — pure SQL via service layer; no LLM | PASS (condition) → service-layer natural-key upsert + HTTP `Idempotency-Key` per Q2 | PASS — endpoints surface; not pipeline | PASS (condition) → emit `tg_idempotency_keys_hit_total`, `tg_*_subscribe_total{result}` | PASS — auth missing → 401; foreign workspace → 404; idempotency mismatch → 422 |
| **ENH-9 `workspace_id` FK** | PASS — new column on `watch_interests` + `digest_subscriptions` (nullable) | PASS — payload includes workspace_id link when set | PASS — single FK lookup | PASS — additive nullable column; NULL = today's behaviour | PASS — workspace deletion → SET NULL (interest survives) | PASS (condition) → emit `tg_watchlist_workspace_subscribe_total{workspace_set}` | PASS — invalid workspace_id → 404-like; deleted workspace → SET NULL graceful |
| **BUG-022 service-layer upsert** | PASS — uses existing tables; new UNIQUE constraints on `(user_id, title)` for watch_interests and `(owner_id, name)` for digest_subscriptions | PASS — `created_at` immutable on UPDATE; `updated_at` advances | PASS — single SELECT + INSERT-or-UPDATE | PASS (core fix) | PASS — no pipeline changes | PASS (condition) → emit `tg_*_subscribe_total{result=created|updated|nochange}` | PASS — race condition closes via `UNIQUE` constraint catch on `IntegrityError` → retry as UPDATE |
| **HTTP `Idempotency-Key` middleware** | PASS — new `idempotency_keys` table (explicit, not metadata dict) | PASS — `request_hash` + `response_body` captured | PASS — single PK lookup | PASS (definition) | PASS — TTL cleanup job (daily) | PASS (condition) → `tg_idempotency_keys_hit_total`, `tg_idempotency_keys_table_size` | PASS — key collision with different body → 422 not 500; TTL expiry → first request semantics |

**Conditions summary** (deliverables in sprint phases):

- Prometheus exporters: `tg_idempotency_keys_hit_total{result}`,
  `tg_watchlist_subscribe_total{result}`,
  `tg_digest_subscribe_total{result}`,
  `tg_watchlist_workspace_subscribe_total{workspace_set}`.
- structlog binds: `user_id`, `workspace_id`, `subscription_id`,
  `idempotency_key` on all subscribe / unsubscribe entry points.

### Open questions for execution sub-session `[OPEN]`

> Planning sub-session 2026-05-21 did **NOT** lock these. Execution
> sub-session must address them before implementation.

1. **`changed_fields` exact shape** — list of column names? List of
   Pydantic field names? Diff with old / new values? Lean: list of
   Pydantic field names (matches API surface).
2. **`idempotency_keys` cleanup mechanism** — periodic scheduler job
   vs lazy-on-read deletion vs cron container? Lean: periodic
   scheduler job (every 1h, runs alongside existing scheduler tick).
3. **`workspace_id` payload-hyperlink format** — what URL pattern? We
   don't have a workspace dashboard URL today (no Web in Wave 1).
   Lean: include `workspace_id` UUID in payload only; URL formation
   deferred to Wave 2B (Web).
4. **`get_watchlist_matches` filtering semantics** — `since: datetime`
   only or also `until: datetime`, `min_score: float`? Lean: `since`
   only for v1; add others on signal.
5. **Existing duplicate cleanup for `UNIQUE` constraints** — manual
   admin step? Pre-migration script? Lean: admin runbook step (two
   queries — `SELECT user_id, title, count(*) FROM watch_interests
   GROUP BY user_id, title HAVING count(*) > 1` and `SELECT owner_id,
   name, count(*) FROM digest_subscriptions GROUP BY owner_id, name
   HAVING count(*) > 1`) → manual review → DELETE duplicates → run
   migration. If production has 0 duplicates (likely, given small user
   base), skip step.
6. **Bot tool surface for ENH-9 workspace_id** — does the bot expose
   workspace_id as a tool argument? Bot users currently don't
   workspace-switch (Q3 from F4-B Core = skip-MVP). Lean: yes, the
   `subscribe_watchlist` / `subscribe_digest` bot tools accept
   workspace_id as optional argument (user can pass it from MCP
   workflow); but bot's free-form prompt doesn't expose it
   conversationally. Compatible with Q3 from F4-B Core (no workspace
   UX in bot).
7. **HTTP `Idempotency-Key` middleware scope** — apply to all POST
   endpoints (including `/api/v1/process`, `/api/v1/export`) or only
   the new subscribe endpoints? Lean: only new subscribe endpoints in
   this sprint; broaden in future PR. Trade-off accepted: smaller
   blast radius now.
8. **DELETE for unsubscribe + idempotency** — `DELETE /api/v1/watchlists/{id}`
   called twice — second returns 204 or 404? Lean: 204 (soft-delete
   already happened; idempotent).

### Risk register

| ID | Risk | Severity | Likelihood | Mitigation |
|---|---|---|---|---|
| R-1 | ENH-9 migration breaks existing F11 / F6 service tests | Medium | Low | Migration строго additive (nullable column). Service-layer tests should pass unchanged. New tests cover workspace_id path explicitly. |
| R-2 | HTTP `Idempotency-Key` middleware accidentally caches errors (500) | Medium | Low | Cache only 2xx responses; 4xx/5xx pass through without caching. Explicit test. |
| R-3 | BUG-022 pre-migration cleanup misses a duplicate → migration fails on prod | High | Very Low | Pre-migration smoke query + manual review. If duplicates found → admin runbook DELETE step before migration. Likely 0 duplicates given small user base today. |
| R-4 | `Idempotency-Key` body-hash false-positive (e.g. serialization order) | Low | Low | Canonical JSON serialization (sorted keys) before hashing. Explicit test for hash stability across Pydantic re-serializations. |
| R-5 | ADR 0008 polymorphic target lands in execution sub-session anyway (scope creep) | High | Low | Hard anti-scope: chat_id-only locked. If signal emerges → STOP, document as observation, separate sprint. |
| R-6 | F11 / F6 service-layer signatures inadvertently change | Medium | Low | Service signatures stay backward-compat. New args additive optional. Existing tests catch drift. |
| R-7 | Tests with `Idempotency-Key` flaky due to clock-based TTL | Low | Medium | Use `freezegun` or `time-machine` for TTL tests; not real-time. |
| R-8 | API endpoint auth resolver fails on edge cases (admin token, anonymous, expired) | Medium | Very Low | Reuse existing auth surface (Q1); auth tests already comprehensive (F4-A coverage). Add new tests for cross-tenant edge case. |

### PR shape — Single PR + 4–5 atomic commits

| Commit | Scope | LOC est. | Tests | Phase |
|---|---|---|---|---|
| **1/4** `feat(parity): ENH-9 + BUG-022 service-layer foundation` | Alembic migration (workspace_id FK on both tables + `UNIQUE (user_id, title)` on watch_interests + `UNIQUE (owner_id, name)` on digest_subscriptions + idempotency_keys table); domain models; service-layer upsert (`find_by_user_and_title` / `find_by_owner_and_name`); `subscribe_*` signatures across all 4 surfaces (add `workspace_id`); existing tests updated for new return shape | ~300–400 | ~15 | Foundation |
| **2/4** `feat(parity): P-1 Watchlist HTTP API` | 5 endpoints + Pydantic schemas + auth wiring + tests | ~250–350 | ~12 | P-1 |
| **3/4** `feat(parity): P-2 Digest HTTP API` | 4 endpoints + schemas + tests | ~200–300 | ~10 | P-2 |
| **4/4** `feat(parity): Idempotency-Key HTTP middleware + cleanup job + docs` | Middleware + table + tests + Prometheus metrics + USER_GUIDE / MCP_AGENT_GUIDE / CHANGELOG / DONE marker stub | ~250–350 | ~13 | HTTP infra + docs |

**Optional 5th commit:** if scope creeps (e.g. CLI subcommand
refactor needed for `--workspace-id` flag consistency) → split into
5/5. Mirror F4-B Core flexibility.

**Total estimate:** ~1000–1400 LOC + ~40–50 new tests.

### Pre-flight gate-1 (anti-scope reminder)

- M-15 docs hygiene already landed (PR #85). **Do not** touch unrelated docs (out-of-scope).
- BUG-013/14/24/14B already closed (PRs #79/#84). **Do not** re-investigate.
- BUG-016 closed (PR #81). **Do not** re-touch docker-compose.yml unless ENH-9 explicitly needs it (likely not).
- **BUG-017 / BUG-018 / BUG-023 already closed in S2 (PR [#87](https://github.com/AlexEfimov/TG_parser/pull/87) SHA `2e9213c`, 2026-05-21).** **Do not** re-touch `tg_parser/processing/topicization.py` / `tg_parser/services/topicization_service.py` / `tg_parser/services/pipeline_service.py` / `tg_parser/cli/app.py` unless ENH-9 explicitly needs it (likely not — S2 paths are orthogonal to `subscribe_*` paths).
- F4-B Core 100% landed. **Do not** revisit Q1–Q8 decisions from F4-B Core sprint.
- **S1 planning artifacts already landed (PR [#86](https://github.com/AlexEfimov/TG_parser/pull/86) SHA `d7a18f9`).** This prompt + ADR drafts 0007/0008/0009 + drift cleanup are baseline; do **not** re-touch them mid-execution unless an open Q resolution requires it.

---

## §9 — Cross-links footer

| Документ | Зачем |
|----------|-------|
| **Parent planning sub-session (S1):** this prompt + ADR drafts 0007/0008/0009 + drift cleanup | Source of truth for locked decisions Q1–Q9 |
| [`REVIEW_2026-05-14_WAVE1_STEP2_DONE.md`](REVIEW_2026-05-14_WAVE1_STEP2_DONE.md) | DONE marker предыдущего шага (F4-B Core) — pre-flight gate-1 reference |
| [`PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md) § 1 + § 3 | P-1 / P-2 pre-references + O-1 / O-3 observations |
| [`PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md`](PLANNING_SURFACE_COVERAGE_PARITY_PREP_2026-05-02.md) | Full inventory + § 4.B (API gaps B-10 / B-11) + § 6 P2 (F6 + F11 API CRUD combo) |
| [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1 § 8](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) | Wave 1 step 3 description + audience-driven priority |
| [`docs/adr/0007-mcp-scheduler-dispatch.md`](../adr/0007-mcp-scheduler-dispatch.md) | Draft — reference only; step 3.1 decision |
| [`docs/adr/0008-subscription-target-model.md`](../adr/0008-subscription-target-model.md) | Draft — Q6 partial use (chat_id-only); full target model deferred |
| [`docs/adr/0009-idempotency.md`](../adr/0009-idempotency.md) | Draft → primary input for Q2; likely Accepted post-sprint |
| [`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md) | 7-checklist for Karpathy compliance |
| [`START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md`](START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md) | Format-precedent for this prompt structure |
| [`BUG_LOG.md` § BUG-022](BUG_LOG.md) | Idempotency bug — closes in this sprint |
| [`BUG_LOG.md` § BUG-015](BUG_LOG.md) | Architectural blocker — explicitly NOT in this sprint |
| [`HANDOFF_POST_MCP_INTAKE_2026-05-15.md`](HANDOFF_POST_MCP_INTAKE_2026-05-15.md) | Untracked; ENH-9 + BUG-022 scope evidence — **do NOT** include as canonical ref in code/test commits |
| [`docs/notes/mcp_testing/2026-05-15_claude_session/02-enhancements.md` § ENH-9 § O-7](mcp_testing/2026-05-15_claude_session/02-enhancements.md) | Tracked artifacts for ENH-9 + idempotency observation |

---

## §10 — После Wave 1 step 3 — что дальше

Согласно audience-driven Wave 1 sequence per
[`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md):

1. **Wave 1 step 3.1 — Architectural follow-up** (~0.5–1 сессия) —
   ADR 0007 ratify + BUG-015 + ENH-1 + ENH-2 + O-3 fix per chosen
   dispatch contract option.
2. **Wave 1 step 4 — Shareable Digest via TG-channel** (~0.3 сессии).
   Extension F6: `subscribe_digest(..., publish_to_channel="@my_digest")`.
   Builds on ADR 0008 polymorphic target lane.
3. **Wave 1.5 Operational Dogfooding** (parallel) — daily TG_parser
   use + light external validation (A4 AI integrators with HTTP API).
4. **Wave 1 closure** — `REVIEW_2026-05-XX_WAVE1_DONE.md` + Decision
   Point per § 5.3 strategy.

**Совокупно:** Wave 1 step 3 закрывает audience A4 (AI Agent Builder)
through HTTP API surface — external clients now have full CRUD over
watchlist + digest without MCP-only dependency. A6 (Domain Curator)
unlocks через ENH-9 workspace context — curators can subscribe
workspace-aware interests. After step 3 + step 4, продукт имеет полный
solo-полированный цикл с external HTTP integration surface.

---

## §11 — История промпта

| Дата | Изменение |
|------|-----------|
| 2026-05-21 | Первая версия. Создана planning sub-session S1 (parent: doc-drift cleanup + Wave 1 step 3 planning). Locks Q1–Q9 (auth = existing FastAPI bearer; idempotency = hybrid Option C; workspace_id = optional FK no auto-expansion; base path = `/api/v1/*` plural; versioning = v1; target = chat_id only; response = Pydantic + envelope; DELETE = soft watchlist, hard digest; tests = TestClient + service unit + idempotency contract). ADR 0007/0008/0009 drafts produced in same sub-session as reference inputs. PR shape: Single PR + 4 atomic commits (~1000–1400 LOC + ~40–50 new tests). 8 OPEN questions explicitly flagged for execution sub-session. Anti-scope reminder: BUG-015 / ENH-1 / ENH-2 / O-3 NOT in this sprint (step 3.1); polymorphic target NOT in this sprint (Wave 1 step 4 + Wave 2A). |
| 2026-05-21 (pre-flight) | Pre-flight S3 update. §1 baseline дополнен post-S2 HEAD `4d567ce` + ссылками на PR #86 (S1 planning) + PR #87 (S2 quick-wins, BUG-017/018/023 closed). §5 pre-flight gate-1 expected SHA `9068cbf` → `4d567ce`, expected baseline `~2150 passed` → `2147 passed, 258 skipped` (post-S2). §8 anti-scope reminder дополнен notes: BUG-017/018/023 closed in S2 (do not re-touch S2 paths — orthogonal to `subscribe_*`); S1 planning artifacts merged (do not re-touch this prompt + ADR drafts mid-execution). Q1–Q9 locked decisions unchanged. No code paths invalidated. |
