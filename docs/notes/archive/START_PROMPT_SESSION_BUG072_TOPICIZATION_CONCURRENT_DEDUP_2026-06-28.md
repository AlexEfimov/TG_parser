# START_PROMPT — BUG-072 concurrent full-topicization of the SAME channel has no dedup

**Created:** 2026-06-28 (handoff from the BUG-071 fix+deploy session; this follow-up was discovered during BUG-071 live validation and is documented READ-ONLY here, NOT yet fixed).
**Branch:** `main`. **Repo:** `/Users/alexanderefimov/TG_parser`.
**Prod:** VPS `ssh prod` (`212.72.189.15:2296`, user `user`, app dir `/home/user/TG_parser`), Docker compose.

> **This is BUG-072. It builds directly on BUG-071** (token-burn in topicization). BUG-071's three fixes are now LIVE on prod (see "What already shipped"). BUG-072 is the *concurrency/dedup gap* that BUG-071 did **not** close: there is no guard preventing two FULL topicization runs of the *same channel* from executing **at the same time**.

---

## ⛔ CRITICAL OPERATIONAL WARNING — READ FIRST

**The Anthropic balance is currently EXHAUSTED and must NOT be refilled until the operator is ready to actively watch.** The BUG-071 live-validation session (see §"Cost evidence") drained the remaining Anthropic credit.

- **Good news (re-burn loop):** BUG-071 **Fix 2** (now live — commit `7ad3264` armed the crash path) means a refill is *safe with respect to the unbounded per-tick re-escalation re-burn loop* — a 0-card channel that crashes a full re-escalation now arms a cooldown marker so the next scheduler tick is skipped within the TTL.
- **Bad news (this bug):** Fix 2's cooldown gates re-escalation **BETWEEN ticks**. It does **NOT** prevent a **within-window duplicate** — i.e. an MCP-triggered `full_pipeline` job and a scheduler tick (or a CLI `tg-parser run`) **overlapping in the same window** can each start a full Sonnet topicization of the same channel concurrently. So a refill still allows within-window duplicate spend until BUG-072 ships. **Restoring credit is a separate user action and should wait until BUG-072 is deployed (or at minimum, until the operator is watching live).**

---

## TL;DR for the next session

During BUG-071 live validation the channel `mediamedics` was topicized **TWICE CONCURRENTLY**: (1) an MCP-triggered `full_pipeline` job via `POST /api/v1/pipeline/trigger` (the `trigger_pipeline` MCP tool), and (2) the scheduler's hourly `incremental_pipeline` tick which, for a 0-card channel, **re-escalates to a FULL `run_topicization`** (the BUG-071 Fix-2 path). Both ran ~222 batches over the same ~11k docs **simultaneously**. A third run (`murashko_med`, 349 batches) was live too. ~15+ concurrent Sonnet calls collapsed Anthropic latency → mass 300s `LLMCallTimeoutError`, **~12.1M Sonnet tokens (~$89) burned, 0 cards persisted, balance exhausted.**

**Root gap:** there is **NO cross-process concurrency guard around full topicization of a channel.** Two guards exist but are **disjoint** and **neither covers the MCP-job-vs-scheduler-tick overlap** (details + verified anchors below).

**Workflow for this session (mirror BUG-071):** implement the fix + tests → self-review → Bugbot review of the diff → **STOP** before commit/deploy and await explicit user approval. On approval: gated full-suite test → commit → push → deploy per `PRODUCTION_DEPLOYMENT.md`.

---

## What already shipped (context — DO NOT redo)

**Prod HEAD = `7ad3264`.** The BUG-071 fix landed across three commits, all now on prod:

