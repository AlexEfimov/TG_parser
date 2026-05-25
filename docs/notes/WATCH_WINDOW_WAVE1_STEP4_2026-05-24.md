# Watch window — Wave 1 Step 4 (PR #93)

**Exercise plan (active + passive checks for this window):** [`docs/runbooks/WAVE1_STEP4_WATCH_SESSION_EXERCISE_PLAN.md`](../runbooks/WAVE1_STEP4_WATCH_SESSION_EXERCISE_PLAN.md).

**Opened:** `2026-05-24T09:54:35Z` (~12:54 MSK 24-05) — declared OPEN immediately after step-4 deploy completed (build + recreate `tg_parser` / `tg_parser_mcp` from `main @ 926a165`, alembic upgrade `e9f0a1b2c3d5 → f1a2b3c4d5e6 → a8b7c6d5e4f3`, smoke matrix 3×201 + 3×204).

**T+24h target (nominal):** `2026-05-25T09:54:35Z` (~12:54 MSK 25-05).

**Closed:** _pending_ — close via `START_PROMPT_SESSION_WATCH_CLOSURE_2026-05-25.md` (or analogous).

**Operator exercise plan:** [`docs/runbooks/WAVE1_STEP4_WATCH_SESSION_EXERCISE_PLAN.md`](../runbooks/WAVE1_STEP4_WATCH_SESSION_EXERCISE_PLAN.md) — P0/P1/P2 checklist (MCP/Bot/CLI), Cursor Automations feasibility, GREEN closure criteria.

