# Sprint Wave 1 step 4 — Shareable Digest (ADR 0008 implementation, target model across 4 surfaces)

> ✅ **Planning landed 2026-05-23** — Wave 1 step 4 sprint prompt
> produced by the formalization sub-session that closed
> [`PLAN_WAVE1_STEP4_2026-05-23.md`](PLAN_WAVE1_STEP4_2026-05-23.md)
> § 7 Q1–Q4 + Q3-under (X1). ADR 0008 promoted Draft → Accepted in
> the same session. Strategy § 5.4 amended (webhook → Wave 2A).
> Companion checklist: [`CHECKLIST_WAVE1_STEP4_2026-05-23.md`](CHECKLIST_WAVE1_STEP4_2026-05-23.md).
>
> Execution sub-session opens in a fresh chat after the user reviews
> this prompt and confirms scope. **Anti-scope items (§ 5) are HARD** —
> any UX-soft pressure during execution → STOP, log as a new
> under-question, do **not** flip scope.

---

## §0 — Context + locked decisions

### Wave 1 state recap

* Step 1 — Bot UX hardening — DONE (REVIEW [`REVIEW_2026-05-08_WAVE1_STEP1_DONE.md`](REVIEW_2026-05-08_WAVE1_STEP1_DONE.md)).
* Step 2 — F4-B Core Workspaces — DONE (REVIEW [`REVIEW_2026-05-14_WAVE1_STEP2_DONE.md`](REVIEW_2026-05-14_WAVE1_STEP2_DONE.md)).
* Step 3 — Surface Parity (P-1 watchlist HTTP + P-2 digest HTTP + ENH-9 `workspace_id` + BUG-022 idempotency, ADR 0009 Accepted) — DONE (REVIEW [`REVIEW_2026-05-21_WAVE1_STEP3_DONE.md`](REVIEW_2026-05-21_WAVE1_STEP3_DONE.md)).
* Step 3.1 — MCP HTTP dispatch (ADR 0007 Accepted, BUG-015 closed) — DONE (rolled into step 3 REVIEW § 1, deploy `b875faf`).
* BUG-028 (digest cron `PromptLoader` None-string regression) — RESOLVED via PR [#92](https://github.com/AlexEfimov/TG_parser/pull/92) squash `26d03a5`, deployed 2026-05-23 ≈19:23Z, DONE-marker commit `668946e`.
* **Current `main` HEAD:** `668946e` (clean working tree pre-step-4).
* ADR status board: 0006 Accepted (2026-05-02), 0007 Accepted (2026-05-22), **0008 Accepted (2026-05-23, this planning sub-session)**, 0009 Accepted (2026-05-22).

### Authoritative scope source

[`PLAN_WAVE1_STEP4_2026-05-23.md`](PLAN_WAVE1_STEP4_2026-05-23.md) (committed in this formalization session). § 4.1 Candidate A locked + § 7 Q1–Q4 + Q3-under (X1) resolved + § 8.1 step 4.1 scope-lock recorded.

### Locked decisions (compact form)

| ID | Decision | Source |
|---|---|---|
| **Q1 — ADR 0008 target model** | **Option B (polymorphic discriminator).** Discriminated union `target: {kind: chat \| channel, chat_id \| channel_id}` per Pydantic + Postgres enum. LOC/session estimate **~500–800 LOC, ~1.5–2 sessions**. | [PLAN § 7 Q1](PLAN_WAVE1_STEP4_2026-05-23.md), [ADR 0008 § Recommendation](../adr/0008-subscription-target-model.md) |
| **Q2 — webhook target** | **Defer to Wave 2A, NO enum reservation in step 4.** Primary `target_kind` enum ships as **`('chat', 'channel')` only**. Wave 2A adds `webhook` via additive `ALTER TYPE … ADD VALUE 'webhook'` + new `TargetWebhook` variant — fully non-breaking. | [PLAN § 7 Q2](PLAN_WAVE1_STEP4_2026-05-23.md), [ADR 0008 § Recommendation](../adr/0008-subscription-target-model.md), [Strategy § 5.4 Wave 2A](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) |
| **Q3 — Bot UX cluster (BUG-025/026/027)** | **Defer to step 4.1 sub-sprint with scope-lock.** Mirror step 3 → step 3.1 precedent. Step 4.1 = BUG-025 (Layer A+B) + BUG-026 (Option A) + BUG-027 (Layer A+B+C); one `prompts/bot.yaml` v1.7.0 → v1.8.0 bump. **Step 4.1 planning is a separate future session** (NOT this sprint). | [PLAN § 7 Q3](PLAN_WAVE1_STEP4_2026-05-23.md), [PLAN § 8.1](PLAN_WAVE1_STEP4_2026-05-23.md) |
| **Q3-under (X1) — step 4 prompt touch** | Step 4 PR DOES touch `prompts/bot.yaml`, but **ONLY a new dedicated `target_kind_semantics` section (≤15 lines)** covering kind=chat vs kind=channel disambiguation + backward-compat fallback semantics. **No other prompt sections touched.** Bump: current **v1.6.0 → v1.7.0** (rebased from user-supplied v1.4.0 → v1.5.0 because `prompts/bot.yaml` already at v1.6.0 per `41a925c`). If structural need surfaces during execution → flag as new under-question, **do NOT silently expand prompt scope** (BUG-029-class risk). | [PLAN § 7 Q3-under (X1)](PLAN_WAVE1_STEP4_2026-05-23.md) |
| **Q4 — idempotency middleware broadening** | **No broadening, no new POST/PATCH endpoints.** Target change workflow = `unsubscribe + resubscribe` (natural-key idempotency per ADR 0009 makes this safe). ADR 0007 dispatch middleware = follow-up ADR 0007 concern, NOT step 4 scope. Wording = «not in this sprint», not «forbidden forever». | [PLAN § 7 Q4](PLAN_WAVE1_STEP4_2026-05-23.md) |

---

## §1 — Scope

### In

* **ADR 0008 implementation** — Option B (polymorphic discriminator) with primary `target_kind` enum **`('chat', 'channel')` only**.
* **4 surfaces** — HTTP API + MCP + Bot + CLI all accept `target: {kind, chat_id|channel_id}` shape + backward-compat `chat_id: int` shim.
* **Alembic migration** — `digest_subscriptions` + `watch_interests` get `target_kind` Postgres ENUM + nullable `channel_id` (VARCHAR). Existing `chat_id` column retained; existing rows migrate `target_kind='chat'`. Reversible (downgrade DROPs).
* **New JSON Schema contract** — `docs/contracts/subscription_target.schema.json` (discriminated union; chat | channel variants).
* **`prompts/bot.yaml` v1.6.0 → v1.7.0** — new dedicated `target_kind_semantics` section (≤15 lines) only.
* **Channel-publish service layer** — best-effort + soft-deactivate on `bot not admin in channel` / `channel not found` per [ADR 0008 § Open questions OQ#3](../adr/0008-subscription-target-model.md).
* **Tests** — service-layer unit + HTTP TestClient + MCP tool + Bot executor + CLI parametrized + migration runtime smoke (testcontainer Postgres, mirror ADR 0009 precedent) + bot-flow integration (mocked aiogram `bot.send_message(channel_id, ...)`).
* **Docs** — ADR 0008 история-row, USER_GUIDE «Digest Subscription» extension, MCP_AGENT_GUIDE `subscribe_digest` target shape note, CHANGELOG entry under `[Unreleased]`, new runbook `docs/runbooks/WAVE1_STEP4_DEPLOY_AND_WATCH.md` (mirror [`WAVE1_STEP3_DEPLOY_AND_WATCH.md`](../runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md)).

### Out — Anti-scope (mirror § 5)

See § 5 (hard list).

### Pre-req

* ADR 0008 status = **Accepted** ✅ (this planning sub-session).
* ADR 0009 idempotency middleware = wired on `POST /api/v1/watchlists` + `POST /api/v1/digests` ✅ (step 3 acceptance).
* ADR 0007 MCP HTTP dispatch = Accepted ✅ (step 3.1).
* BUG-028 closed ✅ (PR #92 / `26d03a5` / DONE-marker `668946e`).
* No outstanding deploys; clean working tree on `main` ≥ `668946e`.

---

## §2 — Phases

Per PLAN § 8.1. **10 phases**, single PR, multi-commit packaging (mirror step 3 — ~4–5 atomic commits OK; if scope-bound the implementation may naturally split into more, but **NOT** more than 8 commits per sprint without explicit replanning).

### Phase 1 — Storage migration

Alembic migration: add `target_kind` Postgres ENUM type with values `('chat', 'channel')` (extension-friendly for additive `'webhook'` in Wave 2A) + nullable `channel_id` VARCHAR on both `digest_subscriptions` and `watch_interests`. Backfill existing rows: `UPDATE … SET target_kind = 'chat'` (existing `chat_id` already populated). Downgrade DROPs both columns. Pre-migration runtime smoke on testcontainer Postgres asserts row count invariant (mirror [`docs/runbooks/wave1_step3_idempotency_dedupe.md`](../runbooks/wave1_step3_idempotency_dedupe.md) precedent).

**LOC:** ~80–100. **Tests:** ~3–5 (migration upgrade + downgrade + idempotency-of-rerun).

### Phase 2 — Domain models

Pydantic discriminated union in [`tg_parser/domain/models.py`](../../tg_parser/domain/models.py): `TargetChat | TargetChannel` with `kind: Literal['chat' | 'channel']` discriminator. Service-layer dispatch in [`tg_parser/services/digest_service.py`](../../tg_parser/services/digest_service.py) + [`tg_parser/services/watchlist_service.py`](../../tg_parser/services/watchlist_service.py) on `target.kind`. Backward-compat shim: `chat_id: int` argument auto-wraps to `TargetChat(chat_id=...)`.

**LOC:** ~120–180. **Tests:** ~5–8 (discriminator round-trip + backward-compat shim + invalid kind rejection).

### Phase 3 — HTTP API

Extend `POST /api/v1/watchlists` and `POST /api/v1/digests` Pydantic request schemas in [`tg_parser/api/schemas.py`](../../tg_parser/api/schemas.py): new optional `target: TargetChat | TargetChannel | None` field with discriminator. Backward-compat: if legacy `chat_id` arg set and `target` is None → auto-construct `TargetChat`. If both set → 400 «provide one of chat_id (legacy) or target (new)». Response shape: include `target: {kind, ...}`. `Idempotency-Key` middleware **reused unchanged** (already wired in step 3). **No new POST or PATCH endpoints.**

**LOC:** ~80–120. **Tests:** ~8–12 (target=chat path, target=channel path, legacy chat_id path, conflict 400, idempotency replay).

### Phase 4 — MCP surface

Tool descriptors in [`tg_parser/mcp_server.py`](../../tg_parser/mcp_server.py) for `subscribe_watchlist` + `subscribe_digest`: accept optional `target: dict` arg alongside legacy `chat_id: int`. Same precedence rules as HTTP. Mutually exclusive enforcement at MCP boundary returns typed error.

**LOC:** ~60–80. **Tests:** ~5–7 (parametrized: kind=chat, kind=channel, legacy chat_id, both-set conflict).

### Phase 5 — Bot surface

`_exec_subscribe_digest` + `_exec_subscribe_watchlist` in [`tg_parser/bot/tools.py`](../../tg_parser/bot/tools.py): accept `target` arg, dispatch on kind. `prompts/bot.yaml` v1.6.0 → **v1.7.0**: add a single new `target_kind_semantics` section (≤15 lines) covering «when user says publish to my channel @X → use target={kind:channel, channel_id:'@X'}» + backward-compat fallback («if user just says "subscribe", assume kind=chat and use the current chat_id»). **No other sections of `prompts/bot.yaml` modified.** Version metadata header updated. Strict commit hygiene: if structural need surfaces during execution to touch other prompt sections → STOP, flag as new under-question (BUG-029-class risk).

**LOC:** ~50–70 + ≤15 prompt lines. **Tests:** ~5–7 (bot executor dispatch + prompt regression sanity).

### Phase 6 — CLI surface

`tg-parser watchlist add` and `tg-parser digest add` in [`tg_parser/cli/app.py`](../../tg_parser/cli/app.py): add mutually-exclusive `--chat-id <int>` / `--channel-id <str>` flags mapping to discriminator. Old `--chat-id`-only callers continue to work (kind inferred as `chat`).

**LOC:** ~40–60. **Tests:** ~4–6 (parametrized: --chat-id only, --channel-id only, both-set conflict, neither-set conflict).

### Phase 7 — Channel-publish service-layer logic

In `digest_service.py` `_publish_to_target(target, payload)`: dispatch on `target.kind`:

* `kind=chat` → existing `bot.send_message(target.chat_id, ...)` path (zero behaviour change).
* `kind=channel` → `bot.send_message(target.channel_id, ...)` with best-effort policy: catch `aiogram` exceptions for «bot not admin in channel» / «chat not found» / «not enough rights» → soft-deactivate subscription (`is_active = False`) + emit typed log entry `channel_publish_permission_denied` + send fallback notification to subscription owner's `chat_id` if available + emit `tg_digest_channel_publish_total{result="permission_denied"}` metric. Other aiogram exceptions → `tg_digest_channel_publish_total{result="failed"}` + retry per existing scheduler policy. Successful publish → `tg_digest_channel_publish_total{result="success"}`.

Per [ADR 0008 § Open questions OQ#3](../adr/0008-subscription-target-model.md) (resolved 2026-05-23).

**LOC:** ~80–120. **Tests:** ~6–10 (success path via mocked aiogram + permission-denied path + fallback notification path + retry on transient).

### Phase 8 — Contracts

New file `docs/contracts/subscription_target.schema.json` describing the discriminated union (chat | channel variants). Cross-link from existing `digest_subscriptions` Pydantic models. Add `tests/test_contracts_subscription_target.py` validating example JSON instances against the new schema.

**LOC:** ~50–80 (schema + tests). **Tests:** ~4–6.

### Phase 9 — Tests (aggregate / integration)

* Service-layer regression: subscribe with `kind=chat` (existing behaviour unchanged) + `kind=channel` (new) + legacy `chat_id` shim mapping + `ChannelAdminRequired` graceful + deactivation.
* Idempotent upsert: same `(owner_id, name)` different `target.kind` → UPDATE with `changed_fields=["target_kind", "channel_id", "chat_id"]`.
* Integration: full subscribe → cron tick → publish to channel; mocked aiogram `bot.send_message(channel_id, ...)`.
* Migration runtime smoke: Alembic dry-run on testcontainers PG with seeded `digest_subscriptions` rows; assert `target_kind='chat'` for all existing rows, no row count change.

**LOC:** ~150–200 (aggregate, may absorb phases 1–8 incremental test additions). **Tests:** ~10–20.

### Phase 10 — Docs

* ADR 0008 история-row + this START_PROMPT cross-link (already done in this formalization).
* USER_GUIDE «Digest Subscription» section extended.
* MCP_AGENT_GUIDE `subscribe_digest` target shape.
* `docs/runbooks/WAVE1_STEP4_DEPLOY_AND_WATCH.md` (new, mirror step 3 deploy runbook shape — pre-deploy checklist, deploy commands, post-deploy smoke matrix, 24h watch matrix).
* CHANGELOG entry under `[Unreleased]` § «Wave 1 step 4 — Shareable Digest».
* REVIEW marker `REVIEW_2026-05-XX_WAVE1_STEP4_DONE.md` (mirror step 3 structure) — landed post-watch-GREEN.

**LOC:** ~100–150 (docs prose). **Tests:** 0.

### Phase totals

* **Aggregate LOC:** ~810–1160 (within Option B locked estimate ~500–800 LOC + ~150–300 LOC test density that wasn't separately broken out, total within ±25% of Option B headline). If above 1200 LOC → STOP, replanning needed.
* **Aggregate new tests:** ~50–80. Quality bar: pytest baselines +25–50 (per Option B headline).

---

## §3 — Pre-flight gate

Run these before phase 1 starts. **Anything that fails → STOP, surface, do not patch around silently.**

```bash
cd /Users/alexanderefimov/TG_parser

git fetch origin main
git checkout main && git pull --ff-only
git log -1 --format='%H %s'
# Expected: HEAD ≥ 668946e (BUG-028 DONE-marker) + any landed commits from this formalization session (planning artifact + ADR 0008 Accepted + START_PROMPT).

.venv/bin/pytest -q --tb=line | tail -3
# Expected: ~2201 passed, ~313 skipped, 0 failed (default mode baseline post-BUG-028 hotfix).

TEST_POSTGRES=1 .venv/bin/pytest -q --tb=line | tail -3
# Expected: ~2505 passed, ~9 skipped, 0 failed (Postgres mode baseline).

ruff format --check . && ruff check .
# Expected: clean (zero diagnostics).

docker compose ps  # local dev stack sanity
# Expected: tg_parser_postgres healthy, tg_parser_bot healthy if running locally.

docker exec tg_parser_postgres psql -U tg_parser_user -d tg_parser \
  -c "SELECT version_num FROM alembic_version_ingestion;"
# Expected: f1a2b3c4d5e6 (step 3 ENH-9 + BUG-022 + idempotency_keys head) — will be down_revision for ADR 0008 migration.
```

**Anti-scope reminder before starting:**

* Do not touch `pyproject.toml`, `requirements*.txt`, `uv.lock`.
* Do not touch `docs/methodology/**` (doesn't exist in this workspace per `AGENTS.md`).
* Do not create new branches; per docs precedent commit to feature branch `feat/wave1-step4-shareable-digest-2026-05-XX` from `main`, single PR.
* Do not modify any `prompts/bot.yaml` section other than the new `target_kind_semantics` section (X1 decision).

---

## §4 — Acceptance criteria

(Mirror REVIEW step 3 § 6 closure criteria.)

1. **All 4 surfaces (HTTP / MCP / Bot / CLI) accept** `target: {kind: chat|channel, chat_id|channel_id}` AND backward-compat `chat_id: int`. Verified via parametrized tests on each surface.
2. **Channel-publish path tested** via mocked aiogram `bot.send_message(channel_id, ...)` in service-layer unit + integration smoke.
3. **Permission-denied path** (`bot not admin in channel` / `chat not found`) → soft-deactivate subscription + typed log `channel_publish_permission_denied` + fallback notification to owner `chat_id` (if available) + `tg_digest_channel_publish_total{result="permission_denied"}` counter increment. Verified via mocked aiogram exception injection.
4. **Migration upgrade + downgrade smoke passes** on testcontainer Postgres (mirror step 3 / ADR 0009 precedent).
5. **New JSON Schema contract** `docs/contracts/subscription_target.schema.json` lands and is referenced by OpenAPI spec for `POST /api/v1/digests` + `POST /api/v1/watchlists`.
6. **`prompts/bot.yaml` v1.6.0 → v1.7.0** ships with ONLY the new `target_kind_semantics` section (≤15 lines); no other sections modified (`git diff prompts/bot.yaml` review confirms).
7. **Pytest counts post-sprint:** baseline +25–50 (per Option B headline). Default mode: ~2226–2251 passed. `TEST_POSTGRES=1`: ~2530–2555 passed.
8. **Ruff clean:** `ruff format --check . && ruff check .` zero diagnostics.
9. **ADR 0008 история-row** updated post-execution with sprint PR SHA + acceptance verdict.
10. **DONE marker** `REVIEW_2026-05-XX_WAVE1_STEP4_DONE.md` published; CHANGELOG entry under `[Unreleased]`.

---

## §5 — Anti-scope (HARD list)

> Same hard anti-scope discipline as step 3 / step 3.1. Any UX-soft
> pressure during execution → STOP, log signal as observation in
> [`PARITY_DECISION_TRACKING.md`](PARITY_DECISION_TRACKING.md) or
> [`BUG_LOG.md`](BUG_LOG.md) if it's a real bug, do **not** flip scope.

| ID | Anti-scope item | Why | Where it goes |
|---|---|---|---|
| **(a)** | **No PATCH target update endpoint** (`PATCH /api/v1/digests/<id>` etc.) | Target change workflow = `unsubscribe + resubscribe` (natural-key idempotency per ADR 0009 makes this safe). Per § 0 Q4. | Future PR if production usage shows real PATCH need (currently no evidence). |
| **(b)** | **No test-publish / publish-now endpoints** | No new POST endpoints in step 4 beyond extending existing `POST /api/v1/digests` / `POST /api/v1/watchlists`. Per § 0 Q4. | Wave 2A if A4 integrators ask for synchronous test-publish. |
| **(c)** | **No middleware broadening to non-subscribe endpoints** (`/api/v1/channels`, `/api/v1/workspaces`, dispatch endpoints `/api/v1/process` / `/api/v1/export`) | Service-layer natural-key idempotency already covers them. ADR 0007 dispatch middleware integration = follow-up ADR 0007 concern, **not step 4 scope**. Wording = «not in this sprint», not «forbidden forever». | Separate «middleware broadening» follow-up PR if production transient-retry pain surfaces. |
| **(d)** | **No `kind=webhook` enum value in primary `target_kind` enum** | Webhook deferred to Wave 2A per ADR 0008 Accepted. Step 4 ships `('chat', 'channel')` only. Wave 2A adds via additive `ALTER TYPE … ADD VALUE 'webhook'` — fully non-breaking. | Wave 2A (A4 audience push, per [Strategy § 5.4](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md)). |
| **(e)** | **No `prompts/bot.yaml` changes outside the new `target_kind_semantics` section** | BUG-025/026/027 HARD RULES are step 4.1 scope. X1 decision keeps each prompt bump thematically focused (step 4 = target semantics; step 4.1 = unsubscribe UX). If structural need surfaces during execution → STOP, flag as new under-question. Per § 0 Q3-under (X1). | Step 4.1 sub-sprint (BUG-025/026/027 HARD RULES, v1.7.0 → v1.8.0 bump). |
| **(f)** | **No Bot UX cluster fixes (BUG-025 / BUG-026 / BUG-027)** | Mirror step 3 → step 3.1 precedent. Step 4 stays «single-purpose A6 push» per audience-driven discipline. Per § 0 Q3. | Step 4.1 sub-sprint (scope-locked per PLAN § 8.1). |
| **(g)** | **Wording «not in this sprint», not «forbidden forever»** | Per explicit user guidance «на текущий момент». Production signal → separate follow-up PR, not bound to step 4. Applies to all (a)–(f) above. | (Always.) |

---

## §6 — Quality gates

| Gate | Threshold | Verification |
|---|---|---|
| Default pytest count | ≥ ~2226 passed, 0 failed | `.venv/bin/pytest -q --tb=line` |
| `TEST_POSTGRES=1` pytest count | ≥ ~2530 passed, 0 failed | `TEST_POSTGRES=1 .venv/bin/pytest -q --tb=line` |
| Ruff format | Zero diagnostics | `ruff format --check .` |
| Ruff lint | Zero diagnostics | `ruff check .` |
| New Prometheus metric | `tg_digest_channel_publish_total{result=success\|permission_denied\|failed}` (mirror F11 metric pattern) | `curl :9090/api/v1/query?query=tg_digest_channel_publish_total` post-deploy |
| New JSON Schema contract | `docs/contracts/subscription_target.schema.json` (discriminated union, chat \| channel variants) + contract test | `python -m jsonschema --schemafile docs/contracts/subscription_target.schema.json <example>` |
| Migration runtime smoke | Upgrade + downgrade on testcontainer Postgres (mirror ADR 0009 precedent) | `tests/test_alembic_subscription_target_migration.py` |
| Karpathy-7 (ADR 0006) | Principle 1 (persistent entity for target shape) + principle 7 (graceful degradation per failure mode — channel publish best-effort) | Inline checklist in PR description |
| Backward-compat regression | Existing `chat_id: int` callers untouched on all 4 surfaces | `tests/test_subscribe_legacy_chat_id.py` (per [ADR 0008 § Test strategy](../adr/0008-subscription-target-model.md)) |

---

## §7 — Deploy plan + 24h watch plan

### Deploy plan

Mirror [`docs/runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md`](../runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md) shape. The detailed runbook `docs/runbooks/WAVE1_STEP4_DEPLOY_AND_WATCH.md` is a **deliverable of the implementation sprint** (Phase 10 docs), NOT this planning sub-session. Outline below for planning visibility.

* **Pre-deploy:** `docker exec tg_parser_postgres pg_dump -t digest_subscriptions -t watch_interests > pre_step4_backup.sql` (rollback safety net). Backup retention 7 days.
* **Deploy commands:** `git pull && docker compose build tg_parser tg_parser_bot tg_parser_mcp && docker compose up -d` (mirror step 3).
* **Migration:** `docker exec tg_parser tg-parser db upgrade --db ingestion` — should run Alembic upgrade for the new ADR 0008 migration; assert `version_num` advances + row count invariant.
* **Smoke immediately after deploy (T+0..15m):**
  * `POST /api/v1/digests` with `target={kind: chat, chat_id: <test_chat>}` → 201, row written with `target_kind='chat'`.
  * `POST /api/v1/digests` with `target={kind: channel, channel_id: '@test_curated_digest'}` → 201, row written with `target_kind='channel'` + `channel_id` populated.
  * `POST /api/v1/digests` with legacy `chat_id: <int>` (no `target`) → 201, row written with `target_kind='chat'` (backward-compat shim).
  * `DELETE /api/v1/digests/<id>` → 204 (regression guard).

### 24h watch plan

* **Open** at deploy timestamp; **close** T+24h.
* **Container target:** `tg_parser` + `tg_parser_bot` + `tg_parser_mcp`.
* **Focus signals:**
  * `tg_digest_channel_publish_total{result="success"}` non-zero (operator-driven smoke: subscribe a test digest to a channel where bot is admin, force cron tick, verify message lands + counter increments).
  * `tg_digest_channel_publish_total{result="permission_denied"}` = 0 (no operational misconfiguration in real subscriptions). If non-zero → check soft-deactivation behaviour fired correctly.
  * `tg_digest_channel_publish_total{result="failed"}` = 0 (no transient errors propagating uncaught).
  * **No regression in chat-target path:** existing `digest_94483db9` (prod endocrinology, `target_kind='chat'`) — daily 09:00 MSK cron tick continues to PASS (regression guard against step 3 BUG-028 closure + step 4 dispatch refactor).
  * `up{service=tg_parser|tg_parser_bot|tg_parser_mcp}` = 1 (97/97 samples over 24h).
  * 0 × 5xx on `/api/v1/digests` + `/api/v1/watchlists` endpoints over watch window.
  * `tg_idempotency_keys_hit_total` continues to behave (no regression).
  * BUG-028 regression guard: `PROMPTS_DIR` env still set on all three services; digest cron job re-tick on 2026-05-XX continues to PASS.
* **Watch window template:** new `docs/notes/WATCH_WINDOW_WAVE1_STEP4_2026-05-XX.md` (mirror [`WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md`](WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md)).
* **GREEN closure:** all focus signals confirmed; produce REVIEW marker `REVIEW_2026-05-XX_WAVE1_STEP4_DONE.md` (mirror [`REVIEW_2026-05-21_WAVE1_STEP3_DONE.md`](REVIEW_2026-05-21_WAVE1_STEP3_DONE.md)).

---

## §8 — Workflow внутри сессии

(Mirror step 3 start-prompt workflow conventions.)

* **Plan first, code second.** Re-read this prompt + ADR 0008 + PLAN before touching code. If the locked-decision rationale doesn't reproduce in your head from § 0 — re-read § 7 of PLAN until it does.
* **Background subagents** for parallel work (e.g. one for storage-migration phase, one for HTTP-API phase) — but **NOT** for prompt edits (Phase 5 `prompts/bot.yaml` is scope-sensitive, single agent in foreground).
* **Document side findings as new BUG-NN** in [`BUG_LOG.md`](BUG_LOG.md) — do **not** bundle them into step 4 PR (mirror step 3 discipline; e.g. BUG-025/026/027 surfaced during step 3 watch but bundled into step 4.1, not step 3 hotfix).
* **No `git commit` without explicit user request** (per [`AGENT_PLAYBOOK.md`](../quality/AGENT_PLAYBOOK.md) § 8). Sprint PR is a **separate user-driven step** after all phases land.
* **No `pyproject.toml` / `requirements*.txt` / `uv.lock` modifications** without explicit user request — ADR 0008 implementation does NOT need new dependencies (Pydantic discriminated unions + Alembic enum support are already vendored).
* **If pyproject change appears necessary** (e.g. a Pydantic version bump for discriminator support) → STOP, surface, do not bump silently.
* **Single PR + 4–5 atomic commits** packaging convention (mirror step 3). Suggested commit story:
  * `feat(adr-0008): storage migration + domain models for polymorphic target` (Phase 1 + 2).
  * `feat(adr-0008): HTTP API + MCP + CLI surfaces for target discriminator` (Phase 3 + 4 + 6).
  * `feat(adr-0008): bot surface + prompts/bot.yaml v1.7.0 target_kind_semantics` (Phase 5).
  * `feat(adr-0008): channel-publish service layer (best-effort + soft-deactivate)` (Phase 7).
  * `docs(adr-0008): contract schema + USER_GUIDE + runbook + CHANGELOG` (Phase 8 + 10).
* **Anti-scope discipline:** if at any phase you reach for an item in § 5 (a)–(g) — STOP, surface the temptation, do **not** silently scope-creep.

---

## §9 — Cross-links

| Документ | Зачем |
|---|---|
| [`PLAN_WAVE1_STEP4_2026-05-23.md`](PLAN_WAVE1_STEP4_2026-05-23.md) | **Authoritative scope source.** § 4.1 Candidate A + § 7 Q1–Q4 + Q3-under (X1) + § 8.1 step 4.1 scope-lock. |
| [`docs/adr/0008-subscription-target-model.md`](../adr/0008-subscription-target-model.md) | **Accepted 2026-05-23.** Primary enum `{chat, channel}` only; Wave 2A webhook additive migration documented. |
| [`docs/adr/0009-idempotency.md`](../adr/0009-idempotency.md) | Companion ADR. Natural keys + middleware reused as-is in step 4. |
| [`docs/adr/0007-mcp-scheduler-dispatch.md`](../adr/0007-mcp-scheduler-dispatch.md) | Not blocking step 4; dispatch middleware integration NOT in scope per § 5 (c). |
| [`docs/adr/0006-karpathy-like-living-kb-principles.md`](../adr/0006-karpathy-like-living-kb-principles.md) | Principle 1 (persistent entity) + principle 7 (graceful degradation) — normative for new target shape + channel-publish best-effort policy. |
| [`PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md` § 5.1 шаг 4, § 5.4 Wave 2A](PRODUCT_STRATEGY_AUDIENCE_DRIVEN_2026-05-02.md) | A6 audience driver (Domain Curator) for step 4 + Wave 2A webhook line (added 2026-05-23). |
| [`PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md` § 3.2](PLANNING_WAVE1_EXECUTION_PLAN_2026-05-03.md) | Original «Light extension F6» scope statement — superseded by ADR 0008 promotion (LOC/session re-locked to ~500–800 / ~1.5–2). |
| [`REVIEW_2026-05-21_WAVE1_STEP3_DONE.md`](REVIEW_2026-05-21_WAVE1_STEP3_DONE.md) | Step 3 closure (baseline pytest counts + 24h watch precedent). |
| [`START_PROMPT_SPRINT_WAVE1_STEP3_2026-05-21.md`](START_PROMPT_SPRINT_WAVE1_STEP3_2026-05-21.md) | **Format-precedent** for this prompt. |
| [`docs/runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md`](../runbooks/WAVE1_STEP3_DEPLOY_AND_WATCH.md) | Template for upcoming `WAVE1_STEP4_DEPLOY_AND_WATCH.md` runbook (Phase 10 deliverable). |
| [`docs/quality/AGENT_PLAYBOOK.md`](../quality/AGENT_PLAYBOOK.md) | Quality lifecycle conventions (no auto-commit; pytest baselines; INBOX-vs-incident triage). |
| [`docs/notes/agents-roles.md`](agents-roles.md) | Agent-role assignment for ADR / implementation / tests / docs phases. |
| [`BUG_LOG.md`](BUG_LOG.md) | Open bug inventory; BUG-025/026/027 = step 4.1 scope (do NOT bundle in step 4 per § 5 (f)). |
| [`CHECKLIST_WAVE1_STEP4_2026-05-23.md`](CHECKLIST_WAVE1_STEP4_2026-05-23.md) | Companion DoD checklist for execution sub-session. |

---

## §10 — История промпта

| Дата | Изменение |
|------|-----------|
| 2026-05-23 | Первая версия. Создана formalization sub-session после Wave 1 step 4 planning (`PLAN_WAVE1_STEP4_2026-05-23.md` § 7 Q1–Q4 + Q3-under (X1) resolved) + ADR 0008 promotion Draft→Accepted + strategy § 5.4 Wave 2A webhook line. Locks Q1=Option B / Q2=defer webhook / Q3=defer Bot UX → step 4.1 / Q3-under X1=step 4 prompt touch limited to `target_kind_semantics` ≤15 lines / Q4=no broadening + no new POST/PATCH. 10 phases (storage → domain models → HTTP → MCP → Bot → CLI → channel-publish → contracts → tests → docs). Anti-scope items (a)–(g). Prompt version baseline rebased to current `prompts/bot.yaml` v1.6.0 (step 4 → v1.7.0, step 4.1 → v1.8.0; user-supplied lock referenced v1.4.0→v1.5.0→v1.6.0 stale by one bump). |