- **`bdca97f`** — `fix(topicization): stop token-burn on truncated replies + bound re-escalation re-burn (BUG-071)` — Fixes 1–3: truncation detection (`stop_reason=="max_tokens"`) + batch-split instead of 3× re-issue; the re-escalation cooldown gate; `LLM_TRUNCATION_TOTAL` observability. (Alert rules added alongside in `4e8a8ce`.)
- **`c3f8710`** — `feat(observability): add topicization failed_batches counter + direct alert (BUG-071)` — `tg_parser_topicization_failed_batches_total` Counter + alert.
- **`7ad3264`** — `fix(topicization): arm re-escalation cooldown marker on crash path (BUG-071)` — closes the Fix-2 failure-path gap: a re-escalation that dies by exception now arms the cooldown marker BEFORE the exception propagates (previously a crash skipped the marker-arming, re-escalating the same 0-card channel every tick — the exact loop that helped burn the ~12.1M tokens).

**Rollback ref for any new deploy = `7ad3264`.** Earlier prod context (unchanged): BUG-069/B2 (`1809795`), BUG-070 Telethon session lock + WAL/busy_timeout (`61637d1`).

This BUG-072 fix is **net-new and uncommitted**. Nothing for it has been implemented yet — only the read-only diagnosis below.

---

## Cost evidence (motivation — BUG-071 live-validation session, prod)

- **~12.1M `claude-sonnet-4-6` tokens** burned in one session (~**$89**).
- **539 `failed_batches`** (`tg_parser_topicization_failed_batches_total`), almost all 300s `LLMCallTimeoutError`.
- **0 topic cards persisted** for the affected channels.
- **Anthropic balance exhausted** as a direct result.
- Three full runs live concurrently: `mediamedics` ×2 (MCP `full_pipeline` job + scheduler re-escalation, ~222 batches each over the same ~11k docs) and `murashko_med` (349 batches). ~15+ concurrent Sonnet calls collapsed provider latency → cascading timeouts.

---

## The gap (discovered during BUG-071 validation; READ-ONLY diagnosis, NOT fixed)

All file:line anchors below were **verified against the working tree at HEAD `7ad3264`** during this diagnosis.

### A. Two full-topicization entry paths, run in the SAME `tg_parser` process

`run_topicization` ([`tg_parser/services/topicization_service.py:123`](../../../tg_parser/services/topicization_service.py)) → `TopicizationPipelineImpl.topicize_channel` ([`tg_parser/processing/topicization.py:186`](../../../tg_parser/processing/topicization.py), `BATCH_SIZE = 50` at `topicization.py:247`) is the single expensive full-run function. It is reached by **three** callers that do **not** coordinate with each other:

