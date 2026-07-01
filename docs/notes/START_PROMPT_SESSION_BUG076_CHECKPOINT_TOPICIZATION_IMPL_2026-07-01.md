# START_PROMPT — BUG-076: checkpoint / resumable persistence in FULL topicization (IMPLEMENTATION)

**Created:** 2026-07-01. This is the **IMPLEMENTATION** start-prompt for BUG-076 — build the fix deliberately, do NOT rush.
**Branch:** `main`. **Repo:** `/Users/alexanderefimov/TG_parser`.
**Prod HEAD:** `b7285d7` (tip of the BUG-071→075 token-burn hardening chain). Working tree is at `bd098e5` = `b7285d7` + one docs-only commit, so every CODE file is byte-identical to prod; verify with `git rev-parse --short HEAD`.
**Committing SHA (this handoff's docs commit):** `<FILL-AFTER-COMMIT>` (the `docs(bug-076): …` commit that lands the design note, BUG_LOG entry, and this start-prompt).
**Rollback ref:** `23764b7` (`fix(topicization): add non-blocking per-channel advisory lock … (BUG-072)`).
**Status:** `open` / **design FINALIZED** (architecture decided: **full multi-chunk resume**; adversarial review incorporated). NO code changed yet.

> **The design note is the SOURCE OF TRUTH — READ IT FIRST, IN FULL:** [`DESIGN_BUG076_CHECKPOINT_TOPICIZATION_2026-07-01.md`](DESIGN_BUG076_CHECKPOINT_TOPICIZATION_2026-07-01.md). This start-prompt SUMMARIZES and POINTS TO it; it does not duplicate it. Also read the `### BUG-076` row in [`BUG_LOG.md`](BUG_LOG.md). Related watch: [`POST_REFILL_WATCH_RUNBOOK_2026-06-30.md`](POST_REFILL_WATCH_RUNBOOK_2026-06-30.md).

---

## ⛔ CRITICAL OPERATIONAL WARNINGS — READ FIRST

1. **`murashko_med` is preventively PAUSED** (`sources.status='paused'`) so the scheduler skips it (the scheduler runs only `status='active'` sources) and the refill-trap cannot re-trigger. **Do NOT resume it** until (a) the fix has shipped to prod AND (b) a bounded `topicization_full_run_token_budget` is set for the controlled first exercise. Resume command when the time comes: `UPDATE sources SET status='active' WHERE source_id='murashko_med';` (or MCP `resume_channel`).
2. **The Anthropic balance is EXHAUSTED / billing-blocked (dormant).** Refilling is a **separate manual USER action**, NOT part of this session. Design and TEST so that even a fresh refill **cannot be single-handedly vaporized** — a run must be able to stop at a durable, checkpointed boundary before it exhausts the balance.
3. **This is a CRASH-SAFETY / BUDGET class, NOT a re-burn / storm class.** The BUG-071..075 fixes all HELD (single escalation, cooldown armed on the crash, shrink-split, R1=0, reconcile bounded); the burned run was PRODUCTIVE work that simply persisted nothing. Every design decision must be checked against "does this regress BUG-071..075?" — the `0x70C1`/`0x70C2` locks, the cooldown + crash-arm, the `reconcile_only` hard-disable, the `discover_attempted` at-most-once semantics, and no-storm must all stay green. Do NOT reintroduce a token-burn surface.

---

## TL;DR — the bug and the chosen fix

**The bug (all-or-nothing END-merge persistence).** `TopicizationPipelineImpl.topicize_channel` (`tg_parser/processing/topicization.py`) loads the whole corpus, fans out ALL batches (`BATCH_SIZE=50`) accumulating `all_batch_topics` **in memory**, then calls `_merge_topics` — a FINAL single-LLM consolidation — and only AFTER that returns does Step 6 (`:391-399`) upsert the cards. That upsert loop is the **one and only** persistence point. `AnthropicBillingError` is a **direct `Exception` subclass** (`processing/llm/errors.py:4`), so it slips past `_merge_topics`'s `except json.JSONDecodeError` / `except (RuntimeError, ValueError, OSError)` guards → it propagates out → the persistence loop is **never reached** → all ~353 batches of work are discarded. Prod evidence (2026-07-01): a legitimate `murashko_med` full re-topicization (0 cards + ~15.5K docs, ~6.6M Sonnet tokens) crashed at `_merge_topics` and persisted **0 cards**. Because the channel stays at 0 cards, any refill that cannot fund the ENTIRE monolithic run in one pass re-vaporizes identically — a **refill-trap** on cold-start 0-card channels.

**The chosen fix (full multi-chunk resume).** The full-topicization path itself chunks the corpus, persists per chunk in an ATOMIC transaction, and RESUMES across ticks/runs until the whole channel is topicized — decided over the cheaper "A-seed + reconcile-converge" hybrid (rejected: reconcile is attempt-convergent, not coverage-complete → more fragmented topics + a residual permanently-uncovered set). The extra machinery (explicit resume driver + transactional per-chunk commits + a checkpointed cross-chunk merge) is **mandatory, not optional**. Quality parity + finality ("do it once, don't revisit") is the reason.

---

## The MANDATORY design pillars (each points to the design note)

Implement ALL of these; none is optional. Full detail in the design note §5–§6.

- **(a) Explicit checkpoint-driven resume trigger** in `_process_source` (design §5.0). **Mandatory** because `should_reescalate` (`topicization_service.py:697`) fires ONLY at 0 cards — the moment chunk 1 persists >0 cards, nothing re-invokes the full path, so a naïve multi-chunk resume would be UNREACHABLE. Add a best-effort stage (ordered BEFORE the reconcile hook) that, while a `topicization:full_checkpoint:<channel>` marker is live, calls a resume entrypoint (`run_topicization(..., resume=True)` or a thin `resume_full_topicization`) under `0x70C1`. Bound each invocation to `topicization_full_max_chunks_per_invocation` chunks (this is ALSO the missing wall-clock bound — §2.6: the 1800s watchdog does NOT wrap the topicization stage).
- **(b) Atomic per-chunk commit** (design §5.1). Per chunk: generate → merge-within-chunk → build cards → **ATOMICALLY co-commit the chunk's card upserts + the checkpoint advance in ONE processing-engine transaction** (upsert cards → advance checkpoint → commit). Atomicity is REQUIRED, not "upsert is idempotent": card ids are LLM-derived (§2.8) and shift on re-run, so a non-atomic partial chunk would mint duplicate/orphan cards. Atomicity converts "partial chunk" into "chunk not started."
- **(c) Per-run token-budget kill-switch, COUPLED to the sequential-chunk refactor** (design §5.3). New setting `topicization_full_run_token_budget` (0 = disabled). A single `asyncio.gather` over ALL batches CANNOT be interrupted at a token boundary — so the budget check is enforced at CHUNK boundaries (after gather+merge+atomic-commit, before the next chunk). On trip: halt cleanly at the durable boundary, log `topicization_full_run_budget_halt`, increment the budget-halt metric, return a benign "partial, resumable" result (NOT an exception, NOT a failed-batch storm). Per-invocation cap; separate cumulative counter for dashboards.
- **(d) Checkpointed, idempotent cross-chunk merge** for quality parity (design §5.4). After all chunks done, a bounded consolidation over the PERSISTED card set (tens–low-hundreds of cards, cheap — reuse the cross-channel-linking cosine+Jaccard machinery): dedup near-duplicate cards under the surviving deterministic id. Record `final_merge_done` in the checkpoint only after it commits; a crash here redoes ONLY the cheap final pass; re-running on an already-merged set is a no-op.
- **(e) Observability** (design §6). Wire `record_topic_created` INTO the full path per-chunk (inside the atomic commit) so `tg_parser_topics_created_total` rises during a productive run and `TopicizationBurnNoProgress` stops false-positiving — **MANDATORY paired change: REMOVE/guard the wrapper emit at `topicization_service.py:463-466`, else every full run double-counts** (the incremental path already emits per card at `:1016`). Emit `topicization_merge` failed-batch counts to `tg_parser_topicization_failed_batches_total` (currently only `topicization_generate`, `metrics.py:147-148`). Add the new full-run token / chunks / budget-halt / resume metrics.
- **(f) NO migration** (design §5.2, §7). The checkpoint is a synthetic `processing_failures` ref `topicization:full_checkpoint:<channel>` (collision-safe with the real `tg:<ch>:<type>:<id>` skip-set and with the existing `reescalation` / `discover_attempted` markers). `attempts` = last completed chunk index (caller-controlled); `error_details_json` carries `{run_id, corpus_fingerprint, chunks_total, chunks_done, batches_done, tokens_spent_cumulative, final_merge_done, last_chunk_at}`. Cleared only when the run FULLY completes. New settings are config-only (no migration). A dedicated `topicization_runs` table is a deferred follow-up.

---

## Key verified anchors (from the READ-ONLY investigation — design note §2)

All verified at prod HEAD `b7285d7`. Re-confirm nothing moved before editing.

- **Full path, all-or-nothing persistence:** `topicize_channel` `:222-399`; load all docs `:261`; build candidates `:270-280`; `BATCH_SIZE=50` hard-coded `:283`; large-channel `asyncio.gather(return_exceptions=True)` under `Semaphore` `:311-354` (concurrency default 5 `:324`); the merge `:356-357`; the ONE persistence loop `:391-399` (`upsert` `:394`).
- **Why the merge crash loses everything:** `_merge_topics` `:570-725`; merge LLM call `:632`; guards `except json.JSONDecodeError :667` and `except (RuntimeError, ValueError, OSError) :683`; **`AnthropicBillingError` is a bare `Exception` subclass** (`processing/llm/errors.py:4`) → not caught → propagates past Step 6. `LLMCallTimeoutError` subclasses `TimeoutError` (`errors.py:12`) → same.
- **`should_reescalate` trigger + arms:** `should_reescalate = len(existing_cards)==0 and len(new_docs)>0` `:697` (the ONLY automatic full-path caller); `reconcile_only=True` forces it False `:708-709`; cooldown gate `:711-750`; escalation try/except `:752-799`; **crash path arms cooldown + re-raises, does NOT recount/clear `:767-799`**; **clean-return recount-clear runs ONLY on the else branch `:843` / `:858-882`, NEVER on crash.**
- **Watchdog — CORRECTED:** `scheduler_service.py:308-319` `asyncio.wait_for(..., 1800s)` wraps ONLY `run_full_pipeline(..., skip_topicize=True)`; the `incremental_topicization` stage (`:512`, which contains the re-escalation full run) and the reconcile stage (`:710`) are **NOT** wrapped → there is currently NO wall-clock bound on topicization; the per-invocation chunk cap (§5.0) + token budget (§5.3) are the only halts.
- **Card-id determinism (drives atomicity):** ids LLM-derived — `topic_id = make_topic_id(primary_anchor_ref)` `topicization.py:808-810`; `make_topic_id(ref)=f"topic:{ref}"` `domain/ids.py:83`; primary anchor sorted by `(-score, anchor_ref)` with LLM-supplied score `:879-882`. → partial-chunk re-run can mint DIFFERENT ids for the same topic → duplicates. Whole-chunk skip is safe.
- **Schema (no migration):** `topic_cards` PK `id`, `upsert = ON CONFLICT(id) DO UPDATE` (`topic_card_repo.py:76`); `processing_failures` PK `source_ref`, `record_failure` sets caller-controlled `attempts` (`processing_failure_repo.py:51`) — already hosts the `reescalation` + `discover_attempted` markers.
- **Safe pattern already in-tree (BUG-075):** `_run_incremental_topicization_locked` persists per batch (`topicization_service.py:995-996` + `:997`/`:1010`), at-most-once `discover_attempted` marker (`:150-221`), bounded per-tick + converges (`run_reconciliation_for_channel :1209+`). The full path is its opposite; the fix brings it up to this standard while keeping the global cross-batch merge quality.
- **Observability gaps:** `record_topic_created` (`api/metrics.py:681`) called on the full path only from the wrapper `topicization_service.py:463-466` (AFTER return → flat 0 during run + on crash → `TopicizationBurnNoProgress` false-positive, `docker/prometheus/alerts.yml:343-353`); `tg_parser_topicization_failed_batches_total` emits only `topicization_generate` (`metrics.py:147-148`).

---

## Workflow (BINDING — same as BUG-071..075)

1. Implement behind **additive settings** (defaults chosen so behaviour is unchanged unless enabled): (a) chunked generate+merge+ATOMIC persist + checkpoint; (b) the resume driver in `_process_source`; (c) budget kill-switch + per-invocation cap; (d) cross-chunk merge; (e) observability wiring incl. the wrapper double-count removal.
2. **Tests** (`TEST_POSTGRES=1` where the txn / marker / lock behaviour needs a real Postgres — mirror `tests/test_bug071_*` / `test_bug075_*`).
3. **Self-review checklist** — write it out, with **resume-driver correctness + atomic-chunk (no-duplicate cards) FIRST** (they are the highest-risk pillars).
4. **Bugbot review of the diff** (focus: chunk atomicity/no-duplicates, resume-driver correctness, checkpoint collision-safety, lock topology, no-abandonment, budget-halt cleanliness, no double-count).
5. **STOP before commit — await EXPLICIT user approval.** No `git commit` before that.
6. On approval: gated full-suite test → commit → push → **deploy per `PRODUCTION_DEPLOYMENT.md`** (code-only, NO migration; force-recreate Prometheus ONLY if alert rules were added). Rollback ref `23764b7`.
7. **Post-deploy controlled first exercise:** set a conservative `topicization_full_run_token_budget`, then RESUME `murashko_med` so the first run is guaranteed to halt-and-persist rather than attempt the whole ~6M-token pass. Watch per [`POST_REFILL_WATCH_RUNBOOK_2026-06-30.md`](POST_REFILL_WATCH_RUNBOOK_2026-06-30.md): chunks persisting, `topics_created` rising during the run, budget-halt/resume/chunks metrics, cooldown markers, no storm.

---

## Test plan (design note §8 has the full list)

1. **Crash-mid-run → resume → cards persist** — inject `AnthropicBillingError` at `_merge_topics` and mid-chunk generate; assert chunks 1..k-1 durable + checkpoint consistent + resume finishes without regenerating completed chunks.
2. **Merge-exception coverage** — `AnthropicBillingError` / `LLMCallTimeoutError` at merge → clean resumable halt (commit + checkpoint), not silent unmerged fallback, not unpersisted crash.
3. **Resume driver (§5.0)** — live marker + >0 cards (so `should_reescalate` is False) → scheduler resume stage re-invokes each tick until the marker clears; no double-drive alongside `should_reescalate`/reconcile; `force=True` runs also resumed.
4. **Atomic chunk / no duplicate cards on resume** (highest-risk) — crash MID-chunk → NO orphan/duplicate cards (txn rolled back) → resume regenerates cleanly.
5. **Budget cap clean halt** — small budget → stops at chunk boundary, persists, arms no storm, increments budget-halt metric, resumable to completion.
6. **Cross-chunk merge idempotency** — dedups near-duplicates deterministically, records `final_merge_done`, re-run is a no-op.
7. **No `record_topic_created` double-count** — exactly one increment per card total (per-chunk emit + removed/guarded wrapper emit).
8. **Cold-start convergence** — 0-card large-backlog channel completes over chunks/ticks; coverage monotonically non-decreasing; leaves 0-card state after the FIRST chunk; checkpoint clears on completion.
9. **No BUG-071..075 regression** — re-run `test_bug071_*`..`test_bug075_*`; add a test that the full-checkpoint marker never collides with the reescalation/discover_attempted rows or the processing skip-set.

---

## Definition of Done

- A crash / mid-run halt loses **≤ 1 chunk**, never the whole run.
- Resume **completes coverage** (full, via the chunked global-merge path — not the reconcile plateau).
- The token budget **halts cleanly** at a durable chunk boundary and is resumable to completion.
- **No duplicate/orphan cards** on resume (atomic per-chunk commit).
- **No `record_topic_created` double-count** (per-chunk emit + wrapper emit removed/guarded).
- **BUG-071..075 signals stay green** (locks, cooldown arm/clear, `reconcile_only`, `discover_attempted`, no-storm).
- **No migration** shipped.

---

## Known-unrelated pre-existing test failures (IGNORE — fail on clean HEAD too)

- `tests/test_mcp_management.py::TestGetAllChannelStats::test_batch_stats_degrades_to_zeros_on_aggregation_error`.
- The scheduler `caplog` isolation flakes (log-capture cross-test contamination — order-dependent, not a real regression).

---

## Conventions to respect (from `AGENTS.md`)

- Branch `main`. **NO `git commit` without an explicit user request.**
- Do **NOT** create or edit `docs/methodology/**` from this workspace (separate worktree; absent on `main` by design).
- No direct edits to `pyproject.toml` / `requirements.txt` without an explicit request.
- Accepted ADRs (`docs/adr/`) and JSON Schemas (`docs/contracts/`) are **binding**.
- Quality lifecycle: `docs/quality/AGENT_PLAYBOOK.md`. Log the fix under **BUG-076** in `docs/notes/BUG_LOG.md`.
- Tests per `tests/README.md`: default / PR / max-local modes; use **`TEST_POSTGRES=1`** for the txn / marker / lock behaviour.

---

## Open tunables to confirm at implementation time (architecture is DECIDED — design note §11)

- Defaults: `topicization_full_chunk_batches` (e.g. 20 → ~1000 docs/chunk), `topicization_full_max_chunks_per_invocation` (e.g. 1–2), `topicization_full_run_token_budget` (0=off vs a concrete cap for the first `murashko_med` exercise).
- Checkpoint home: synthetic `processing_failures` ref (no migration, recommended) vs a dedicated `topicization_runs` table (needs migration) — ship synthetic first.
- Which new observability metrics/alerts land in the first cut vs deferred.
- Cross-chunk merge similarity: reuse cross-channel-linking cosine+Jaccard thresholds as-is vs a dedicated same-channel threshold.
