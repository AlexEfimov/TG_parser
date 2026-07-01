# DESIGN (FINAL) — BUG-076: checkpoint / resumable persistence in FULL topicization

**Created:** 2026-07-01. **Status:** DESIGN FINAL (architecture decided: **full multi-chunk resume**). READ-ONLY investigation done; **no code changed**. Awaiting implementation approval.
**Repo:** `/Users/alexanderefimov/TG_parser`, branch `main`.
**Prod HEAD this note targets:** `b7285d7` (tip of the BUG-071→075 token-burn hardening chain; working tree at `bd098e5` = `b7285d7` + one docs-only commit, so all code files are byte-identical).
**Rollback ref:** `23764b7` (`fix(topicization): add non-blocking per-channel advisory lock … (BUG-072)`).
**Tracks:** BUG-076 in [`BUG_LOG.md`](BUG_LOG.md). Related watch: [`POST_REFILL_WATCH_RUNBOOK_2026-06-30.md`](POST_REFILL_WATCH_RUNBOOK_2026-06-30.md).

> **Workflow convention (binding):** design handoff only. Implementation must **STOP before commit/deploy and await explicit user approval** — mirroring BUG-071..075 (build + test → self-review → Bugbot → approval → commit → deploy → post-deploy watch). No `git commit`, no prod mutation, no billing top-up as part of this design.

> **Decision recorded (2026-07-01):** the user chose **full multi-chunk resume** — the full-topicization path itself chunks the corpus, persists per chunk, and RESUMES across ticks/runs until the whole channel is topicized — over the cheaper "A-seed + reconcile-converge" hybrid. Rationale: higher final quality (true cross-batch consolidation) and a definitive fix ("do it once, don't revisit"). The extra machinery (an explicit resume driver + transactional per-chunk commits + a checkpointed cross-chunk merge) is accepted and is **mandatory**, not optional — see §5.

---

## 1. Problem statement

After the Anthropic balance was refilled, a single **legitimate** FULL re-topicization of `murashko_med` (0 topic cards + ~15.5K-doc backlog, ~353 batches of 50, ~6M+ Sonnet tokens) ran through its entire batch-generation phase, then **crashed at the final `_merge_topics` consolidation on `AnthropicBillingError`** and persisted **ZERO** topic cards. Net: ~6.6M tokens spent → 0 durable cards.

This is **not** a re-burn / storm bug. The BUG-071..075 fixes all HELD (single escalation, cooldown armed on the crash, shrink-split, R1=0, reconcile bounded). The work was **productive**; it just persisted nothing. The gap is threefold:

1. **Not crash-safe** — full topicization persists cards only at an atomic END-merge (all-or-nothing). A failure anywhere before the persist loop discards every batch.
2. **Not resumable** — a re-run starts from batch 1; no checkpoint state exists.
3. **Not fundable-incrementally / not budget-aware** — there is no per-run token cap, so a run cannot stop cleanly at a durable boundary when the balance is low. A refill that cannot fund the ENTIRE run in one pass is re-vaporized (a **refill-trap**).

Cold-start 0-card channels are the trap: largest backlog + highest merge cost + they are exactly what the 0-card→full trigger routes into the monolithic run.

**The irony to leverage:** the BUG-075 incremental/reconcile path is already the safe pattern (per-batch persist, at-most-once marker, per-tick cap, converges over ticks, nothing lost on crash). The full path is its opposite. The fix brings the full path up to that standard **while keeping its global cross-batch merge quality**.

---

## 2. Verified anchors (from the READ-ONLY investigation)

All line numbers verified at prod HEAD `b7285d7`.

### 2.1 The full path — all-or-nothing persistence

`tg_parser/processing/topicization.py :: TopicizationPipelineImpl.topicize_channel` (`:222-399`):