**Merge commit:** `926a165` — [PR #93](https://github.com/AlexEfimov/TG_parser/pull/93) squash-merged 2026-05-24T09:39:52Z (per `gh pr view 93 --json mergeCommit,mergedAt`).

**Pre-deploy local prod HEAD:** `e9f0a1b2c3d5` (workspaces F4-B; **two revisions** behind expected `f1a2b3c4d5e6` — Wave 1 step 3 migration was never applied to the local stack DB; step 4 deploy caught up both heads-to-head). **Post-deploy HEAD:** `a8b7c6d5e4f3` (Wave 1 step 4 — ADR 0008 polymorphic subscription target).

**Pre-deploy backup:** [`backups/pre_step4_backup_20260524T094610Z.sql`](../../backups/pre_step4_backup_20260524T094610Z.sql) — 5753 B, `pg_dump -t digest_subscriptions -t watch_interests`. Tables empty at backup time → file contains DDL only (no row data); recovery == re-create empty tables.

**Container `StartedAt` (post-recreate):** `tg_parser` and `tg_parser_mcp` recreated 2026-05-24T09:48:33Z (image `tg_parser:latest` rebuilt from `main @ 926a165`); both healthy by 09:48:50Z. `tg_parser_postgres` / `tg_parser_grafana` / `tg_parser_prometheus` retained running (4-week-old containers; not part of step-4 image rebuild).

---

## Deploy smoke (immediate, 2026-05-24)

| # | Criterion | Method | Result |
|---|---|---|---|
| 1 | Pre-flight: docker compose ps | local docker | ✅ 5 default-profile containers (postgres, prometheus, grafana, tg_parser, mcp) all healthy where applicable |
| 2 | Pre-flight: PROMPTS_DIR regression guard | `docker compose --profile bot config` | ✅ `PROMPTS_DIR=/app/prompts` codified on **all 3** services (`tg_parser`, `mcp`, `tg_bot`) — BUG-028 Layer D fix per `docker-compose.yml:233` comment ("This was previously the prod hotfix workaround — now committed for all three services") |
| 3 | Backup | `docker exec tg_parser_postgres pg_dump …` | ✅ 5753 B file at `backups/pre_step4_backup_20260524T094610Z.sql` |
| 4 | Build | `docker compose --profile bot build tg_parser tg_bot mcp` | ✅ all three exported `tg_parser:latest` image; ~85s |
| 5 | Recreate | `docker compose up -d` | ✅ `tg_parser` + `tg_parser_mcp` Recreated → Healthy in ≤30s |
| 6 | Migration | `docker exec tg_parser tg-parser db upgrade --db ingestion` | ✅ `e9f0a1b2c3d5 → f1a2b3c4d5e6 → a8b7c6d5e4f3 (head)` — both Wave 1 step 3 and step 4 applied; alembic transactional |
| 7 | Row invariant: 0 NULL `target_kind` | `SELECT COUNT(*) FILTER (WHERE target_kind IS NULL)` on both tables | ✅ 0 / 0 (vacuously: tables empty pre-migration in this dev DB) |
| 8 | Row invariant: 0 `target_kind='channel'` | `SELECT COUNT(*) FILTER (WHERE target_kind='channel')` on both tables | ✅ 0 / 0 (vacuously: no rows existed to backfill) |
| 9 | `POST /api/v1/digests` `target={kind:chat,chat_id:777111}` | curl, no auth (`API_KEY_REQUIRED=false` → synthetic admin) | ✅ 201 Created; response `target:{kind:"chat",chat_id:777111}`; digest_id `a7264e8d-2bd5-402e-a7e4-5f3e633d07c3` |
| 10 | `POST /api/v1/digests` `target={kind:channel,channel_id:"@smoke_test_step4"}` | curl, no auth | ✅ 201 Created; response `target:{kind:"channel",channel_id:"@smoke_test_step4"}`; digest_id `c45ec1be-0722-4f45-8433-ee995fe037c6` |
| 11 | `POST /api/v1/digests` legacy top-level `chat_id:777222` | curl, no auth | ✅ 201 Created; backward-compat shim → response `target:{kind:"chat",chat_id:777222}`; digest_id `3b3eba8d-3e58-41b2-917c-a0229cbd8477` |
| 12 | `DELETE /api/v1/digests/{a7264e8d…}` | curl | ✅ 204 No Content |
| 13 | `DELETE /api/v1/digests/{c45ec1be…}` | curl | ✅ 204 No Content |
| 14 | `DELETE /api/v1/digests/{3b3eba8d…}` | curl | ✅ 204 No Content |

**Smoke verdict:** ✅ all 4-surface contracts on the HTTP edge confirmed:
- `target.kind=chat` discriminator round-trip
- `target.kind=channel` discriminator round-trip
- legacy `chat_id` shim → emits `target.kind=chat` in response (ADR 0008 backward compat)
- DELETE 204 on all three target shapes

---

## Anomaly observed during smoke (NOT a step 4 regression)

**Local-stack-only seeding gap.** First batch of 3 POSTs returned 500 because `get_default_admin()` returns synthetic user `00000000-0000-0000-0000-000000000000`, but only the real admin (`57789b21-67ce-…`) existed in `users`. Each POST ⇒ FK violation on `digest_subscriptions.owner_id_fkey` ⇒ `IntegrityError` caught by `digest_service.subscribe()` race-retry branch ⇒ retry-`SELECT` on the same connection hit `InFailedSQLTransactionError` (no rollback before retry).

**Worked around** by inserting the synthetic admin row (`INSERT INTO users (id='00000000-…',name='admin',role='admin')`) and reassigning the smoke source to that owner; smoke matrix then completed cleanly. Both transient artifacts (smoke source `@step4_smoke` + synthetic admin) cleaned up post-smoke; final `SELECT COUNT(*) FROM users = 1` (real admin only).

**Latent service defect (out-of-scope for step 4 close):** `digest_service.subscribe()` race-retry pattern (`tg_parser/services/digest_service.py:265-272`) does not `session.rollback()` between the failed `create()` and the retry `find_by_owner_and_name()`. In a real prod env every `IntegrityError` path on `digest_subscriptions` would fail to recover. Pre-existing; not introduced by step 4 (the same pattern existed before the polymorphic-target refactor).

→ **Recommend** filing as `BUG-029` after watch closes; bundle into a step-4 follow-up PR (small, targeted patch that adds an explicit rollback between the `create()` IntegrityError and the retry SELECT).

---

## Initial Prometheus snapshot (T+0)

Sampled `2026-05-24T09:53:43Z` (epoch `1779616423`).

| Series | Result | Note |
|---|---|---|
| `up{job="tg_parser_api",instance="tg_parser:8000",service="api"}` | **1** | API healthy post-recreate |
| `up{job="tg_parser_mcp",instance="mcp:8080",service="mcp"}` | **1** | MCP healthy post-recreate |
| `up{job="tg_parser_bot",instance="tg_bot:8081",service="bot"}` | **0** | Bot intentionally down (profile-gated, Exited 3 weeks ago, **not part of step-4 deploy scope**) — see below |
| `tg_digest_channel_publish_total{result=*}` | **(empty series)** | Expected at T+0: counter only materialises on first scheduler-tick channel digest publish; smoke subscriptions were created+deleted within seconds, no cron tick fired. Counter is **registered** (verified via code: `tg_parser/api/metrics.py`); will appear once a real channel digest publishes. |
| `tg_idempotency_keys_hit_total{result=*}` | **(empty series)** | Smoke matrix did not pass `Idempotency-Key` headers (step-4 brief did not require it; step-3 watch already covered idempotency); existing series will be re-populated on next `Idempotency-Key`-bearing POST. |
| `tg_idempotency_keys_table_size{service="api"}` | **0** | Empty DB; no cached idempotency keys; gauge will tick up after first keyed POST (cleanup cron `0 * * * *` is registered — see startup log `idempotency_keys_cleanup`). |

---

## Container log smoke (T+0..15m)

`docker logs --tail 200` per service, post-recreate at 09:48:33Z, smoke completed 09:53:31Z.

| Container | unhandled_exception count | Classification |
|---|---|---|
| `tg_parser` | **3** | All three are the FK-violation 500s during the first failed smoke batch (09:51:13Z–09:51:15Z) — root-caused above (synthetic admin missing). After seeding (09:52:30Z), 0 errors over 09:53:00Z–09:54:35Z window. **No step-4-regression errors.** |
| `tg_parser_mcp` | **0** | Clean over the entire post-recreate window. |
| `tg_parser_bot` | **N/A** | Container Exited(0) since 2026-05-03 (~3 weeks); not part of step-4 deploy scope; **PROMPTS_DIR codified** in `docker-compose.yml:233` so when an operator re-launches it via `--profile bot`, BUG-028 will not regress. |

---

## Focus signals for the 24h window

Per [`docs/runbooks/WAVE1_STEP4_DEPLOY_AND_WATCH.md` § 24h watch](../runbooks/WAVE1_STEP4_DEPLOY_AND_WATCH.md):

1. **`tg_digest_channel_publish_total{result="success"}`** — operator should subscribe to a real channel target during the window (Telegram bot must be admin in that channel) to materialise the counter. Otherwise expect empty series at close (NOT a failure — series materialises lazily).
2. **`tg_digest_channel_publish_total{result="permission_denied"}`** — expected **0** in steady state. Non-zero ⇒ BUG-029 candidate (bot mis-promoted, channel mis-typed).
3. **Existing chat-target prod digest cron** — no regression (BUG-028 guard). Existing scheduled chat digests fire on their cron tick using the `target_kind='chat'` backfilled rows. None exist in this local DB to observe (zero rows pre-migration).
4. **`up{job=~"tg_parser.*"}` continuity** — `up{service=api}` and `up{service=mcp}` should remain `1` for the whole window. Single bucket-zero at OPEN (recreate) tolerable per step-3 GREEN criterion §4 reuse.

---

## Operator action required during the window

| # | Action | Priority |
|---|---|---|
| **OA-1** | **Re-launch `tg_bot`** via `docker compose --profile bot up -d tg_bot` if the production bot is required during this watch (3-week-old Exited container → image rebuild already happened during step-4 build, so the new image contains both step 4 polymorphic-target code AND the BUG-028 PROMPTS_DIR fix). | **DEFERRED — outside step-4 scope; no step-4 deliverable depends on the bot for this window.** |
| **OA-2** | Subscribe to a **real channel target** via `POST /api/v1/digests target={kind:channel,channel_id:"@<real_channel>"}` (with bot promoted as admin in that channel) to materialise `tg_digest_channel_publish_total{result="success"}`. Without this, the counter stays empty at close (still GREEN per § Focus signals #1 caveat). | **OPTIONAL** for green close. |
| **OA-3** | After 24h, run closure session with `START_PROMPT_SESSION_WATCH_CLOSURE_2026-05-25.md` analogous to step-3 closure: Q1 `up{}` gap-detection, Q2 `tg_digest_channel_publish_total` instant, log-scan for 5xx on `/api/v1/(digests\|watchlists)`. | **MANDATORY** to close. |
| **OA-4** | File `BUG-029` (digest_service race-retry transaction-rollback gap) → step-4 follow-up PR. | **MANDATORY before step-5 starts.** |

---

## Verdict

| Field | Value |
|---|---|
| **Status** | **OPEN** (2026-05-24T09:54:35Z, nominal close 2026-05-25T09:54:35Z) |
| **Initial verdict** | **GREEN-pending** — all immediate smoke criteria PASS (3×201 + 3×204; correct `target` discriminator round-trip on all three shapes; alembic head advances; PROMPTS_DIR regression guard codified). One operator follow-up (BUG-029) deferred to post-watch. |
| **DONE marker** | [`docs/notes/REVIEW_2026-05-24_WAVE1_STEP4_DONE.md`](REVIEW_2026-05-24_WAVE1_STEP4_DONE.md) — to be finalised at watch close. |

---

## Cross-reference

* Sprint start prompt: [`START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md`](START_PROMPT_SPRINT_WAVE1_STEP4_2026-05-23.md).
* Plan: [`PLAN_WAVE1_STEP4_2026-05-23.md`](PLAN_WAVE1_STEP4_2026-05-23.md).
* ADR: [`docs/adr/0008-subscription-target-model.md`](../adr/0008-subscription-target-model.md).
* Runbook: [`docs/runbooks/WAVE1_STEP4_DEPLOY_AND_WATCH.md`](../runbooks/WAVE1_STEP4_DEPLOY_AND_WATCH.md).
* Step-3 watch precedent (structural mirror): [`WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md`](WATCH_WINDOW_WAVE1_STEP3_2026-05-22.md).
