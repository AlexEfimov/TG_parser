# START PROMPT — BUG-075: topicization coverage reconciliation (deferred)

**Created:** 2026-06-28
**Status:** `open` / deferred — design deliberately, do NOT rush-implement.
**Parent:** carved out of the BUG-073 (F1+F3) token-burn hardening session. F1+F3+F2
shipped alone; the coverage-convergence work below was DESCoped after 5 consecutive
HIGH Bugbot findings on the per-tick reconciliation prototype.

---

## 1. The problem (why BUG-075 exists)

Topicization coverage is **tick-local**. The scheduler's incremental hook
(`run_incremental_for_all_sources` in `tg_parser/services/scheduler_service.py`)
derives `new_doc_refs` from a single per-tick `docs_after − docs_before` snapshot and
feeds ONLY those refs to `run_incremental_topicization`. There is **no standing
recovery** for documents that are PROCESSED (persisted to `processed_documents`) but
never become COVERED (never land in a `topic_bundle`). Such docs can stay
**permanently untopicized**:

- A doc persisted by some path that never topicizes it (CLI `tg-parser process`, a
  `skip_topicize=True` run, or a crash between processing and topicization) is never
  in any tick's `new_doc_refs`.
- **F1 (this ship) slightly WIDENS this pre-existing window.** F1's per-channel
  processing advisory lock (`PIPELINE_LOCK_NS = 0x9C40`) makes a contended
  `run_processing` a benign skip (`processing_run_skipped_already_in_flight`). The
  lock-holder may persist docs AFTER the skipped tick's `docs_after` snapshot; if the
  holder is a processing-only path, those docs miss that tick's incremental. This is
  acceptable for the F1+F3+F2 ship (see the inline caveat at the F1 skip site in
  `processing_service.py` → `run_processing`), because it is essentially the
  pre-existing scheduler property and the common holders (dispatch `full_pipeline` /
  scheduler tick) topicize their own docs. BUG-075 is the durable fix.

**Goal of BUG-075:** a convergent mechanism that eventually topicizes every
processed-but-uncovered doc, WITHOUT reintroducing token-burn.

---

## 2. The 5 hard-won design learnings (from the Bugbot rounds — read before coding)

These were each a separate HIGH Bugbot finding against the prototype. Any future
design MUST satisfy all five simultaneously; that combination is what makes this hard.

1. **Recovery must be CONVERGENT/STANDING, not gated on a transient per-tick flag.**
   The first attempt fired recovery only when that tick's `run_processing` returned
   `skipped_locked=True`. But the recovery call (`run_incremental_topicization_for_uncovered`)
   can DEFER on lock contention and do no work; later healthy ticks (flag false) never
   retried → abandonment survived. Recovery must run on a schedule independent of who
   processed the docs and of whether a prior attempt deferred.

2. **"Uncovered" includes off-topic/unassignable docs → an unconditional sweep
   re-burns.** Coverage == "is in some `topic_bundle`". The LLM discover legitimately
   returns off-topic/chit-chat docs as `unassignable` (see
   `tg_parser/processing/topicization.py` `_discover_single_batch`, plus the
   JSON-parse-exhausted fallback), and those NEVER enter a bundle. So a recurring
   uncovered sweep re-sends the SAME perpetually-unassignable docs to Sonnet on every
   tick — unbounded re-burn. You need a **per-doc "discover attempted" idempotency
   marker** so each uncovered doc is sent to discover AT MOST ONCE.

3. **The marker must be written for EVERY doc that consumed a Phase-2 discover call,
   regardless of outcome — excluding only now-covered docs.** Marking only
   `truly_unassignable` docs is insufficient: a doc the LLM assigned to a new card the
   quality filter rejected, an assignment dropped as invalid (`topic_id` ∉ existing
   ids), or a successful assignment whose bundle write failed all CONSUME a discover
   call yet stay uncovered. Correct invariant: after Phase 2, mark
   `unassigned_refs − covered_after` (every discover-batch doc that did not become
   covered). A discover call that RAISES (hard LLM/parse error) is NOT a completed
   attempt → do not mark it (retry next time). Net: reconciliation excludes a ref that
   is EITHER covered OR attempted → at-most-one discover per doc, ever.

4. **The proceed-without-lock path must release its dedicated DB connection before the
   LLM run.** (This learning is ALREADY shipped as part of F3 — keep it.) The
   incremental advisory lock runs on a dedicated connection; on the
   proceed-without-lock branch the connection must be released BEFORE the long Phase
   1/2 run so an idle connection is not held for the run's duration. See
   `run_incremental_topicization` in `topicization_service.py` and
   `tests/test_bug073_pipeline_concurrency.py::test_incremental_proceed_without_lock_releases_connection_before_run`.