- `:261` — load ALL docs into memory: `documents = await self.processed_doc_repo.list_by_channel(channel_id)`.
- `:270-280` — build `candidates` for the WHOLE corpus (in memory).
- `:283` — `BATCH_SIZE = 50` (hard-coded in the full generate path; DISTINCT from `settings.topicization_batch_size=50` used by the incremental discover path).
- `:311-354` — large-channel path: split into batches, `asyncio.gather(*(_gen_batch...), return_exceptions=True)` under `asyncio.Semaphore(batch_concurrency)` (default 5, `:324`), accumulating `all_batch_topics` **in memory**. A per-batch exception is counted (`failed_batches`) but does NOT crash the gather.
- `:356-357` — `if all_batch_topics: raw_topics = await self._merge_topics(all_batch_topics, candidates)` — the FINAL single-LLM consolidation call.
- `:364-380` — build `topic_cards` in memory from `raw_topics`.
- **`:391-399` — Step 6, the ONE AND ONLY persistence point:** `for card in topic_cards: await self.topic_card_repo.upsert(card)` (`upsert` at `:394`). Reached ONLY after `_merge_topics` returns.

### 2.2 Why the merge crash loses everything

`_merge_topics` (`:570-725`):

- `:632` — the merge LLM call `await self.llm_client.generate_with_usage(...)`.
- `:667` — `except json.JSONDecodeError` → fall back to unmerged `all_batch_topics`.
- `:683` — `except (RuntimeError, ValueError, OSError)` → fall back to unmerged.
- **`AnthropicBillingError` is a direct `Exception` subclass** (`tg_parser/processing/llm/errors.py:4`), so it is **NOT** caught by either clause → it propagates out of `_merge_topics` → out of `topicize_channel` → the Step 6 persistence loop (`:391`) is **never reached** → all ~353 batches of work in `all_batch_topics` are discarded.
- `LLMCallTimeoutError` subclasses `TimeoutError` (`errors.py:12`), also not caught by the merge guards → same propagation. The generate-phase batches are protected by `return_exceptions=True`; the **merge** call is the unprotected single point of failure.

### 2.3 In-memory state a crash loses; restartability

Across all batches before the merge the run holds, in memory only: `documents`, `candidates`, and `all_batch_topics`. None is persisted incrementally. `topicize_channel` keeps **no checkpoint state** and there is **no resume marker**, so a re-run reloads the full corpus (`:261`) and regenerates from batch 1. Re-escalation calls `run_topicization(force=False)` (`topicization_service.py:761`), but with 0 existing cards there is nothing to skip → full redo. **The run is not restartable today.**

### 2.4 The `should_reescalate` 0-card→full trigger + BUG-071 arms

`tg_parser/services/topicization_service.py`:

- `:697` — `should_reescalate = len(existing_cards) == 0 and len(new_docs) > 0` — **the ONLY automatic caller of the full path.**
- `:708-709` — `reconcile_only=True` forces it `False` (BUG-075 learning 5).
- `:711-750` — BUG-071 Fix-2 cooldown gate: reads the synthetic `_reescalation_marker_ref` and, if within `topicization_reescalation_cooldown_s` (default 3600s), suppresses the full run and falls through to cheap incremental Phase 1/2.
- `:752-799` — the escalation: `full = await run_topicization(...)` wrapped in `try/except Exception`. **Crash path (`:767-799`): arms the cooldown marker and re-raises** — it does NOT recount/clear.
- `:843` — the **clean-return** branch (`else`); `:858-882` — the persisted-card-recount clear/arm — **runs ONLY on clean return, never on crash.**
- Advisory locks: `TOPICIZATION_LOCK_NS = 0x70C1` (full, `:232`), `INCREMENTAL_TOPICIZATION_LOCK_NS = 0x70C2` (incremental, `:238`); full lock holds a dedicated connection for the run (`:280-284`, `:311-333`).

**Critical corollary (drives §5.0):** because `:697` is the ONLY automatic full-path caller and it fires only at **0 cards**, once the first chunk persists >0 cards `should_reescalate` is permanently `False` → **nothing re-invokes the full path** → a naïve multi-chunk resume is UNREACHABLE. This is why an explicit resume driver (§5.0) is mandatory.

### 2.5 The safe pattern already in-tree (BUG-075 incremental/reconcile)

`_run_incremental_topicization_locked` (`topicization_service.py:626-1121`):

