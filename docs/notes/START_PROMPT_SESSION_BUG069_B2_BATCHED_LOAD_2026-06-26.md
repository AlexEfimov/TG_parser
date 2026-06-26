# START_PROMPT — BUG-069 + B2 joint design (batched/cursor processing load) + pending ops

**Created:** 2026-06-26 (handoff from the BUG-067/068 fix+deploy session; context window was ~80% full).
**Branch:** `main`. **Repo:** `/Users/alexanderefimov/TG_parser`.
**Prod:** VPS `ssh prod` (`212.72.189.15:2296`, user `user`, app dir `/home/user/TG_parser`), Docker compose.

---

## TL;DR for the next session

Two linked threads to pick up, **plus one pending ops task**:

1. **Design-investigation (read-only first):** BUG-069 (un-paginated full-backlog load + `ORDER BY` sort spills to `pgsql_tmp` → transient `DiskFullError`) and the **deferred B2** (bound how much backlog is re-attempted per tick) share ONE root cause and should be fixed together with a **batched / keyset-cursor processing load**. Produce a concrete design proposal, then implement after explicit user approval.
2. **Pending ops task (safe disk cleanup):** prune dangling/untagged Docker images on prod (~20 GB) to actually restore filesystem headroom. `docker builder prune` was already run (freed only 3.6 GB private cache; `df` unchanged because the rest is shared image layers). The real lever is `docker image prune` of UNTAGGED images — **`tg_parser:latest` must stay**. Not yet done; awaiting go.

---

## What already shipped this session (context — DO NOT redo)

Commit **`1ed86ac`** "fix(pipeline): bound LLM hangs, surface degraded ticks, cap token re-burn (BUG-067, BUG-068)" — committed, pushed to `origin/main`, **deployed to prod and verified** (prod HEAD = `1ed86ac`, services healthy, backlogs draining: murashko_med 11384→12765, mediamedics 9514→10450 across post-deploy ticks). Implemented + reviewed (self/security/bugbot, all findings fixed):

- **A1** aggregate wall-clock timeout around `anthropic_client.generate_with_usage` (`LLMCallTimeoutError`, `anthropic_call_timeout_s`=300); timed-out doc fails fast (one attempt, no max_attempts re-burn).
- **A2** per-source watchdog (`asyncio.wait_for`, `scheduler_source_timeout_s`=1800) cancels in-flight work + awaits cancelled tasks before re-raise; releases scheduler slot.
- **A3** `scheduler_max_concurrent_sources` 1→2, `scheduler_max_instances` 1→2, + per-source Postgres advisory lock (`_source_processing_lock`) so overlapping ticks can't double-process a channel.
- **B1** degraded-tick detection (denominator = docs **attempted this tick**, `scheduler_degraded_failure_ratio`=0.5) — no more false `success` on 0-of-N. Observed working in prod (`source_tick_degraded`).
- **B3** per-channel coverage gauge `tg_channel_processed_coverage_ratio` + `channel_coverage`/`channel_coverage_low` logs (`scheduler_coverage_alert_ratio`=0.8).
- **B2b** bounded retry + cooldown via `failure_repo`/`processing_failures` (billing 1800s / parse 3 attempts→86400s / default 3600s); `LLMCallTimeoutError`→category `timeout`→other; clamps future-dated legacy timestamps; cooldown-skipped docs counted as `skipped` not `failed`.
- **Chunked persistence** in `_process_batch_parallel` via `asyncio.as_completed` + `_persist_chunk` (`PROCESSING_PERSIST_CHUNK_SIZE`=20); failures recorded incrementally; no partial-chunk write during cancel unwind.
- **Billing-pause** `AnthropicBillingError` surfaces `billing_blocked_count` → `_record_and_pause_on_billing` fires + tick marked degraded (not swallowed).

`BUG_LOG.md` BUG-067/068 updated; **BUG-069 filed** this session (see below). Nothing else uncommitted of note.

---

## Thread 1 — BUG-069 + B2 joint design

### Shared root cause (confirmed code paths)
Every scheduler tick loads the channel's **entire** raw backlog and sorts it, then filters in Python:
- `tg_parser/services/processing_service.py:113-114` — `run_processing` calls `raw_repo.list_by_channel(channel_id)` with **no `limit`**. The `limit` param is applied in Python only AFTER the full query returns (`:125-126`) — never bounds the DB load/sort.
- `tg_parser/storage/sqlalchemy/raw_message_repo.py:155-184` — SQL ends in `ORDER BY date ASC` (`:182`); `LIMIT` appended only if `limit` passed (`:175`).
- The "already processed" filter (`processed_doc_repo.exists(...)`, around `pipeline.py:~1040-1045`) and the B2b cooldown filter both run in Python AFTER loading everything.