1. **Scheduler incremental tick (re-escalation path).** `run_incremental_for_all_sources` → `_process_source` runs `run_full_pipeline(..., skip_topicize=True)` then calls `run_incremental_topicization(channel_id, new_doc_refs)` at **[`scheduler_service.py:497-500`](../../../tg_parser/services/scheduler_service.py)**. For a **0-card channel with new docs**, `run_incremental_topicization` re-escalates to a FULL `run_topicization`: the trigger `should_reescalate = len(existing_cards) == 0 and len(new_docs) > 0` at **`topicization_service.py:313`**, the escalation call at **`topicization_service.py:363-370`**.
2. **MCP / API `full_pipeline` job.** `POST /api/v1/pipeline/trigger` ([`tg_parser/api/routes/pipeline.py:56-127`](../../../tg_parser/api/routes/pipeline.py)) → `trigger_pipeline_job` ([`tg_parser/services/pipeline_dispatch_service.py:95`](../../../tg_parser/services/pipeline_dispatch_service.py)) → background task `_run_pipeline_job_background` (`pipeline_dispatch_service.py:156`) → `run_full_pipeline(..., skip_topicize=False)` (`pipeline_dispatch_service.py:183`) → `run_topicization` at **[`pipeline_service.py:203-207`](../../../tg_parser/services/pipeline_service.py)** (`run_full_pipeline` def at `pipeline_service.py:62`). The `TOPICIZATION` job kind calls `run_topicization` directly at `pipeline_dispatch_service.py:226`.
3. **CLI `tg-parser run`** — a **SEPARATE OS process** (its `/metrics` aren't even scraped). It reaches `run_full_pipeline` → `run_topicization` with no shared in-process state.

### B. The two existing guards are DISJOINT — neither covers path-1-vs-path-2 overlap

- **Scheduler guard (Postgres advisory, cross-process):** `_source_processing_lock(source_id)` at **`scheduler_service.py:62-123`** takes a SESSION-scoped `pg_try_advisory_lock(:ns, hashtext(:sid))` (`SCHEDULER_SOURCE_LOCK_NS = 0x5C40` at `scheduler_service.py:59`) on a DEDICATED connection, held for the whole tick (acquired in `_process_source` at **`scheduler_service.py:275-285`**). This was added as the **BUG-068 A3 follow-up (Fix 4)** to stop two *scheduler ticks* from double-processing a source. **It is taken ONLY on the scheduler path.** The MCP/API dispatch and the CLI never take it.
- **Dispatch guard (in-process set, single-process only):** `_running_channel_jobs: set[str]` at **`pipeline_dispatch_service.py:50`** (checked + populated in `trigger_pipeline_job` at `pipeline_dispatch_service.py:118-124`, surfaced as HTTP 409 `JobAlreadyRunning`). This stops two *MCP/API jobs for the same channel* from overlapping **within one process**, but it is (i) a plain in-memory `set` → does **not** coordinate with the CLI's separate process, and (ii) **keyed by `normalize_channel_id(channel_id)`** and completely **disjoint** from the scheduler's `pg_try_advisory_lock` keyed by `source_id` — the scheduler never consults `_running_channel_jobs`, and the dispatch never takes the advisory lock.

**Net result:** a scheduler tick (path 1, holding `_source_processing_lock`) and an MCP `full_pipeline` job (path 2, holding only the in-process set entry) can BOTH enter `run_topicization` for the **same channel at the same time** — exactly what happened to `mediamedics`. A CLI `run` (path 3) bypasses both guards entirely.

> NOTE — `topicization.py:135` has `self._db_lock = asyncio.Lock()`. This is an **intra-instance DB-write serializer** on one `TopicizationPipelineImpl`, NOT a cross-run/cross-process topicization guard. Each concurrent run constructs its own pipeline instance with its own `_db_lock`, so it provides zero dedup between runs. (BUG-070's lock is the Telethon **ingestion** session lock in `telethon_client.py` — also unrelated to topicization runs.) Confirm: there is **no** advisory lock or in-flight marker wrapping `run_topicization` / `topicize_channel`.

### C. BUG-071 Fix 2 gates BETWEEN ticks, not WITHIN a window (make this distinction explicit)

BUG-071 Fix 2 (the cooldown gate at **`topicization_service.py:337-354`**, marker armed/cleared at `:395-440`, persisted in `processing_failures` under synthetic ref `topicization:reescalation:<channel_id>` — `_reescalation_marker_ref` at `topicization_service.py:50`) reads a *persisted marker at the start of the next tick* and skips re-escalation while inside `topicization_reescalation_cooldown_s` (default **3600s**, `settings.py:388`).

This is a **between-ticks** gate. It does **NOT** prevent a **within-window duplicate** because:
- the marker is only *armed after* a run fails/finishes — so when an MCP job and a scheduler tick both *start* in the same window, neither sees an armed marker;
- the **MCP / CLI path never reads or arms the re-escalation marker at all** — it goes through `pipeline_service.run_topicization`, which has no cooldown awareness.

So Fix 2 closes the *iterative re-burn loop* but leaves the *concurrent duplicate* wide open. **BUG-072 is specifically the within-window / cross-path concurrent-duplicate gap.**

---

## The proposed fix (design — options + recommended default)

Goal: **at most one full topicization run per channel at a time, across ALL entry paths and ALL processes** (scheduler re-escalation, MCP/API `full_pipeline` + `topicization` jobs, and the separate CLI `run` process).

### Option (a) — Postgres advisory lock keyed by channel around the full run  ✅ RECOMMENDED

Wrap `run_topicization` (the single funnel for all three paths — see §A) in a **non-blocking** `pg_try_advisory_lock(:ns, hashtext(channel_id))` on a **dedicated connection** (session-scoped, held for the run's lifetime, `pg_advisory_unlock` + close in `finally`). This is a **direct reuse of the existing, proven `_source_processing_lock` pattern** (`scheduler_service.py:62-123`) — promote/generalize it (e.g. a `channel_topicization_lock(channel_id)` async-context-manager) with a **new namespace constant** distinct from `SCHEDULER_SOURCE_LOCK_NS` (e.g. `TOPICIZATION_LOCK_NS`).

- **Try, don't block:** `pg_try_advisory_lock` returns immediately. If **not acquired**, another run already owns the channel → **skip/defer with a clear log** (`topicization_run_skipped_already_in_flight channel=…`) and return a benign no-op result. Do **NOT** raise (see Fix-2 interplay below).
- **Why session-scoped on a dedicated connection (not `pg_try_advisory_xact_lock`):** a full topicization spans MANY transactions/batches, so a transaction-scoped lock cannot cover it — same reasoning as `_source_processing_lock`'s docstring. The dedicated connection avoids the pooling footgun (session lock leaking onto a pooled connection).
- **Crash-release safety (a big plus over option b):** Postgres advisory locks **auto-release when the holding connection closes** — so a crashed/killed run (the exact failure mode that burned tokens) cannot leave a permanent stale lock. No TTL/heartbeat reaper needed.
- **Placement:** wrapping `run_topicization` itself covers all three callers in one place. The scheduler tick will then hold BOTH `_source_processing_lock(source_id)` (different namespace) and the new channel-topicization lock — no deadlock risk (different keys, both `try`-acquire, ordered).

### Option (b) — DB in-flight marker row with TTL/heartbeat

Reuse `processing_failures` (or a small dedicated state table) to write a "topicization in-flight at <ts>" row, checked before starting. **Rejected as the default** because it needs a TTL + heartbeat to survive crashes (a killed run leaves a stale "in-flight" row that blocks the channel forever until the TTL), reintroducing exactly the kind of stale-state bookkeeping that advisory-lock auto-release avoids. More moving parts, a migration if a new table, and racey check-then-set semantics.

### Option (c) — app-level `asyncio.Lock`

**Insufficient — reject.** An in-process lock cannot coordinate the CLI `tg-parser run` (separate process; its metrics aren't even scraped), and even within one process it is fragile. Any guard MUST be **cross-process**; this is the decisive argument for option (a).

### Interplay with BUG-071 Fix 2 (must respect)

- A **skipped-because-locked** run is **NOT a failed attempt** and must **NOT arm the Fix-2 cooldown marker**. The crash-path arming lives in `run_incremental_topicization`'s `try/except` around the re-escalation `run_topicization` call (`topicization_service.py:371-403`): it arms the marker on ANY exception. Therefore the lock-skip must return a **benign sentinel result (no exception)** so it neither trips the crash-arming nor counts as a 0-card failure. Do not double-arm cooldowns.
- Conversely, the *acquiring* run keeps the existing Fix-2 arm/clear-on-persisted-cards behavior unchanged.

### Test guidance

- Use `TEST_POSTGRES=1` for the advisory-lock behavior (it needs a real Postgres — `pg_try_advisory_lock` is a no-op stub on the non-PG path; the guard should **degrade to "acquired"** when no DB/engine is available, mirroring `_source_processing_lock`'s `yield True` fallback so unit tests without a DB never block).
- **Concurrency test:** simulate two concurrent `run_topicization` for the same channel → assert the **second skips** (no second batch run) and the first completes; assert a different channel is NOT blocked.
- **Fix-2 interplay test:** assert a lock-skip does **NOT** write/bump the `topicization:reescalation:<channel>` marker (skip ≠ failed attempt).
- **Cross-path test:** assert the scheduler re-escalation path and the `pipeline_service`/dispatch path both take the SAME lock (so they actually exclude each other).

---

## Suggested first actions in the new session

1. **Read-only re-confirm the anchors** above (the tree may have moved if anything landed after `7ad3264`): `topicization_service.py:123` / `:243` / `:313` / `:337-354` / `:363-403`, `topicization.py:186` / `:247` / `:135`, `scheduler_service.py:59` / `:62-123` / `:275-285` / `:497-500`, `pipeline_service.py:62` / `:203-207`, `pipeline_dispatch_service.py:50` / `:95` / `:118-124` / `:156` / `:183` / `:226`, `api/routes/pipeline.py:56-127`, `settings.py:388`.
2. **Implement option (a)** — generalize `_source_processing_lock` into a channel-keyed topicization advisory lock with a new namespace; wrap `run_topicization`; benign skip-on-not-acquired (no raise; no Fix-2 marker arming). Add the tests above.
3. **Self-review + Bugbot review** the diff. Then **STOP** and await explicit user approval before commit/deploy.

---

## Current prod / repo state to record

- **Prod HEAD = `7ad3264`** (BUG-071 Fixes 1–3 + crash-path cooldown arming, deployed & validated). **Rollback ref = `7ad3264`.**
- **Anthropic balance EXHAUSTED** (drained by the BUG-071 validation session). Do not refill until BUG-072 ships or the operator is actively watching (per the top warning). BUG-071 Fix 2 being live makes the *re-burn loop* safe; the *within-window duplicate* is still open.
- **Relevant settings defaults** (`tg_parser/config/settings.py`): `topicization_reescalation_cooldown_s=3600` (`:388`); `scheduler_max_concurrent_sources=2` (`:641`); `scheduler_max_instances=2` (`:655`). `SCHEDULER_SOURCE_LOCK_NS=0x5C40` (`scheduler_service.py:59`).
- **Observability already in place** (reuse for validation): `tg_parser_topicization_failed_batches_total` Counter (`api/metrics.py:142`, helper `record_topicization_failed_batch` at `:779`); `tg_parser_llm_tokens_total{model="claude-sonnet-4-6"}`; BUG-071 truncation/token-burn alert rules.
- **Known unrelated pre-existing test failure** (out of scope; fails on clean HEAD too — ignore): `tests/test_mcp_management.py::TestGetAllChannelStats::test_batch_stats_degrades_to_zeros_on_aggregation_error`.

---

## Conventions to respect (from `AGENTS.md`)

- Branch `main`. **NO `git commit` without an explicit user request.**
- Accepted ADRs in [`docs/adr/`](../../adr/) and JSON Schemas in [`docs/contracts/`](../../contracts/) are **binding**.
- Do **NOT** create or edit `docs/methodology/**` from this workspace (it lives in a separate worktree; absent on `main` by design).
- No direct edits to `pyproject.toml` / `requirements.txt` without an explicit request.
- Tests per [`tests/README.md`](../../../tests/README.md): default / PR / max-local modes; use `TEST_POSTGRES=1` for the advisory-lock behavior (this fix needs it).
- Quality lifecycle: [`docs/quality/AGENT_PLAYBOOK.md`](../../quality/AGENT_PLAYBOOK.md). Log the fix under **BUG-072** in [`docs/notes/BUG_LOG.md`](../BUG_LOG.md) (BUG-071 is the latest used).

---

## Deploy procedure reference (only after explicit approval)

`PRODUCTION_DEPLOYMENT.md` § Updating (canonical): backup → `git pull --ff-only` → `docker compose build tg_parser` → `db upgrade --db all` (run as a no-op check; **option (a) needs NO migration** — advisory locks are runtime-only; if you instead pick option (b) with a new table, verify the migration applies cleanly) → `docker compose up -d` → `docker compose --profile bot up -d --force-recreate --no-deps tg_bot` → smoke (`/health`, `/metrics`, `docker compose ps`). Force-recreate prometheus ONLY if `docker/prometheus*` changed. All via `ssh prod` (`212.72.189.15:2296`, app dir `/home/user/TG_parser`). **Rollback = `git checkout 7ad3264 && docker compose build tg_parser && docker compose up -d`.**