- **Per-batch persistence:** discover batch loop (`:970-1033`) persists AS IT GOES — `:995-996` *"Batch checkpoint: persist each successful batch immediately …"*; `_update_bundles_for_assignments(...)` (`:997`) + `topic_card_repo.upsert(card)` (`:1010`) run INSIDE the loop.
- **New-card bootstrap:** discover DOES create new cards from `llm_result["new_topics"]` (`topicization.py:1453-1467`, upsert at `topicization_service.py:1010`) — so reconcile CAN cold-start a 0-card channel (relevant to the rejected hybrid, §4).
- **At-most-once progress marker:** `discover_attempted` synthetic `processing_failures` ref (`:150-221`), collision-safe with real `tg:<ch>:<type>:<id>` refs.
- **Bounded per-tick + converges:** `run_reconciliation_for_channel` (`:1209+`) caps the feed at `settings.topicization_reconcile_max_docs` (default 200, `:1336-1339`), passes `reconcile_only=True` + `defer_if_locked=True`, recomputes candidates each tick. **Convergence semantics:** every uncovered doc is *attempted at most once* (`_mark_discover_attempted` `:185-221`) and never re-fed → it converges to "every doc attempted ≤1×," **not** to ~100% coverage (a residual permanently-uncovered set remains). This is why the hybrid is quality-inferior (§4).

### 2.6 Watchdog premise — CORRECTED

`scheduler_service.py:308-319`: the `asyncio.wait_for(..., timeout=scheduler_source_timeout_s)` (1800s) wraps **ONLY** `run_full_pipeline(source_id=..., mode="incremental", skip_topicize=True, ...)`. The `incremental_topicization` stage (`:512`, which contains the re-escalation full run) and the reconcile stage (`:710`) are **NOT** wrapped in any `asyncio.wait_for`. **Therefore there is currently NO wall-clock bound on topicization at all** (the `settings.py` comment implying `topicization_reconcile_max_docs` keeps cost under `scheduler_source_timeout_s` is inaccurate). The token budget kill-switch (§5.3) + the per-invocation chunk cap (§5.0) are the ONLY halts we will have — this is designed for below.

### 2.7 Observability gaps

- **`record_topic_created`** (`api/metrics.py:681`) is called on the full path ONLY from the `run_topicization` wrapper (`topicization_service.py:463-466`), AFTER `topicize_channel` returns → the metric is flat 0 during the whole run and on a crash → `TopicizationBurnNoProgress` (`docker/prometheus/alerts.yml:343-353`) false-positives on a productive run. **NOTE (double-count hazard):** the incremental path already emits per card (`:1016`); if we ALSO emit per-chunk in the full path, the wrapper loop at `:463-466` MUST be removed/guarded or every full run double-counts (§6).
- **`tg_parser_topicization_failed_batches_total`** documents "only `topicization_generate` is emitted today" (`metrics.py:147-148`) → a **merge**-stage crash is invisible to `TopicizationFailedBatchesHigh`.

### 2.8 Schema + card-id determinism (drives the transactional requirement)

- `topic_cards` (`_metadata.py:608-653`): PK `id`; `upsert` is `ON CONFLICT(id) DO UPDATE` (`topic_card_repo.py:76`).
- **Card ids are LLM-derived, NOT stable across re-runs:** `topic_id = make_topic_id(primary_anchor_ref)` (`topicization.py:808-810`); `make_topic_id(ref) = f"topic:{ref}"` (`domain/ids.py:83`); `primary_anchor_ref = anchors[0].anchor_ref` where anchors are sorted by `(-score, anchor_ref)` (`:879-882`) and `score` comes straight from LLM output (`raw_anchor.get("score", 0.0)`, `:764`). Anthropic is not bit-deterministic even at temperature 0, and the merge's group→primary selection can shift → **re-running a partially-persisted chunk can mint DIFFERENT ids for the same underlying topic → duplicate/orphan cards.** Whole-chunk skip is safe (ids preserved); partial-chunk re-run is NOT. → §5.1 requires an atomic per-chunk commit.
- `processing_failures` (`_metadata.py:584-597`): PK `source_ref`, cols `channel_id/attempts/last_attempt_at/error_class/error_message/error_details_json`; `record_failure` sets `attempts = excluded.attempts` on conflict (`processing_failure_repo.py:51`) — the **caller controls `attempts`** (not auto-incremented). Already hosts the BUG-071 `topicization:reescalation:<channel>` and BUG-075 `topicization:discover_attempted:<ref>` markers — the no-migration synthetic-ref home reused here.

