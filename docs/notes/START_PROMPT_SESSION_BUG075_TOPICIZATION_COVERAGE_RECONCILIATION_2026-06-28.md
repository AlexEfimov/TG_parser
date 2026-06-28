# START_PROMPT — BUG-075: convergent topicization coverage reconciliation (deferred)

**Created:** 2026-06-28 (carved out of the BUG-073 F1+F3 token-burn hardening session; this note is the IMPLEMENTATION start-prompt — design + build BUG-075 deliberately, do NOT rush).
**Branch:** `main`. **Repo:** `/Users/alexanderefimov/TG_parser`. **Verified against HEAD `e0f517d`.**
**Prod:** VPS `ssh prod` (`212.72.189.15:2296`, user `user`, app dir `/home/user/TG_parser`), Docker compose.
**Status:** `open` / deferred. F1 (BUG-073), F3 (BUG-073) and F2 (BUG-074) shipped to prod WITHOUT this; BUG-075 is the durable coverage-convergence fix.

> **This is BUG-075. It builds on BUG-073 (F1+F3 per-channel locks) and BUG-071/072 (topicization token-burn + full-run dedup).** During BUG-073 a per-tick coverage-reconciliation subsystem was attempted to fix "tick-local abandonment" (processed-but-never-topicized docs). Each successive recovery attempt drew a further **HIGH Bugbot finding** (the original abandonment HIGH plus a series of iterations, each surfacing a new constraint — captured below as the 5 design learnings), and the subsystem became its own token-burn surface, so it was **DESCOPED to BUG-075** and removed from the ship. BUG-075 is to design + implement coverage-convergence PROPERLY and safely.

---

## ⛔ CRITICAL OPERATIONAL WARNING — READ FIRST

**This bug class is a TOKEN-BURN surface. The whole reason it was descoped is that a careless reconciliation re-burns Sonnet tokens.** Treat every design decision through the lens of "does this ever re-send the same docs to the LLM, or ever trigger a FULL re-topicization?" If yes, it is wrong.

- **The Anthropic balance situation:** the prior BUG-071/072 sessions closed the active token-burn vectors (truncation re-burn, concurrent full runs, JSON-retry re-burn). Restoring/refilling Anthropic credit is a **separate manual user action** and is NOT part of BUG-075. Do not assume credit is available; design and test BUG-075 so that even if it shipped to a freshly-refilled balance it could not storm.
- **Learning #5 below is the killer** and is the single most important constraint in this note. A reconciliation that calls `run_incremental_topicization` without disabling the BUG-071 zero-card re-escalation path will periodically trigger a FULL re-topicization on stuck zero-card channels — exactly the catastrophe BUG-071 fixed. Do not lose this.

---

## TL;DR for the next session

Topicization coverage is **tick-local**. The scheduler incremental hook (`run_incremental_for_all_sources` → `_process_source` in `tg_parser/services/scheduler_service.py`) derives `new_doc_refs` from a single per-tick `docs_after − docs_before` snapshot ([`scheduler_service.py:496-500`](../../tg_parser/services/scheduler_service.py)) and feeds ONLY those refs to `run_incremental_topicization`. There is **no standing recovery** for documents that are PROCESSED (in `processed_documents`) but never become COVERED (never land in a `topic_bundle`). Such docs can stay **permanently untopicized**:

- A doc persisted by a path that never topicizes it (CLI `tg-parser process`, a `skip_topicize=True` run, or a crash between processing and topicization) is never in any tick's `new_doc_refs`.
- **F1 (BUG-073, now live) slightly WIDENS this pre-existing window.** F1's per-channel processing advisory lock (`PIPELINE_LOCK_NS = 0x9C40`) makes a contended `run_processing` a benign skip (`processing_run_skipped_already_in_flight`). The lock-holder may persist docs AFTER the skipped tick's `docs_after` snapshot; if the holder is a processing-only path, those docs miss that tick's incremental. This is documented as acceptable for the F1+F3+F2 ship — see the **explicit BUG-075 caveat comments** at both skip sites ([`processing_service.py:135-146`](../../tg_parser/services/processing_service.py) in `run_processing`, and [`processing_service.py:518-525`](../../tg_parser/services/processing_service.py) in `run_multi_agent_processing`).