Three symptoms, one cause:
| Symptom | Bug | Mechanism |
|---|---|---|
| Token/cost re-burn | BUG-067 / B2 | full unprocessed set re-sent to LLM every tick |
| `DiskFullError` (pgsql_tmp) | **BUG-069** | full `ORDER BY` materializes a large sort that spills to temp |
| Tick memory / wall-time | BUG-068-adjacent | ~33k rows loaded into memory each tick |

**Key point:** shipped B2b only skips *failed* docs. It does NOT cap the load of not-yet-attempted docs and does NOT remove the full sort. The "real B2" = **bound + batch the per-tick processing load**, which simultaneously fixes BUG-069.

### Proposed direction (to validate + detail)
Move from "load all → filter in Python" to a **batched keyset-cursor load**: each tick processes N oldest unprocessed messages via keyset pagination on `date` (`WHERE date > cursor ORDER BY date LIMIT N` — index scan, not a full sort), advancing a per-source cursor. Cuts tokens (bounded re-attempt), removes the large sort (no pgsql_tmp spill), bounds memory/time. Composes with the already-shipped chunked persistence.

### CRITICAL unknown to confirm FIRST
`raw` and `processing` are separate alembic branches (`alembic_raw.ini` / `alembic_processing.ini`). **Confirm whether they are physically separate Postgres databases.** If yes, you CANNOT JOIN `raw_messages` against `processed_documents`/`processing_failures` to push the "not processed / not in cooldown" filter into SQL — which is exactly why the filter is in Python today. Design then must be: keyset-paginate `raw` in batches of N + keep the exists/cooldown filter in Python over the bounded window + persist a per-source cursor.

### Open decisions for the design proposal (give defensible defaults)
1. Confirm raw/processing DB separation (decides SQL push-down vs keyset+cursor).
2. Batch size per tick (drain speed ↔ per-tick cost/memory/sort). Propose a default.
3. Where to store the per-source cursor (e.g. a column on `sources`, or a new small state table). Check existing `sources` schema.
4. Cursor vs cooldown interaction — avoid getting "stuck" re-scanning cooldown-deferred docs at the head of the window (cursor must advance; decide how cooldowned-but-not-yet-processed docs are revisited after TTL without blocking forward progress).
5. Confirm an index exists on `raw_messages(date)` (and ideally a composite supporting the keyset + channel filter); if not, a migration is part of the fix.

### Suggested first action in the new session
Launch a **read-only design-investigation** (one focused worker) that: confirms the DB-boundary fact, inspects `raw_message_repo` query + indexes, `sources` schema (cursor home), the `processed_doc_repo.exists` / B2b cooldown filter call sites, and returns a concrete design with defaults for the 5 decisions above + a migration plan if an index/cursor column is needed. THEN discuss → implement on approval. Respect `AGENTS.md` (no commit without explicit request; accepted ADRs in `docs/adr/` and JSON Schemas in `docs/contracts/` are binding; tests per `tests/README.md`).

---

## Thread 2 — Pending ops: safe disk cleanup on prod (NOT yet done)

- `docker builder prune -f` already run → reclaimed 3.6 GB *private* build cache; `df /` unchanged (6.7 G free / 63% used) because the other ~20 GB "reclaimable" is **shared image layers** still referenced by live images + the active tick was writing concurrently.
- **To actually free space:** `docker image prune` of **dangling/untagged** images (~20 GB) on prod. Command intent: remove untagged images only; **`tg_parser:latest` (ID was `6e1e70a7927d`) and all running containers/named volumes (postgres data) MUST stay.** Do it via a read/verify-then-prune worker: `df /` before, `docker images` to confirm what's dangling, `docker image prune -f` (or targeted), `df /` after, then confirm services Up(healthy) + murashko/mediamedics still draining. Awaiting user go.
- Also keep an eye on disk headroom generally — it's the trigger condition for BUG-069's DiskFull.

---

## Current prod state snapshot (2026-06-26 ~18:09Z)
- HEAD `1ed86ac`; all services Up(healthy); billing topped up, no billing pause.
- Backlogs draining: murashko_med ~12765, mediamedics ~10450 (and climbing per tick). murashko `last_success_at` advanced 2026-06-25T22:57Z → 2026-06-26T17:53Z (BUG-068 wedge cleared).
- Pre-deploy DB backup taken: `data/backups/postgres_20260626_184628.sql.gz` (267 M).
- One pre-existing unrelated test failure: `test_mcp_management.py::TestGetAllChannelStats::test_batch_stats_degrades_to_zeros_on_aggregation_error` (BUG-066 area) — fails on clean HEAD too; out of scope.

## Deploy procedure reference
`PRODUCTION_DEPLOYMENT.md` § Updating (canonical): backup → `git pull --ff-only` → `docker compose build tg_parser` → `db upgrade --db all` (run as no-op check) → `docker compose up -d` → `docker compose --profile bot up -d --force-recreate --no-deps tg_bot` → smoke (`/health`, `/metrics`, `docker compose ps`). Force-recreate prometheus ONLY if `docker/prometheus*` changed. All via `ssh prod`. Rollback = `git checkout <prev_sha> && build && up -d`.