---

## 3. Design goals

1. **Crash-safe** — a crash loses **at most one chunk**, never the whole run.
2. **Resumable** — a later tick/run continues from the checkpoint, not from batch 1 — driven by an **explicit trigger** independent of card count (§5.0).
3. **Fundable-incrementally** — partial budget → partial **durable** progress.
4. **Budget-aware** — a hard per-run token-budget kill-switch halts cleanly at a persisted checkpoint BEFORE exhausting the balance (caps productive spend too).
5. **No regression to BUG-071..075** — `0x70C1`/`0x70C2` locks, cooldown + crash-arm, `reconcile_only` hard-disable, `discover_attempted` semantics all preserved; no storm; no doc abandonment.
6. **Quality parity (target):** the multi-chunk result approximates the monolithic global merge closely via a checkpointed, idempotent cross-chunk consolidation pass (§5.4) — this is the reason the user chose this over the hybrid.

---

## 4. Considered and REJECTED alternative — the "A-seed + reconcile-converge" hybrid

**Shape:** the full path does ONE bounded, crash-safe, budget-capped chunk purely to move the channel off 0 cards, then the proven BUG-075 reconcile path converges the rest.

**Why rejected (per the user's decision):** reconcile is **attempt-convergent, not coverage-complete** (§2.5) — every doc gets ≤1 discover attempt and is never retried, and there is NO global cross-corpus merge, so a first-ever topicization of a huge backlog yields **more fragmented / near-duplicate topics** and a residual permanently-uncovered set. The user prioritized quality + finality, so the hybrid's cheaper machinery does not justify its lower-quality, likely-to-be-revisited outcome. It also silently makes the elaborate full-path resume machinery dead code. **We keep reconcile only as the standing steady-state hook it already is (BUG-075), not as the cold-start engine.**

(The pure monolithic-with-bigger-budget "just refill more" non-fix is also rejected: it does not fix crash-safety or the refill-trap, only defers them.)

---

## 5. Concrete mechanism (FINAL — full multi-chunk resume)

### 5.0 Explicit checkpoint-driven resume trigger (MANDATORY — closes the §2.4 corollary)

Because `should_reescalate` (`:697`) fires only at 0 cards, we add a resume driver that does NOT depend on card count:

- **Marker-driven:** while a `topicization:full_checkpoint:<channel_id>` marker exists and is not complete, the channel has an in-progress full run to resume.
- **Where it hooks:** in `_process_source` (`scheduler_service.py`), add a best-effort stage — ordered BEFORE the reconcile hook — that, for the current source, checks for a live full-checkpoint marker and, if present, calls a **resume entrypoint** `run_topicization(..., resume=True)` (or a thin `resume_full_topicization(channel_id)`), which takes `0x70C1` and continues from the checkpoint. This runs every tick until the marker clears (mirrors the standing BUG-075 reconcile hook: never pollutes `stage_errors`, never crashes the tick).
- **Per-invocation bound (also the missing time-bound from §2.6):** a single invocation processes at most `topicization_full_max_chunks_per_invocation` chunks (new setting, e.g. default 1–2) OR until the token budget (§5.3) trips, then returns a benign "partial, resumable" result. So each tick returns promptly and the backlog drains over multiple ticks — giving us the wall-clock safety that the un-wrapped topicization stage otherwise lacks.
- **Coexistence with `should_reescalate` + cooldown:** the FIRST run is still kicked off by `should_reescalate` (0-card→escalate) exactly as today; it persists chunk 1 (channel now >0 cards) and writes the checkpoint. From then on, the resume driver — not `should_reescalate` — carries it to completion. The cooldown gate is unaffected (a resume is not a re-escalation; it does not re-enter the `:711-750` gate). `force=True` manual runs (MCP/CLI) likewise write a checkpoint and are picked up by the same resume driver.

### 5.1 Chunked full run with per-chunk persist + ATOMIC commit

- **Chunking:** partition the ordered batch list into chunks of `topicization_full_chunk_batches` batches (new setting, e.g. default 20 → ~1000 docs/chunk at BATCH_SIZE=50). Order is deterministic (stable by `source_ref`) so resume is well-defined.
- **Per-chunk flow** inside a new `_topicize_channel_chunked` (delegated to from `topicize_channel`):
  1. Generate the chunk's batches (existing `_gen_batch` + `asyncio.gather(return_exceptions=True)`, unchanged BUG-071 shrink/split).
  2. Merge WITHIN the chunk (`_merge_topics` over the chunk's `all_batch_topics`), **wrapped so `AnthropicBillingError`/`LLMCallTimeoutError` are treated as a clean, resumable halt** (§5.3), not a silent unmerged fallback and not an unpersisted crash.
  3. Build the chunk's cards.
  4. **ATOMICALLY co-commit, in ONE processing-engine transaction:** the chunk's `topic_card_repo.upsert`s **and** the checkpoint advance (§5.2). Ordering within the txn: upsert cards → advance checkpoint → commit. Because `topic_cards` and `processing_failures` live in the same engine, this is a single transaction with **no migration**.
  5. Proceed to the next chunk (subject to the per-invocation cap §5.0). On any crash, chunks 1..k-1 are durable AND their checkpoint is consistent; chunk k either fully committed or not at all → **no partial-chunk state ever exists**, so the non-deterministic-id hazard (§2.8) cannot produce duplicates.
- **Resume:** at (re)start, read the checkpoint; skip chunks marked complete; regenerate only from the first incomplete chunk. Whole-chunk skip preserves ids; the atomic commit guarantees there is never a partially-persisted chunk to re-run.

> **Why atomic (not "upsert is idempotent"):** the earlier draft's claim that re-persisting a partially-landed card is idempotent is FALSE for partial chunks (§2.8 — ids are LLM-derived and shift on re-run). Atomicity converts "partial chunk" into "chunk not started," which is the only safe way to make resume duplicate-free without deterministic ids.

### 5.2 Checkpoint / progress marker — synthetic `processing_failures` ref (NO migration)

Mirror BUG-071/075: a synthetic, collision-safe `source_ref` `topicization:full_checkpoint:<channel_id>` in `processing_failures`:

- `attempts` → last completed chunk index (caller-set; §2.8 confirms `attempts` is caller-controlled).
- `error_details_json` → `{run_id, corpus_fingerprint, chunks_total, chunks_done, batches_done, tokens_spent_cumulative, final_merge_done: bool, last_chunk_at}`.
- `last_attempt_at` → checkpoint timestamp.
- **Cleared** (delete_failure) only when the run FULLY completes (all chunks done AND `final_merge_done`).

**Collision-safety:** a real doc ref is `tg:<ch>:<type>:<id>`; the processing skip-set matches the REAL ref, so this synthetic row is loaded into `failure_map` but never matched → it can never skip a doc from processing (same argument as the two existing markers). `corpus_fingerprint` (e.g. `count + max(updated_at)` of `list_by_channel`) lets resume DETECT a materially-changed corpus and restart cleanly instead of resuming a stale plan.

**No migration, WITH robust checkpointing:** achievable precisely because the atomic co-commit (§5.1) uses the same engine — "no migration" and "robust checkpoint" are not in tension. A dedicated `topicization_runs` table (cleaner/queryable) is a deferred follow-up, not required for correctness.

### 5.3 Budget guardrail — per-run token kill-switch (COUPLED to sequential chunks)

- New setting `topicization_full_run_token_budget` (0 = disabled). The pipeline accumulates `total_input_tokens`/`total_output_tokens` (`topicization.py:176-177`), reset per invocation (`:245`-region) — i.e. they measure THIS invocation. The checkpoint's `tokens_spent_cumulative` carries spend across resumes for observability.
- **Coupling (correction):** the current single `asyncio.gather` over ALL batches (`:337-340`) **cannot** be interrupted at a token boundary. So the budget cap is NOT an orthogonal add-on — it **requires** the sequential-chunk refactor (§5.1). Enforce the check at **chunk boundaries** (after gather+merge+atomic-commit, before the next chunk). Within-chunk overshoot is bounded to ≤ one chunk's tokens because `batch_concurrency=5` (semaphore `:324`) caps in-flight batches.
- **On trip:** halt cleanly at the chunk boundary (current chunk already durably committed), log a distinct `topicization_full_run_budget_halt`, increment the budget-halt metric, and return a benign "partial, resumable" result (NOT an exception, NOT a failed-batch storm). The resume driver (§5.0) continues next tick.
- Decide `budget` scope explicitly: **per-invocation** cap (simple; pairs with the per-invocation chunk cap §5.0) plus a separate cumulative counter for dashboards. This guarantees no single refill can be single-handedly vaporized — the run stops at a durable line before exhaustion.

### 5.4 Cross-chunk merge — first-class, checkpointed, idempotent (quality parity)

Chunking only APPROXIMATES the monolithic global merge (two chunks can independently mint near-duplicate cards with different primary anchors → different ids). To reach quality parity:

- **Within a chunk:** `_merge_topics` runs as today → coherent local dedup, atomically persisted.
- **Cross-chunk pass (after all chunks done):** a bounded consolidation over the PERSISTED card set (tens–low-hundreds of cards, NOT the corpus, so it is cheap):
  - Detect near-duplicate cards (embedding cosine + keyword Jaccard, reusing the existing cross-channel-linking similarity machinery) and MERGE them under the surviving (lowest-ordered / deterministic) id, moving bundles/anchors and deleting the merged-away ids.
  - **Idempotent + checkpointed:** run under `0x70C1`; record `final_merge_done` in the checkpoint only after the merge commits; a crash here leaves chunk cards durable (slightly more fragmented, still covering docs) and `final_merge_done=false`, so a resume redoes ONLY the cheap final pass. Re-running the pass on an already-merged set is a no-op (no remaining near-duplicates above threshold).
  - **Budget it too:** if the pass itself uses an LLM step, it is subject to the same budget/halt discipline.
- **Honest quality note:** result ≈ (not =) the old single global merge; the cross-chunk pass closes most of the gap, and any residual fragmentation is strictly better than 0 cards.

### 5.5 Interaction with existing guarantees (no BUG-071..075 regression)

- **Advisory locks:** the chunked run + every resume execute under `channel_topicization_lock` (`0x70C1`), so two resumes cannot race; incremental/reconcile keeps `0x70C2`; no new namespace. The `0x70C1` dedicated connection is **already** held across the whole monolithic run today (`:280-284`) — chunking adds NO new idle connection (no learning-4 regression). The per-invocation cap (§5.0) actually SHORTENS per-invocation lock-hold time vs today. (Pre-existing caveat, mildly reduced: a pooled idle-timeout dropping the advisory-lock connection mid-run.)
- **`should_reescalate` + cooldown:** the crash path (`:767-799`) still arms the cooldown marker and re-raises — unchanged. **Correction to the earlier draft:** the persisted-recount clear (`:858-882`) runs ONLY on the clean-return branch (`:843`), NOT on crash — so we do the recount-based clear on the **budget-halt (clean return)** path, and leave crash-arming as-is. Harmless either way once >0 cards (no escalation fires). Key win: the first committed chunk moves the channel off 0 cards, so `should_reescalate` never re-routes it into a monolithic redo — the **resume driver (§5.0)** carries it instead.
- **`reconcile_only`:** still forces `should_reescalate=False`; the full-checkpoint marker is a SEPARATE synthetic ref, never interfering with `discover_attempted`/`reescalation` rows.
- **Shared `processing_failures`:** three synthetic-ref classes now live there (reescalation = 1/channel, full_checkpoint = 1/channel, discover_attempted = 1/doc). Guard any AGGREGATE failure metric/alert against inflation from these synthetic rows (they are not real per-message failures).

---

## 6. Observability fixes (close the `TopicizationBurnNoProgress` blind spot)

- **Wire `record_topic_created` into the full path per-chunk** (inside the atomic commit, as each chunk's cards persist) — so `tg_parser_topics_created_total` rises during a productive run and `TopicizationBurnNoProgress` stops false-positiving. **MANDATORY paired change:** remove/guard the wrapper emit at `topicization_service.py:463-466`, else every full run double-counts. (Add a test asserting no double-count — §8.)
- **Emit `topicization_merge` (and per-chunk) failed-batch counts** to `tg_parser_topicization_failed_batches_total` so a merge-stage halt is visible to `TopicizationFailedBatchesHigh` (`metrics.py:147-148` currently emits only `topicization_generate`).
- **New metrics** (each a small `metrics.py` counter/gauge + one emit site, no migration):
  - `tg_parser_topicization_full_run_tokens_total{channel_id}` — cumulative per-run token spend (feeds budget guard + cost dashboard).
  - `tg_parser_topicization_full_run_chunks{channel_id}` (gauge chunks_done/chunks_total) — live progress.
  - `tg_parser_topicization_full_run_budget_halt_total{channel_id}` — clean budget halts (benign, watchable).
  - `tg_parser_topicization_full_run_resume_total{channel_id}` — resumes (a sustained rate with no completion = a channel that never finishes → investigate).
- **Suggested alerts:** budget-halt sustained (info/warn); resume-without-completion sustained (warn — non-convergence); keep `TopicizationBurnNoProgress` as a now-accurate backstop.

---

## 7. Migration / schema impact

- **None required.** Checkpoint lives in existing `processing_failures` via a synthetic `source_ref` (§5.2); the atomic co-commit uses the shared processing engine (§5.1). Deploy is code-only (matches BUG-071/075).
- **New settings** (config only, no migration): `topicization_full_chunk_batches`, `topicization_full_max_chunks_per_invocation`, `topicization_full_run_token_budget` (0=off). Per workspace constraint, `pyproject.toml`/`requirements.txt` untouched.
- A dedicated `topicization_runs` table is an OPTIONAL later follow-up (queryability only).

---

## 8. Test plan

Unit + `TEST_POSTGRES=1` integration (mirroring `tests/test_bug071_*` / `test_bug075_*`; the txn/marker/lock behavior needs a real Postgres):

1. **Crash-mid-run → resume → cards persist:** inject `AnthropicBillingError` at `_merge_topics` and at a mid-chunk generate → assert chunks 1..k-1 cards are DURABLE, the checkpoint is consistent, and a resume run persists the remaining cards WITHOUT regenerating completed chunks.
2. **Merge-exception coverage:** `AnthropicBillingError` / `LLMCallTimeoutError` at the merge site are handled as a clean resumable halt (commit + checkpoint), not a silent unmerged fallback and not an unpersisted crash.
3. **Resume driver (§5.0):** with a live full-checkpoint marker and >0 cards (so `should_reescalate` is False), assert the scheduler resume stage re-invokes the full path each tick until the marker clears; assert it does NOT double-drive alongside `should_reescalate`/reconcile; assert `force=True` runs are also resumed.
4. **Atomic chunk / no duplicate cards on resume:** crash MID-chunk (after some `upsert`s would have landed in a non-atomic design) → assert NO orphan/duplicate cards (the transaction rolled the partial chunk back) → resume regenerates the chunk cleanly. This is the highest-risk case; it must be explicit.
5. **Budget cap clean halt:** with a small `topicization_full_run_token_budget`, assert the run stops at a chunk boundary, persists what it produced, arms no storm, increments the budget-halt metric, and is resumable to completion over subsequent ticks.
6. **Cross-chunk merge idempotency:** after chunked persist, assert the cross-chunk pass dedups near-duplicate cards deterministically, records `final_merge_done`, and re-running it is a no-op (no new merges, no duplicates).
7. **No `record_topic_created` double-count:** assert one increment per card total (per-chunk emit + removed/guarded wrapper emit).
8. **Cold-start convergence:** a 0-card large-backlog channel completes over multiple chunks/ticks; assert coverage is **monotonically non-decreasing**, the channel leaves 0-card state after the FIRST chunk (so `should_reescalate` no longer routes a monolithic redo), and the checkpoint clears on completion. (Coverage target: full — via the global-merge chunked path — NOT the reconcile plateau.)
9. **No BUG-071..075 regression:** re-run `test_bug071_*`..`test_bug075_*` — cooldown arm/clear, `0x70C1`/`0x70C2`, `reconcile_only` hard-disable, `discover_attempted`, no-storm all green; add a test that the full-checkpoint marker never collides with the reescalation/discover_attempted rows or the processing skip-set.

---

## 9. Risks / trade-offs

- **Cross-chunk merge quality:** per-chunk merge + a cross-chunk pass ≈ (not =) one global merge (§5.4). Mitigation: the bounded similarity-based consolidation; residual fragmentation ≫ better than 0 cards.
- **Checkpoint staleness:** corpus changing between runs → resuming a stale plan. Mitigation: `corpus_fingerprint` → resume detects change and restarts cleanly.
- **Transaction scope:** the atomic per-chunk commit spans `topic_cards` + `processing_failures`; verify both repos share one engine/session so a single transaction is genuinely atomic (they do today — confirm in implementation).
- **Marker growth:** one more synthetic-ref class in `processing_failures` (1 row/channel, cleared on completion). Mitigation: namespaced + aggregate-metric guard (§5.5).
- **Budget under-funding:** too-small a budget → many resumes, slow convergence. Mitigation: setting, default generous (or 0=off), watch the resume metric.

---

## 10. Rollout / roll-forward sketch

1. Implement behind additive settings (defaults chosen so behaviour is unchanged unless enabled): (a) chunked per-chunk generate+merge+ATOMIC persist + checkpoint; (b) the resume driver in `_process_source`; (c) the budget kill-switch + per-invocation cap; (d) the cross-chunk merge pass; (e) observability wiring (incl. the wrapper double-count removal).
2. **STOP before commit — self-review checklist (resume-driver + atomic-chunk first) → Bugbot review** (focus: chunk atomicity/no-duplicates, resume-driver correctness, checkpoint collision-safety, lock topology, no-abandonment, budget-halt cleanliness, no double-count), then **explicit user approval**, then commit.
3. Deploy to prod (code-only, no migration; if new alert rules are added, Prometheus force-recreate per `PRODUCTION_DEPLOYMENT.md`). Rollback ref `23764b7`.
4. **Controlled first exercise:** with the fix live, set `topicization_full_run_token_budget` conservatively and RESUME `murashko_med` (currently `status='paused'`) so the first run is guaranteed to halt-and-persist rather than attempt the whole 6M-token pass. Watch per the POST-REFILL runbook: chunks persisting, `topics_created` rising during the run, budget-halt/resume/chunks metrics, cooldown markers, no storm.
5. **Roll-forward criteria:** cards persist incrementally, a mid-run halt/crash loses ≤1 chunk, resume completes coverage, `TopicizationBurnNoProgress` no longer false-positives, BUG-071..075 signals steady. If any runbook rollback trigger fires: pause the channel (fastest kill-switch) then roll back to `23764b7`.

---

## 11. Open decisions for the user (post-finalization)

Architecture is DECIDED (full multi-chunk resume). Remaining tunables to confirm at implementation time:

- **Defaults:** `topicization_full_chunk_batches` (e.g. 20), `topicization_full_max_chunks_per_invocation` (e.g. 1–2), `topicization_full_run_token_budget` (0=off vs a concrete cap for the first murashko_med exercise).
- **Checkpoint home:** synthetic `processing_failures` ref (no migration, recommended) vs a dedicated `topicization_runs` table (cleaner, needs migration) — recommend shipping synthetic first.
- **Which new observability metrics/alerts** land in the first cut vs deferred.
- **Cross-chunk merge similarity:** reuse the cross-channel-linking cosine+Jaccard thresholds as-is, or a dedicated threshold for same-channel card dedup.