**Goal of BUG-075:** a **convergent** mechanism that eventually topicizes every processed-but-uncovered doc, WITHOUT reintroducing token-burn and WITHOUT ever triggering a full re-topicization.

**Workflow for this session (mirror BUG-071/072/073):** design → implement the fix + tests → self-review → Bugbot review of the diff → **STOP** before commit/deploy and await explicit user approval. On approval: gated full-suite test → commit → push → deploy per `PRODUCTION_DEPLOYMENT.md`.

---

## What already shipped (context — DO NOT redo)

**Prod HEAD = `e0f517d`** (BUG-073 F1+F3 + BUG-074 F2 live). The last four relevant commits:

- **`e0f517d`** — `fix(topicization): repair malformed JSON instead of re-issuing the batch (BUG-074)` — F2: `repair_json` before counting a JSON parse-fail; stops the 3× full-batch re-burn.
- **`bbd7c35`** — `fix(pipeline): per-channel advisory locks for processing + incremental topicization (BUG-073)` — F1 (`channel_pipeline_lock` / `PIPELINE_LOCK_NS = 0x9C40`) + F3 (`channel_incremental_topicization_lock` / `INCREMENTAL_TOPICIZATION_LOCK_NS = 0x70C2`) + the shared `channel_advisory_lock` helper.
- **`23764b7`** — `fix(topicization): add non-blocking per-channel advisory lock to stop concurrent full runs (BUG-072)` — full-topicization lock (`TOPICIZATION_LOCK_NS = 0x70C1`).
- **`7ad3264` … `bdca97f`** — BUG-071 truncation/token-burn fixes + the zero-card re-escalation cooldown gate (the thing learning #5 hinges on).

**Rollback ref for any new deploy = `23764b7`** (the last clean topicization-lock commit before the F1/F3/F2 hardening pass; per the BUG_LOG it is the BUG-072 commit). The BUG-073/074 work is committed (it is at HEAD) — BUG-075 itself is **net-new and uncommitted**; nothing for it has been implemented yet (the prototype was removed during the descope — see §"The removed prototype" below).

**Namespace map (all distinct, all non-blocking `pg_try_advisory_lock`, no deadlock):**
- `0x5C40` — `SCHEDULER_SOURCE_LOCK_NS` (scheduler per-source, ingestion engine) — `scheduler_service.py:59`.
- `0x70C1` — `TOPICIZATION_LOCK_NS` (FULL topicization) — `topicization_service.py:133`.
- `0x70C2` — `INCREMENTAL_TOPICIZATION_LOCK_NS` (incremental Phase 1/2) — `topicization_service.py:139`.
- `0x9C40` — `PIPELINE_LOCK_NS` (processing F1) — `processing_service.py:47`.

A BUG-075 reconciliation should **reuse `0x70C2`** (it IS incremental topicization) rather than mint a new namespace — see the recommended design.

---

## The 5 hard-won design learnings (THE CRUX — read before writing any code)

These were each a separate HIGH Bugbot finding against the removed prototype. **Any BUG-075 design MUST satisfy all five simultaneously**; that combination is what makes this hard and is exactly why it was descoped rather than patched a 6th time.

### Learning 1 — Recovery must be CONVERGENT / STANDING, not gated on a transient per-tick flag.
The first prototype fired recovery only when that tick's `run_processing` returned `skipped_locked=True`. But the recovery call (`run_incremental_topicization_for_uncovered`) can **DEFER** on lock contention and do no work (it passes `defer_if_locked=True` — see [`topicization_service.py:1025`](../../tg_parser/services/topicization_service.py), and the defer returns `IncrementalTopicizeResult(deferred_locked=True)` at [`topicization_service.py:497`](../../tg_parser/services/topicization_service.py)). Later healthy ticks (flag false) never retried → abandonment survived a single deferred attempt. **Recovery must run on a schedule independent of who processed the docs and of whether a prior attempt deferred** — a deferral / empty result MUST be retried on later ticks.

### Learning 2 — "Uncovered" includes off-topic / unassignable docs → an unconditional sweep re-burns.
Coverage == "is in some `topic_bundle`". The LLM discover legitimately returns off-topic / chit-chat docs as `unassignable` — see [`topicization.py:1471`](../../tg_parser/processing/topicization.py) (`unassignable = llm_result.get("unassignable", [])`) inside `_discover_single_batch` ([`topicization.py:1338`](../../tg_parser/processing/topicization.py)), plus the JSON-parse-exhausted fallback that marks the WHOLE batch unassignable at [`topicization.py:1430`](../../tg_parser/processing/topicization.py) and the `llm_result is None` fallback at [`topicization.py:1436`](../../tg_parser/processing/topicization.py). Those docs **NEVER enter a bundle**. So a recurring "uncovered" sweep re-sends the SAME perpetually-unassignable docs to Sonnet on every tick — unbounded re-burn. You need a **per-doc "discover attempted" idempotency marker** so each uncovered doc is sent to discover **AT MOST ONCE**.

### Learning 3 — The marker must be written for EVERY doc that consumed a Phase-2 discover call, regardless of outcome — excluding only now-covered docs.
Marking only `truly_unassignable` docs is insufficient. Within `_discover_single_batch`, a doc can consume a discover call yet stay uncovered via several paths, all of which must be marked:
- the LLM assigned it to a NEW card the quality filter / `_build_topic_card` rejected (card-build can drop it — see the build loop + `except` at [`topicization.py:1453-1469`](../../tg_parser/processing/topicization.py));
- the assignment was dropped as invalid (`topic_id ∉ existing_topic_ids` — the guard at [`topicization.py:1443`](../../tg_parser/processing/topicization.py));
- a successful assignment whose bundle write later failed;
- truly `unassignable` ([`topicization.py:1471`](../../tg_parser/processing/topicization.py)).

**Correct invariant:** after Phase 2, mark `unassigned_refs − covered_after` (every discover-batch doc that did not become covered). Here `unassigned_refs` is exactly the Phase-2 input — the second element returned by `assign_documents_to_topics` ([`topicization_service.py:774`](../../tg_parser/services/topicization_service.py)) — i.e. the docs that were sent to Phase-2 discover and did not end up covered. **This deliberately EXCLUDES Phase-1-keyword-assigned docs: they never consumed a discover call, so they must never be marked.** (This is why the marker set is NOT `fed − covered`: `fed` also includes the Phase-1 keyword-covered docs, so `fed − covered` would over-mark docs that never consumed a discover call — e.g. a keyword-assigned doc whose bundle write later failed — wrongly barring a cheap future retry.) A discover call that **RAISES** (hard LLM/parse error — e.g. the `raise` at [`topicization.py:1433`](../../tg_parser/processing/topicization.py)) is **NOT a completed attempt** → do NOT mark it (retry next time). Net: reconciliation excludes a ref that is EITHER covered OR attempted → **at-most-one discover per doc, ever** → steady-state cost ~0.

### Learning 4 — The proceed-without-lock path must release its dedicated DB connection before the LLM run.
**(Already shipped as part of F3 — keep it, and mirror it in any new code path.)** The incremental advisory lock runs on a dedicated connection. On the proceed-without-lock branch the connection must be released BEFORE the long Phase 1/2 run so an idle connection is not held for the run's duration. See the branch structure in `run_incremental_topicization` ([`topicization_service.py:479-511`](../../tg_parser/services/topicization_service.py)): the acquired branch returns INSIDE the `async with` (holds the lock for the run), the defer branch returns inside, and ONLY the proceed-without-lock branch falls OUT of the context (`return await _run()` at [`topicization_service.py:511`](../../tg_parser/services/topicization_service.py)) so the connection is released first. The shared helper `channel_advisory_lock` ([`advisory_lock.py:46`](../../tg_parser/services/advisory_lock.py)) closes the dedicated connection in `finally`. Regression test (already shipped): `tests/test_bug073_pipeline_concurrency.py::test_incremental_proceed_without_lock_releases_connection_before_run`.

### Learning 5 — THE KILLER: any reconciliation that calls `run_incremental_topicization` MUST DISABLE the BUG-071 zero-card re-escalation path.
`_run_incremental_topicization_locked` re-escalates to a **FULL** `run_topicization` when a channel has 0 topic cards and there are new docs: the trigger `should_reescalate = len(existing_cards) == 0 and len(new_docs) > 0` at [`topicization_service.py:584`](../../tg_parser/services/topicization_service.py), gated by the BUG-071 Fix-2 cooldown ([`topicization_service.py:608-625`](../../tg_parser/services/topicization_service.py)), with the escalation call at [`topicization_service.py:634`](../../tg_parser/services/topicization_service.py) and the crash-arm at [`topicization_service.py:642-674`](../../tg_parser/services/topicization_service.py).

A standing reconciliation that fires on EVERY tick and calls `run_incremental_topicization` would therefore **periodically trigger a full re-topicization on stuck zero-card channels** — exactly the catastrophic token-burn BUG-071 fixed (the cooldown only spaces it to once per `topicization_reescalation_cooldown_s = 3600s`, but a reconciliation that keeps feeding new "uncovered" refs to a 0-card channel re-arms the trigger forever). **Reconciliation must be cheap-Phase-1/2-ONLY — it must NEVER re-escalate.** This was the 5th finding and the reason the whole subsystem was descoped rather than patched again.

> Concretely: BUG-075 needs a way to run the incremental Phase 1 (+ Phase 2 if cards exist) that HARD-SKIPS the `should_reescalate` branch. Options: a new `reconcile_only: bool` / `allow_reescalation: bool=True` parameter threaded into `run_incremental_topicization` → `_run_incremental_topicization_locked` that forces `should_reescalate = False`; or a dedicated thin entrypoint. Whichever you choose, add an explicit test asserting a 0-card channel does NOT storm a full re-topicization through the reconciliation path.

---

## Accepted trade-off (carried into BUG-075)

**At-most-one discover attempt per doc.** Once a doc has consumed a discover call and stayed uncovered, it is marked and never re-sent — **even if topics that would now fit it appear later** (a doc unassignable at attempt time is not retried later even if new topics would now match). This is the explicit no-re-burn priority: it is strictly better than the current tick-local behaviour (which gives processed-but-missed docs ZERO attempts), and it bounds steady-state cost to ~0. If BUG-075 ever wants "re-try when the topic set changed materially", that must be an **explicit, bounded, separately-designed trigger** (e.g. invalidate the `discover_attempted` markers when a full re-topicization rebuilds the card set), NOT an unconditional sweep.

---

## Recommended design (incorporates all 5 learnings)

**Shape: a STANDING per-channel reconciliation hook, run on the scheduler cadence, feeding only NOT-YET-ATTEMPTED uncovered docs to a CHEAP-ONLY incremental path that cannot re-escalate.**

1. **Where it hangs:** a new best-effort post-processing hook inside `_process_source` ([`scheduler_service.py:208`](../../tg_parser/services/scheduler_service.py)), mirroring the contract of the existing F5-C resummarize / F11 watchlist hooks that already run there after the `if new_doc_refs:` block ([`scheduler_service.py:501`](../../tg_parser/services/scheduler_service.py) onward). It runs on EVERY tick (learning 1: standing, not flag-gated), never pollutes `stage_errors`, never crashes the tick.

2. **Candidate selection (learning 2 + 3):** uncovered = processed − covered (compute like `run_incremental_topicization_for_uncovered` does at [`topicization_service.py:984-995`](../../tg_parser/services/topicization_service.py)), then **EXCLUDE** any ref carrying a `discover_attempted` marker. So the feed is `uncovered − attempted`.

3. **Bounded slice (learning 1 convergence without watchdog trips):** cap the per-tick feed via a new setting **`topicization_reconcile_max_docs`** (no such setting exists today — add it to `settings.py`; suggested starting default **`200`**). This bounds the per-tick reconcile cost so a single tick cannot trip the per-source watchdog (`scheduler_source_timeout_s = 1800` — [`settings.py:671`](../../tg_parser/config/settings.py)); a large backlog drains over multiple ticks (`ceil(backlog / topicization_reconcile_max_docs)` ticks). A deferral / partial drain is naturally retried next tick because the hook is standing. Tune the default against observed discover-call latency × `topicization_reconcile_max_docs` ≪ `scheduler_source_timeout_s`.

4. **Cheap-only incremental call (learning 5 — THE KILLER):** feed the slice to `run_incremental_topicization` with re-escalation **explicitly disabled** (new `reconcile_only=True` / `allow_reescalation=False` flag forcing `should_reescalate=False` at [`topicization_service.py:584`](../../tg_parser/services/topicization_service.py)). **Threading the flag (do not skip a layer):** `should_reescalate` lives in `_run_incremental_topicization_locked` ([`topicization_service.py:514`](../../tg_parser/services/topicization_service.py)), but the public entrypoint is `run_incremental_topicization` ([`topicization_service.py:427`](../../tg_parser/services/topicization_service.py)) whose inner `_run()` passes a fixed kwarg set — so the new `reconcile_only` (or equivalently-named) flag MUST be added to BOTH signatures (`run_incremental_topicization` and `_run_incremental_topicization_locked`) and forwarded through `_run()`; inside the locked body it forces `should_reescalate = False` so reconciliation is cheap-Phase-1/2-only and NEVER full re-escalation. Reuse the existing `0x70C2` incremental lock; on contention this path should **DEFER** (`defer_if_locked=True`) — a defer is retried next tick (learning 1). NEVER take `0x70C1` / never call `run_topicization`.

5. **Marker write (learning 3):** after Phase 2 returns, mark `unassigned_refs − covered_after` — i.e. the docs that were sent to Phase-2 discover (the `unassigned_refs` returned by `assign_documents_to_topics` at [`topicization_service.py:774`](../../tg_parser/services/topicization_service.py)) and did not end up covered. This deliberately EXCLUDES Phase-1-keyword-assigned docs (they never consumed a discover call), so the set is `unassigned_refs − covered_after` and NOT `fed − covered`. A discover call that RAISED contributes nothing to `covered_after` AND must not be marked (so guard the marker write to only run on a completed Phase-2, not on an exception path). At-most-one discover per doc, ever.

6. **Connection lifecycle (learning 4):** the reconciliation must not hold an idle dedicated DB connection across the LLM run — it inherits this for free if it routes through the already-correct `run_incremental_topicization` proceed/defer structure; if you add a new entrypoint, replicate the release-before-run branch.

### Marker storage

The removed prototype reused the `processing_failures` table under a synthetic, clearly-namespaced ref `topicization:discover_attempted:<source_ref>` (NO migration). This is the **same pattern BUG-071 uses for its re-escalation marker** — see `_reescalation_marker_ref` returning `topicization:reescalation:<channel_id>` at [`topicization_service.py:52-54`](../../tg_parser/services/topicization_service.py), written via `record_failure` / read via `list_failures` / cleared via `delete_failure`. That namespace can never collide with a real `tg:<channel>:<type>:<id>` doc ref NOR with the per-message failure rows matched by `pipeline._should_skip_failed` / `raw_message_repo` (those match the REAL ref), so it cannot cause a doc to be skipped from PROCESSING.

**Reconsider for BUG-075** whether a dedicated column/table (`processed_documents.discover_attempted_at`, or a small `topicization_discover_attempts` table) is cleaner than overloading `processing_failures` — a Bugbot reviewer may flag the synthetic-ref overload as surprising. A dedicated boolean/timestamp column on `processed_documents` would need a migration but is the most self-documenting; weigh "no migration + proven pattern" vs "explicit schema".

### Option alternatives (note pros/cons in the design)

- **(a) Every-tick reconciliation hook in `_process_source`** ✅ recommended default — simplest convergence, naturally bounded by `topicization_reconcile_max_docs` (suggested default `200`; bounds per-tick reconcile cost under the `scheduler_source_timeout_s = 1800` watchdog, backlog drains over multiple ticks), retried automatically; cost ~0 in steady state because of the marker. Con: adds a small per-tick query (uncovered − attempted) on every channel.
- **(b) Separate periodic backfill job** (own APScheduler cadence, e.g. every N hours) — decouples reconciliation cadence from the ingest tick; good if the per-tick query cost matters. Con: another scheduled job to operate/observe; convergence latency is the job interval, not the tick.
- **(c) On-demand only (CLI `topicize uncovered`)** — already exists (`run_incremental_topicization_for_uncovered`); rejected as the BUG-075 fix because it is manual (not convergent) and, crucially, it goes through the re-escalation path (learning 5) so it is NOT safe to call unattended on zero-card channels.

---

## The removed prototype (reference — re-derive, do NOT trust)

A working implementation of this reconciliation **already existed and passed ~200 tests** (the prototype was uncommitted and has since been removed — it is NOT in git history, so the count is approximate and unverifiable) before it was removed during the descope. It can be recovered from this session's agent transcript / git reflog or simply re-derived from the design above. **It must be re-reviewed against learning #5 specifically — that is the finding it FAILED on the final Bugbot pass** (it called into `run_incremental_topicization` without disabling re-escalation, so it could storm a full re-topicization on quiet zero-card ticks). Do not lift it verbatim; treat it as a sketch and re-satisfy all 5 learnings, especially #5.

---

## Test guidance

Use `TEST_POSTGRES=1` for the advisory-lock / reconciliation behavior (the `0x70C2` lock is a no-op stub on the non-PG path; the guard degrades to "acquired" with no DB — mirror `channel_advisory_lock`'s `yield True` fallback so unit tests without a DB never block). Suggested assertions:

- **Convergence:** a processed-but-uncovered doc (e.g. persisted via a `skip_topicize` path) is eventually covered after one/few reconciliation ticks **without** manual intervention.
- **No re-burn (steady state ~0):** a channel of perpetually-unassignable docs → first reconciliation issues discover calls and marks them; a SECOND reconciliation pass issues **0 LLM calls** (assert mocked discover called once total).
- **Learning 5 — no storm:** a 0-card channel with uncovered docs fed through the reconciliation path does **NOT** trigger `run_topicization` (assert the full-run funnel is never called; assert the cooldown marker is untouched).
- **Learning 3 — marker invariant:** after a mixed Phase-2 (some assigned, some quality-rejected, some unassignable, one batch that RAISED), only `unassigned_refs − covered_after` are marked (the docs that were sent to Phase-2 discover and did not end up covered — this EXCLUDES Phase-1-keyword-assigned docs, which never consumed a discover call) AND the raised batch's docs are NOT marked (retried next pass).
- **Learning 1 — defer is retried:** a reconciliation that defers under `0x70C2` contention does no work but the next tick retries and converges.
- **Learning 4 — no idle connection** across the LLM run (extend / mirror `test_incremental_proceed_without_lock_releases_connection_before_run`).
- **Hook contract:** a reconciliation error never crashes the tick / never adds to `stage_errors` (mirror the F5-C / F11 hook tests already in `tests/test_*scheduler*`).

---

## Suggested first actions in the new session

1. **Read-only re-confirm the anchors** below (this note verified them against HEAD `e0f517d` — confirm nothing moved if anything landed after it).
2. **Decide marker storage** (synthetic `processing_failures` ref vs dedicated column/table) and whether to add a `reconcile_only` flag vs a dedicated entrypoint.
3. **Implement the recommended design** — standing hook in `_process_source` → cheap-only `run_incremental_topicization` (re-escalation disabled, `0x70C2`, `defer_if_locked=True`) → marker write for `unassigned_refs − covered_after` (docs sent to Phase-2 discover that did not end up covered; EXCLUDES Phase-1-keyword-assigned docs). Add the tests above.
4. **Self-review** against ALL 5 learnings (write the self-review as a checklist — learning 5 first). Then **Bugbot review** the diff. Then **STOP** and await explicit user approval before commit/deploy.

### Verified code anchors (all confirmed against HEAD `e0f517d`; none unconfirmed)

`tg_parser/services/topicization_service.py`:
- `_REESCALATION_ERROR_CLASS` `:49`; `_reescalation_marker_ref` `:52`; `_reescalation_in_cooldown` `:57`; `_arm_reescalation_marker` `:81`; `_clear_reescalation_marker` `:112`.
- `TOPICIZATION_LOCK_NS = 0x70C1` `:133`; `INCREMENTAL_TOPICIZATION_LOCK_NS = 0x70C2` `:139`; `channel_incremental_topicization_lock` `:142`; `channel_topicization_lock` (full) `:176`.
- `run_incremental_topicization` `:427`; lock acquire `async with channel_incremental_topicization_lock(...)` `:479`; defer branch returns `deferred_locked=True` `:485-497`; proceed-without-lock falls out of context, `return await _run()` `:503-511`.
- `_run_incremental_topicization_locked` `:514`; `should_reescalate = len(existing_cards) == 0 and len(new_docs) > 0` `:584`; BUG-071 cooldown gate `:608-625`; full re-escalation `run_topicization` call `:634`; crash-arm `:642-674`; BUG-072 `skipped_locked` fall-through `:710-717`.
- `run_incremental_topicization_for_uncovered` `:950`; uncovered computation `:984-995`; `defer_if_locked=True` call `:1025`.

`tg_parser/services/processing_service.py`:
- `PIPELINE_LOCK_NS = 0x9C40` `:47`; `channel_pipeline_lock` (delegates to `channel_advisory_lock`) `:50-62`; `_locked_skip_processing_result` `:68`.
- `run_processing` `:102`; **BUG-075 caveat comment** at the skip site `:135-146`; sentinel return `:147`.
- `run_multi_agent_processing` `:486`; **BUG-075 caveat comment** `:518-525`; sentinel return `:526`.

`tg_parser/services/advisory_lock.py`: `channel_advisory_lock(channel_id, *, namespace, engine_attr, label)` `:46`; unlock+close in `finally` `:91-105`.

`tg_parser/services/scheduler_service.py`:
- `SCHEDULER_SOURCE_LOCK_NS = 0x5C40` `:59`; `_source_processing_lock` `:63` (acquired in `_process_source` at `:276`).
- `run_incremental_for_all_sources` `:126`; `_process_source` `:208`; `docs_before` `:296`; `docs_after` `:378`; **tick-local `new_doc_refs` computation** `:496-500`; incremental call `:512`; F5-C/F11 post-processing hooks follow the `if new_doc_refs:` block from `:501`.

`tg_parser/processing/topicization.py`:
- `discover_new_topics` batch loop with `batch_size` default 50 `:1255-1336`; `_discover_single_batch` `:1338`.
- JSON-parse-exhausted fallback (mark whole batch unassignable) `:1430`; `llm_result is None` fallback `:1436`; hard-error `raise` (NOT a completed attempt) `:1433`.
- invalid-assignment guard `topic_id in existing_topic_ids` `:1443`; discovered-card build (can drop) `:1453-1469`; `unassignable = llm_result.get("unassignable", [])` `:1471`; batch return `:1481`.
- full-topicization `BATCH_SIZE = 50` `:283`.

`tg_parser/services/pipeline_service.py`: `run_full_pipeline` `:62`; `skip_topicize` param `:68`; **short-circuit on processing `skipped_locked`** `:181-199`.

`tg_parser/config/settings.py`: `topicization_reescalation_cooldown_s` (default `3600`, `ge=0`) `:388`; `scheduler_source_timeout_s` (default `1800`) `:671`; `scheduler_max_concurrent_sources` `:641`.

---

## Current prod / repo state to record

- **Prod HEAD = `e0f517d`** (BUG-073 F1+F3 + BUG-074 F2 live). **Rollback ref = `23764b7`** (BUG-072 full-topicization lock — last clean pre-hardening commit).
- BUG-073 / BUG-074 are logged in [`docs/notes/BUG_LOG.md`](BUG_LOG.md); the **DESCOPED to BUG-075** row under BUG-073 records this decision (search `DESCOPED to BUG-075`). BUG-072 is the full-topicization lock; BUG-071 is the token-burn / re-escalation work.
- **The F1 abandonment caveat is the motivating gap** — the inline BUG-075 comments at `processing_service.py:135-146` and `:518-525` point back to this note.
- **Relevant settings defaults:** `topicization_reescalation_cooldown_s = 3600` (`settings.py:388`); `scheduler_source_timeout_s = 1800` (`:671`); `scheduler_max_concurrent_sources` (`:641`).
- **Anthropic balance:** the BUG-071/072/073/074 work closed the active token-burn vectors; restoring/refilling Anthropic credit is a **separate manual user action**, NOT part of BUG-075. Design + test so a refilled balance could not be stormed.
- **Known-unrelated pre-existing test failures (ignore — fail on clean HEAD too):**
  - `tests/test_mcp_management.py::TestGetAllChannelStats::test_batch_stats_degrades_to_zeros_on_aggregation_error`.
  - the scheduler `caplog` isolation flakes (log-capture cross-test contamination in the scheduler suite — order-dependent, not a real regression).

---

## Conventions to respect (from `AGENTS.md`)

- Branch `main`. **NO `git commit` without an explicit user request.**
- Accepted ADRs in [`docs/adr/`](../adr/) and JSON Schemas in [`docs/contracts/`](../contracts/) are **binding**.
- Do **NOT** create or edit `docs/methodology/**` from this workspace (it lives in a separate worktree; absent on `main` by design).
- No direct edits to `pyproject.toml` / `requirements.txt` without an explicit request.
- Tests per [`tests/README.md`](../../tests/README.md): default / PR / max-local modes; use **`TEST_POSTGRES=1`** for the advisory-lock / reconciliation behavior (this fix needs a real Postgres).
- Quality lifecycle: [`docs/quality/AGENT_PLAYBOOK.md`](../quality/AGENT_PLAYBOOK.md). Log the fix under **BUG-075** in [`docs/notes/BUG_LOG.md`](BUG_LOG.md) (the DESCOPED row under BUG-073 is the existing placeholder).
- **Workflow (same as prior sessions):** implement + tests → self-review → Bugbot → **STOP** before commit, await approval.

---

## Deploy procedure reference (only after explicit approval)

`PRODUCTION_DEPLOYMENT.md` § Updating (canonical): backup → `git pull --ff-only` → `docker compose build tg_parser` → `db upgrade --db all` (a NO-OP unless you chose a dedicated marker table/column — the advisory-lock + synthetic-ref design needs **no migration**; if you add a column/table, verify the migration applies cleanly) → `docker compose up -d` → `docker compose --profile bot up -d --force-recreate --no-deps tg_bot` → smoke (`/health`, `/metrics`, `docker compose ps`). Force-recreate prometheus ONLY if `docker/prometheus*` changed. All via `ssh prod` (`212.72.189.15:2296`, app dir `/home/user/TG_parser`). **Rollback = `git checkout 23764b7 && docker compose build tg_parser && docker compose up -d`.**

---

## Definition of done (for BUG-075)

- A processed-but-uncovered doc is eventually topicized (convergence) without manual intervention.
- Steady-state LLM cost on a channel of perpetually-unassignable docs is ~0 (assert "second pass issues 0 LLM calls").
- Reconciliation NEVER triggers a full re-topicization (assert a zero-card channel does not storm) — **learning 5**.
- No idle dedicated DB connection held during any LLM run — **learning 4**.
- A deferred reconciliation is retried on a later tick (convergence survives a single defer) — **learning 1**.
- The `discover_attempted` marker is written for `unassigned_refs − covered_after` (docs sent to Phase-2 discover that did not end up covered; this EXCLUDES Phase-1-keyword-assigned docs, which never consumed a discover call) and NOT for raised-attempt docs — **learning 3**.
- All four contention namespaces stay distinct (`0x5C40` / `0x70C1` / `0x70C2` / `0x9C40`) and all locks remain non-blocking try-locks (no deadlock).