5. **THE KILLER: any reconciliation that calls `run_incremental_topicization` MUST
   DISABLE the BUG-071 zero-card re-escalation path.** `run_incremental_topicization`
   re-escalates to a FULL re-topicization when a channel has 0 topic cards (BUG-071
   Fix-2, cooldown-gated). A standing reconciliation that fires on EVERY tick would
   therefore periodically trigger a full re-topicization on stuck zero-card channels —
   exactly the catastrophic token-burn BUG-071 fixed. **Reconciliation must be
   cheap-Phase-1/2-ONLY** (never re-escalate). This was the 5th finding and the reason
   the whole subsystem was descoped rather than patched again.

---

## 3. Accepted trade-off (carried into BUG-075)

**At-most-one discover attempt per doc.** Once a doc has consumed a discover call and
stayed uncovered, it is marked and never re-sent — even if topics that would now fit it
appear later. This is the explicit no-re-burn priority: it is strictly better than the
current tick-local behaviour (which gives processed-but-missed docs ZERO attempts), and
it bounds steady-state cost to ~0. If BUG-075 ever wants "re-try when the topic set
changed materially", that must be an explicit, bounded, separately-designed trigger
(e.g. invalidate markers on a full re-topicization), NOT an unconditional sweep.

---

## 4. Suggested shape (NOT prescriptive — design deliberately)

A plausible convergent design that satisfies all 5 learnings:

- A **standing** reconciliation (own scheduler cadence, or every-N-ticks), per channel.
- Reads uncovered docs = processed − covered; EXCLUDES docs with a
  `discover_attempted` marker (learning 2/3).
- Feeds the remainder to a **cheap-only** incremental path that CANNOT re-escalate
  (learning 5) — e.g. a dedicated entrypoint / flag that runs Phase 1 (+ Phase 2 if
  cards exist) but hard-skips the zero-card BUG-071 branch.
- Writes the marker for `unassigned_refs − covered_after` after Phase 2 (learning 3).
- Bounds the per-invocation slice (`max_docs`) so a large backlog drains over ticks
  without tripping the per-source watchdog (`scheduler_source_timeout_s`).
- DEFERS (no work) under the 0x70C2 incremental lock; a defer is retried by the next
  standing run (learning 1).
- Best-effort, never pollutes `stage_errors`, never crashes the tick (mirror the
  F5-C / F11 post-processing hook contract).

**Marker storage:** the prototype reused the `processing_failures` table under a
synthetic, clearly-namespaced ref `topicization:discover_attempted:<source_ref>` (NO
migration). That namespace can never collide with a real `tg:<channel>:<type>:<id>` doc
ref NOR with the per-message failure rows matched by `pipeline._should_skip_failed` /
`raw_message_repo` (those match the REAL ref), so it cannot cause a doc to be skipped
from PROCESSING. Reconsider whether a dedicated table/column is cleaner for BUG-075.

---

## 5. File anchors (baseline `main` after F1+F3+F2 ship)

- `tg_parser/services/scheduler_service.py` — `run_incremental_for_all_sources`: the
  tick-local incremental hook (`new_doc_refs`) + the F5-C resummarize / F11 watchlist
  post-processing hooks (the contract a reconciliation hook should mirror). The
  reconciliation hook was REMOVED here; this is now baseline.
- `tg_parser/services/topicization_service.py`:
  - `run_incremental_topicization` (F3 wrapper) + `_run_incremental_topicization_locked`
    (the locked body; Phase 1/2; the BUG-071 zero-card re-escalation branch that
    learning 5 says reconciliation must avoid).
  - `run_incremental_topicization_for_uncovered` (CLI `topicize uncovered`; computes
    uncovered = processed − covered — the natural place a reconcile mode hung off).
  - `channel_incremental_topicization_lock` / `INCREMENTAL_TOPICIZATION_LOCK_NS = 0x70C2`.
- `tg_parser/services/processing_service.py` — `run_processing` lock-contention branch:
  the F1 benign skip + the inline `BUG-075` caveat comment marking the widened window.
- `tg_parser/processing/topicization.py` — `_discover_single_batch`: where docs become
  `unassignable` (learning 2) and the assigned/quality-rejected/invalid/persist-failed
  outcomes (learning 3) originate.
- `tg_parser/services/advisory_lock.py` — `channel_advisory_lock` (reuse for any new
  per-channel lock).
- BUG-071 (`START_PROMPT_SESSION_BUG071_TOPICIZATION_TOKEN_BURN_2026-06-27.md`) — the
  zero-card re-escalation + cooldown marker that learning 5 hinges on.
- `docs/notes/BUG_LOG.md` — BUG-073 (the DESCOPED row records this decision), BUG-074
  (F2), BUG-072 (the full-topicization lock).

---

## 6. Definition of done (for BUG-075 when picked up)

- A processed-but-uncovered doc is eventually topicized (convergence) without manual
  intervention.
- Steady-state LLM cost on a channel of perpetually-unassignable docs is ~0 (no
  re-burn) — assert with a "second pass issues 0 LLM calls" test.
- Reconciliation NEVER triggers a full re-topicization (assert zero-card channel does
  not storm).
- No idle dedicated DB connection held during any LLM run.
- All four contention namespaces stay distinct (`0x5C40` / `0x70C1` / `0x70C2` /
  `0x9C40`) and all locks remain non-blocking try-locks (no deadlock).
