# START_PROMPT — BUG-076 residual token-leak HARDENING (IMPLEMENTATION)

**Created:** 2026-07-02. This is the **IMPLEMENTATION** start-prompt for the follow-up that closes the residual unproductive-spend surfaces an adversarial token-leak audit found in the *committed* BUG-076 fix. Build deliberately, do NOT rush.
**Branch:** `main`. **Repo:** `/Users/alexanderefimov/TG_parser`.
**HEAD this note targets:** `596fe30` = `fix(topicization): checkpoint/resumable per-chunk persistence for full topicization (BUG-076)` — the committed BUG-076 fix. Verify with `git rev-parse --short HEAD`.
**Prod HEAD / deploy state:** as of 2026-07-02, `596fe30` is a **LOCAL commit on `main` only** (`main` is ahead of `origin/main` by 1 — not pushed, NOT confirmed deployed; prod HEAD is still `b7285d7` per the watch runbook). Verify with `git status -sb` / `git log origin/main..HEAD` and, on prod, `git -C /home/user/TG_parser rev-parse --short HEAD` before assuming anything is live.
**Rollback ref:** `23764b7` (`fix(topicization): add non-blocking per-channel advisory lock … (BUG-072)`) — the last commit before the BUG-073/074/075 + BUG-076 chain.
**Status:** `open` / **design-in-prompt** (findings + fix approaches are decided below from the audit; NO code changed yet). The BUG-076 feature ships **DARK** behind the master switch **`topicization_full_resume_enabled=False`** — every fix here stays dark until that flag flips.
**Recommended tracking id:** **BUG-077** (residual token-leak hardening of BUG-076) — see the BUG_LOG note at the end; final id is the implementer/user's call.

> **This prompt is the SOURCE OF TRUTH for the next session.** It summarizes and points to the BUG-076 artifacts; it does not duplicate them. READ FIRST, in order:
> 1. [`DESIGN_BUG076_CHECKPOINT_TOPICIZATION_2026-07-01.md`](DESIGN_BUG076_CHECKPOINT_TOPICIZATION_2026-07-01.md) — the architecture these findings sit on top of.
> 2. [`START_PROMPT_SESSION_BUG076_CHECKPOINT_TOPICIZATION_IMPL_2026-07-01.md`](START_PROMPT_SESSION_BUG076_CHECKPOINT_TOPICIZATION_IMPL_2026-07-01.md) — the shipped-fix pillars + workflow this mirrors.
> 3. The `### BUG-076` row in [`BUG_LOG.md`](BUG_LOG.md) — the four Bugbot rounds already landed (what is NOT a leak anymore). **Caveat:** that row's Status field predates the `596fe30` commit and still says "UNCOMMITTED / prod HEAD `b7285d7`, local HEAD `d41a3dd`" — trust `git log` over it; updating that row is part of this session's BUG_LOG task.
> 4. [`POST_REFILL_WATCH_RUNBOOK_2026-06-30.md`](POST_REFILL_WATCH_RUNBOOK_2026-06-30.md) — the watch/rollout the F7 runbook note and the post-deploy exercise plug into.

---

## ⛔ CRITICAL OPERATIONAL WARNINGS — READ FIRST

1. **`murashko_med` stays PAUSED** (`sources.status='paused'`; the scheduler runs only `status='active'` sources). Do NOT resume it, do NOT refill billing. **No deploy before the STOP/approval gate** — deployment happens ONLY via workflow step 6, after explicit user approval of the reviewed diff. Resuming the channel is a separate, deliberate post-deploy exercise (workflow step 7), and only with a bounded `topicization_full_run_token_budget` set.
2. **The feature is DARK.** BUG-076 ships behind `topicization_full_resume_enabled=False`; the legacy monolithic path is byte-for-byte unchanged. These findings are follow-ups to a shipped-dark fix — **nothing is on fire**. Do not treat this as an incident.
3. **BUT: two findings MUST be closed BEFORE the flag is enabled for steady-state use.** These are the only *deterministic* spend surfaces:
   - **F1 — the unbounded drip.** A resume that repeatedly fails WITHOUT advancing `chunks_done` re-burns generate+merge tokens every scheduler tick with **no backoff, no counter, no cooldown** (BUG-076 deliberately disarms the BUG-071 cooldown while a live checkpoint exists). This is the only UNBOUNDED leak.
   - **F4 — guaranteed cold-start double-spend.** The BUG-075 reconcile hook does not know about a live full checkpoint, so after chunk 1 commits it feeds up to `topicization_reconcile_max_docs=200` of the not-yet-done chunks' docs into Phase-2 discover EVERY tick — double-topicizing docs the full run will cover anyway.
   F3, F7, F9, F5 are hardening (bounded / conditional / observability / blast-radius) and may land in the same PR but are not enable-blockers.
4. **Do NOT regress BUG-071..076.** The `0x70C1`/`0x70C2` locks, the re-escalation cooldown arm/clear, `reconcile_only` hard-disable, `discover_attempted` at-most-once, the atomic per-chunk commit (no duplicate LLM-derived ids), and the four already-landed Bugbot fixes (empty-chunk advance-vs-halt discrimination, append-tolerant ref-pinning, pinned chunk span, flag-gated `_has_live_full_checkpoint`) must all stay green. Every change here is additive and dark-by-default.
5. Standard workspace rules: **NO `git commit` without an explicit user request**; do NOT touch `pyproject.toml` / `requirements.txt` / `docs/methodology/**`; do NOT touch `murashko_med` / billing; do NOT touch pre-existing git stashes.

---

## TL;DR — what shipped, and what this session closes

The committed BUG-076 fix (HEAD `596fe30`) makes full topicization **crash-safe and resumable**: the corpus is chunked, each chunk is generate → merge-within-chunk → **atomically co-committed** (cards + bundles + checkpoint) in one transaction, and a scheduler resume driver carries a partial run to completion across ticks. The **≤1-chunk-loss invariant holds**, the legacy monolithic path is untouched, and the whole thing is dark behind `topicization_full_resume_enabled`.

An **adversarial token-leak audit** of that committed fix then asked the sharper question: *while the machinery is correct for the happy/crash path, where can it spend tokens that produce no durable progress?* It found six residual surfaces. This session closes them — the two deterministic ones (F1, F4) are enable-blockers; the rest are hardening. Two audit "findings" were verified to be **NON-issues** and are recorded so the next session doesn't chase them.

---

## The MANDATORY findings to fix (ranked by token-risk)

Each finding gives: the leak, why it burns tokens, the verified code anchor(s) at HEAD `596fe30`, and the fix approach. `[MUST-BEFORE-ENABLE]` vs `[HARDENING]` is marked per finding.

### F1 — circuit-breaker for a non-advancing resume `[MUST-BEFORE-ENABLE]` — the only UNBOUNDED drip

- **The leak.** The scheduler resume driver (`scheduler_service.py:702-727`) calls `run_full_topicization_resume_for_channel` **unconditionally every tick** while a live checkpoint exists. BUG-076 deliberately DISARMS the BUG-071 re-escalation cooldown while that checkpoint is live — on both the success path (`topicization_service.py:1173-1185`) and the exception path (`:1073-1081`) — precisely so a resumable run is not starved. There is **NO backoff, NO consecutive-failure counter, NO cooldown** for a chunk that keeps failing WITHOUT advancing `chunks_done`.
- **Why it burns tokens.** Each such tick regenerates the failing chunk's batches (generate spend) and, if the batches succeed, the within-chunk merge (merge spend), then halts without committing → `chunks_done` unchanged → same chunk retried next tick, forever. **Deterministic triggers, all of which advance nothing:**
  - a built card that violates a DB constraint → the atomic `_commit_chunk_atomically` fails AFTER generate+merge spend, every tick;
  - a chunk whose only batch always truncation-drops (`TopicizationBatchTruncatedError` counted as `chunk_failed` → empty-after-failure clean halt at `topicization.py:815-825`, no advance);
  - a merge reply with **string** group ids → `TypeError` at `topicization.py:1199` (`0 <= mid` on a `str`), currently **uncaught** → crashes the invocation (this is F2, below, folded in here).
- **Fix approach.**
  1. **Persist a consecutive-no-progress counter in the checkpoint.** The `processing_failures.attempts` column is already overloaded to mean `chunks_done` (caller-controlled), so do NOT reuse it — add a field to `error_details_json` (e.g. `consecutive_noprogress_resumes: int`). Increment it whenever a resume invocation returns/halts with `chunks_done` unchanged from the value read at invocation start; reset it to 0 whenever `chunks_done` advances or `final_merge_done` flips true. Extend `FullRunCheckpoint` + `to_details()`/`parse_checkpoint()` in `topicization_checkpoint.py` (default 0 for legacy rows). **Structural note (new write path required):** today the checkpoint row is written ONLY inside the atomic chunk commit (`_commit_chunk_atomically`) — which, by definition, never happens on a no-progress halt. Persisting the counter therefore needs a **separate failure-path `error_details_json` update** (a small standalone `record_failure` of the same synthetic row, outside the chunk transaction) that must not disturb `chunks_done`/`attempts` or the pinned plan fields.
  2. **Back off / cool down after N.** The resume driver (`run_full_topicization_resume_for_channel`, `topicization_service.py:1521-1601`) skips the resume when `consecutive_noprogress_resumes >= topicization_full_resume_noprogress_limit` (new setting, N) — either hard-skip with a distinct `skipped_reason="noprogress_circuit_open"` or apply a cooldown TTL keyed off `last_chunk_at` (`topicization_full_resume_noprogress_cooldown_s`, new setting). Emit the F9 alertable metric on trip. This is the *only* place the drip can be bounded, because the BUG-071 cooldown is (correctly) disarmed for live checkpoints. **Two implementation traps:** (a) the driver's returned `chunks_done` is the **PRE-invocation** value — `topicization_service.py:1599` returns `checkpoint.chunks_done` read at `:1583-1586` BEFORE `run_topicization(resume=True)` runs — so detecting advancement requires a **post-invocation re-read** of the checkpoint (or a progress field added to the `run_topicization` summary); comparing the pre-read to itself would always look like no progress. (b) A `0x70C1` lock-skip (`skipped_reason="locked"`, `:1596-1597`) is **benign contention**, not a failed resume — it must NOT increment the no-progress counter, else concurrent triggers falsely trip the breaker.
  3. **Fold in F2 (malformed-merge crash → clean halt).** Catch the `TypeError`/`AttributeError` from the merge group-id loop (`topicization.py:1196-1223`, crash site `:1199`) as a **clean resumable halt** (like the billing/timeout halt already handled), so a malformed merge feeds the no-progress counter instead of crashing `run_topicization` (which today would surface as a `bug076_full_resume_failed` log and keep retrying). Treat it as `chunk_failed` so it does NOT advance the checkpoint.
- **Anchors:** `scheduler_service.py:702-727`; `topicization_service.py:1173-1185` (success disarm), `:1073-1081` (exception disarm), `:1521-1601` (resume driver; pre-invocation `chunks_done` returned at `:1599`, lock-skip at `:1596-1597`); `topicization.py:815-825` (empty-after-failure halt), `:1196-1223` (merge group-id loop, crash at `:1199`); `topicization_checkpoint.py:95-186` (`FullRunCheckpoint` + `to_details`/`parse_checkpoint`).

### F4 — gate the BUG-075 reconcile hook on a live full-run checkpoint `[MUST-BEFORE-ENABLE]` — guaranteed cold-start double-spend

- **The leak.** `run_reconciliation_for_channel` (`topicization_service.py:1604+`) and its scheduler hook (`scheduler_service.py:745-768`) have **no knowledge of a live full checkpoint**. The reconcile hook runs on EVERY tick, ordered right AFTER the F1 resume hook. Once chunk 1 of a full run commits (channel now >0 cards, but the not-yet-done chunks' docs are still uncovered), the reconcile hook feeds up to `topicization_reconcile_max_docs=200` of exactly those uncovered docs into Phase-2 discover.
- **Why it burns tokens.** Those docs are pinned to future chunks of the in-flight full run; discover topicizes them NOW (a full LLM discover batch), and the full run re-topicizes them again when it reaches their chunk → **guaranteed double-spend on cold-start channels**, plus fragmented/duplicate cards competing with the full-run cards. Deterministic on any large-backlog 0-card channel — the exact case BUG-076 exists for.
- **Fix approach.** Add a `_has_live_full_checkpoint(failure_repo, channel_id)` gate (the helper already exists and is flag-aware from BUG-076 round-4 — reuse it) at the top of `run_reconciliation_for_channel` and/or its scheduler hook: while a live full-run checkpoint exists for the channel, **skip (or defer) reconcile** for that channel. Return a benign status (`skipped_reason="full_run_in_progress"`) so it re-arms automatically once the full run completes and clears the checkpoint. Decide (open tunable) whether to HARD-SKIP reconcile entirely vs merely DEPRIORITIZE (e.g. exclude the frozen `planned_refs` set from the reconcile candidate pool so genuinely-new appended docs still get covered). Hard-skip is simpler and safe (the full run + a later reconcile tick cover everything); deprioritize keeps steady-state coverage tighter.
- **Anchors:** `topicization_service.py:1604+` (`run_reconciliation_for_channel`), `scheduler_service.py:745-768` (reconcile hook), `topicization.py:~1810-1855` + `_discover_single_batch:1857+` (Phase-2 discover the docs are fed into); `_has_live_full_checkpoint` (`topicization_service.py`, flag-gated per BUG-076 round-4).

### F9 — observability for commit-stage failures / the drip `[HARDENING]`

- **The gap.** `record_topicization_full_run_tokens` fires only **post-commit** (`topicization.py:859-863`, inside the loop AFTER `_commit_chunk_atomically`). So the F1 drip — which spends on generate+merge but never commits — reads **zero** in `tg_parser_topicization_full_run_tokens_total`. A commit-stage failure increments **no failure counter** at all (only a `bug076_full_resume_failed` log line in `scheduler_service.py:722-727`). The drip is invisible on the BUG-076 dashboard.
- **Fix approach.** Add `tg_parser_topicization_full_run_chunk_failed_total{channel_id}` (a counter in `api/metrics.py` alongside the existing `TOPICIZATION_FULL_RUN_*` block at `:204-236`) incremented on any non-advancing chunk halt (empty-after-failure, malformed-merge halt, commit failure, budget halt-with-no-progress). Optionally also record **pre-commit** token spend (or emit tokens at generate/merge boundaries, not only post-commit) so the drip's spend is visible. Suggested alert: `full_run_resume_total` rising while `full_run_chunks{kind=done}` stays flat (a channel resuming forever without advancing) → the F1 signal; and any sustained `full_run_chunk_failed_total`. New alert rules → Prometheus force-recreate on deploy (see workflow step 6).
- **Anchors:** `topicization.py:859-863` (post-commit token emit); `api/metrics.py:204-236` (existing `TOPICIZATION_FULL_RUN_TOKENS_TOTAL` / `_CHUNKS` / `_BUDGET_HALT_TOTAL` / `_RESUME_TOTAL`), emit helpers `:918-950`; `scheduler_service.py:722-727` (the log-only failure path).

### F3 — distinguish "checkpoint READ failed" from "no checkpoint" `[HARDENING]`

- **The gap.** `_read_full_checkpoint` swallows ALL read errors → `None` (`topicization.py:462-464`), and `parse_checkpoint` degrades a malformed/corrupt row → `None` (`topicization_checkpoint.py:154-186`). A caller that gets `None` treats it as "no checkpoint → start a FRESH pinned run." So a **transient DB error** at the read moment silently re-burns chunk 0+, overwrites the real checkpoint, mints duplicate cards, and skips the stale-cleanup path. There is also a **read/clear race**: the driver reads the marker in a short-lived session (`topicization_service.py:1583-1586`) and then calls `run_topicization(resume=True)` (`:1594`) which re-reads under `0x70C1` — the checkpoint can change/clear in between.
- **Fix approach.** Make `_read_full_checkpoint` (and the driver's marker read) distinguish **read-error** from **absent**: on a genuine read exception, ABORT the invocation (return a benign "retry next tick, cost 0" status) rather than falling through to a fresh run. Re-verify checkpoint existence **AFTER** acquiring `0x70C1` inside `run_topicization` (close the read/clear race) — if the checkpoint vanished under the lock, do nothing. Keep `parse_checkpoint` returning `None` for genuinely-malformed rows (that IS "no usable checkpoint"), but ensure the *transport* error path is separable.
- **Anchors:** `topicization.py:453-464` (`_read_full_checkpoint`, `except Exception → None` at `:462-464`); `topicization_checkpoint.py:154-186` (`parse_checkpoint` degrade-to-`None`); `topicization_service.py:1583-1586` (driver marker read) + `:1594` (`run_topicization(resume=True)`).

### F7 — flag re-enable hazard / leftover checkpoint `[HARDENING]`

- **The gap.** A checkpoint row can survive a flag **off → legacy monolithic run → flag on** cycle (BUG-076 round-4 already made a leftover row *inert while the flag is OFF* for cooldown-arming, but the row itself persists). On re-enable, the resume driver can resume a **stale plan** on top of a legacy result (re-spend + duplicate cards), or — if the pinned refs no longer match — trigger the stale-restart wipe (`topicization.py:671-679`) that `delete_by_channel`'s the good legacy cards.
- **Fix approach.** At minimum, a **runbook note** (append to [`POST_REFILL_WATCH_RUNBOOK_2026-06-30.md`](POST_REFILL_WATCH_RUNBOOK_2026-06-30.md)): before flipping `topicization_full_resume_enabled` on, inspect/clear any `topicization:full_checkpoint:<channel>` row (SQL: `SELECT ... FROM processing_failures WHERE source_ref LIKE 'topicization:full_checkpoint:%'`). Optionally (code): have the **legacy monolithic completion path** delete the marker on successful completion so a legacy run can't leave a stale checkpoint for a future re-enable. Keep it dark-safe.
- **Anchors:** `topicization.py:671-679` (stale-restart `delete_by_channel` wipe); `topicization_service.py:1557-1558` (resume-driver flag gate) + the BUG-076 round-4 `_has_live_full_checkpoint` flag short-circuit; the legacy monolithic persistence loop `topicization.py:440-447`.

### F5 — narrow the stale-restart wipe `[HARDENING]` — blast-radius

- **The gap.** The stale-restart cleanup (`topicization.py:671-679`) deletes **ALL** channel cards and bundles (`delete_by_channel`), including incremental/discover cards created by the BUG-075 reconcile path that are unrelated to the prior partial full run. A false or genuine stale-restart therefore over-deletes.
- **Fix approach.** Delete only the cards belonging to the prior partial run, keyed on the checkpoint's `run_id`. **WARNING — the stamp does NOT exist yet:** today `_build_topic_card` stamps `metadata.topicization_run_id` as a **fresh per-card timestamp** `run_<now>` (`topicization.py:1329`), NOT the checkpoint's `fullrun_*` `run_id` (minted at `:594`); it even varies across resume invocations of the SAME run. A naive `metadata.topicization_run_id == checkpoint.run_id` filter would therefore match **NOTHING** — the scoped wipe would delete zero cards and the duplicate-card problem the wipe exists to prevent would return. The fix MUST first **plumb `checkpoint.run_id` into the cards persisted by the chunked path** (pass it into `_build_topic_card`, or overwrite the metadata field in `_commit_chunk_atomically` before upsert), and only then can the stale-restart wipe filter on it (repo delete-by-run-id method or service-side filter instead of `delete_by_channel`). Also decide a **fallback for pre-fix cards**: a partial run persisted before this stamp existed has no matching `run_id` — e.g. keep the broad `delete_by_channel` when the checkpoint predates the stamped format (detectable via a checkpoint schema/version field or the absence of matching-stamped cards), and use the scoped delete only for runs written with the new stamp.
- **Anchors:** `topicization.py:671-679` (the wipe); `topicization.py:1329` (per-card `run_<now>` stamp in `_build_topic_card`), `:594` (checkpoint `fullrun_*` `run_id` mint), `:635/639` (`run_id` resume plumbing), `topicization_checkpoint.py:115`; card metadata stamping target: `_commit_chunk_atomically`.

---

## Verified NON-issues (record so the next session does NOT chase them)

Both were checked against HEAD `596fe30` and are **not leaks**. The implementer MAY tidy them but should not spend a fix budget treating them as bugs:

1. **`planned_ref_hash` is stored but never compared on resume** (`topicization.py:635`; hash helper `topicization_checkpoint.py:86-92`). Resume integrity rests on **ref-membership** (`missing_refs = [r for r in pinned_refs if r not in live_by_ref]`, `topicization.py:627-628`), not on the hash. The hash is integrity/logging only. Not a leak; optionally wire it into a log assertion.
2. **The `LLMCallTimeoutError` branch in the merge halt handler is effectively dead.** `LLMCallTimeoutError` subclasses `TimeoutError` (`llm/errors.py:12`), and `TimeoutError` is a subclass of `OSError`, so it is already **swallowed inside `_merge_topics`** by `except (RuntimeError, ValueError, OSError)` at `topicization.py:1188` → returns unmerged `all_batch_topics`, the chunk still commits → **no leak** (the timeout does not propagate to the outer halt handler). Not a bug; optionally remove the unreachable branch for clarity.

---

## Verified anchors (LLM call sites + per-finding lines, HEAD `596fe30`)

Spot-checked this session; **none had drifted** from the audit's claims. Re-confirm before editing.

- **LLM spend sites in the full path:** per-batch generate `_generate_topics_batch` (via `_generate_chunk`, `topicization.py:477-510`); within-chunk merge `_merge_topics` LLM call region `topicization.py:~1140-1170` (JSON guarded at `:1172-1190`; group-id post-processing `:1196-1223`, uncaught `TypeError` at `:1199`); Phase-2 discover `_discover_single_batch` `:1857+`.
- **F1:** `scheduler_service.py:702-727`; `topicization_service.py:1073-1081`, `:1173-1185`, `:1521-1601` (pre-invocation `chunks_done` return `:1599`, lock-skip `:1596-1597`); `topicization.py:815-825`, `:1196-1223`; `topicization_checkpoint.py:95-186`.
- **F4:** `topicization_service.py:1604+`; `scheduler_service.py:745-768`; `topicization.py:1857+`; `_has_live_full_checkpoint` (flag-gated, BUG-076 round-4).
- **F9:** `topicization.py:859-863`; `api/metrics.py:204-236` + `:918-950`; `scheduler_service.py:722-727`. (Confirmed: NO `full_run_chunk_failed_total` counter exists today.)
- **F3:** `topicization.py:453-464`; `topicization_checkpoint.py:154-186`; `topicization_service.py:1583-1586`, `:1594`.
- **F7:** `topicization.py:671-679`, `:440-447`; `topicization_service.py:1557-1558`.
- **F5:** `topicization.py:671-679`; `run_id` mint `:594`, resume plumbing `:635/639`, per-card `run_<now>` stamp `:1329` (`_build_topic_card` — does NOT match the checkpoint's `fullrun_*` id); `topicization_checkpoint.py:115`.
- **Class hierarchy (confirmed):** `AnthropicBillingError(Exception)` (`llm/errors.py:4`); `LLMCallTimeoutError(TimeoutError)` (`llm/errors.py:12`) → `TimeoutError` ⊂ `OSError`.
- **Settings (confirmed present):** `topicization_full_resume_enabled` (default False), `topicization_full_chunk_batches` (20), `topicization_full_max_chunks_per_invocation` (1), `topicization_full_run_token_budget` (0=off), `topicization_full_merge_threshold` (0.6).

---

## Workflow (BINDING — same discipline as BUG-071..076)

1. **Implement behind additive settings** wherever behavior could change; keep everything dark-by-default (all gated by `topicization_full_resume_enabled` and/or the new sub-settings). No behavior change while the master flag is off. No migration (reuse the synthetic `processing_failures` checkpoint row; new fields go in `error_details_json` with legacy-safe defaults). Do NOT edit `pyproject.toml` / `requirements.txt`.
2. **Tests.** Add to `tests/test_bug076_checkpoint_topicization.py` (or a sibling `tests/test_bug077_*` if tracked as BUG-077). Use **`TEST_POSTGRES=1`** where the checkpoint / advisory-lock / atomic-txn behavior needs a real Postgres. Compose service **`tg_parser_postgres`** (pgvector:pg17) on **127.0.0.1:5432**, user **`tg_parser_user`**, pw **`test_password`**, db **`tg_parser_test`**. Follow `tests/README.md` modes (default / PR / max-local). Non-PG unit tests must still pass without a database.
3. **Self-review checklist** — write it out; put **F1 circuit-breaker correctness** (counter increments/resets on the right transitions; no false trip that strands a genuinely-progressing run) and **F4 gate correctness** (no reconcile double-spend while a checkpoint is live; genuine appends still eventually covered) FIRST — they are the enable-blockers.
4. **Bugbot review of the diff** (focus: F1 counter transitions + no-false-trip, F4 gate + coverage-not-abandoned, F3 read-error-vs-absent, F5 wipe scoped to `run_id`, no BUG-071..076 regression, all dark-by-default).
5. **STOP before commit — await EXPLICIT user approval.** No `git commit` before that.
6. On approval: gated full-suite test → commit → push → **deploy per `PRODUCTION_DEPLOYMENT.md`** (code-only; **force-recreate Prometheus** only if new F9 alert rules are added — the rules file is a bind-mount, hot reload keeps the stale inode). Rollback ref `23764b7`.
7. **Post-deploy controlled first exercise (only after F1+F4 are in):** clear/inspect any leftover checkpoint row (F7), set a conservative `topicization_full_run_token_budget`, flip `topicization_full_resume_enabled=True`, then RESUME `murashko_med`. Watch per [`POST_REFILL_WATCH_RUNBOOK_2026-06-30.md`](POST_REFILL_WATCH_RUNBOOK_2026-06-30.md): chunks advancing, `full_run_resume_total` NOT rising while `full_run_chunks{kind=done}` is flat, `full_run_chunk_failed_total` ~0, reconcile NOT double-feeding the full-run docs, no storm.

---

## Test plan (maps to each fix)

1. **F1 no-progress circuit-breaker** — a chunk that fails to advance (constraint-violating card / always-truncation-drop / malformed-merge) is retried at most N times, then the resume driver skips/cools-down (`skipped_reason="noprogress_circuit_open"`), and `full_run_chunk_failed_total` + the counter increment as expected; a genuinely-progressing run (advances each tick) NEVER trips (counter resets on advance). **Explicitly cover the two traps:** (a) advancement detection uses a POST-invocation checkpoint re-read (or a run-summary progress field) — assert the breaker does NOT trip on a run that advances, even though the driver's returned `chunks_done` is the stale pre-invocation value (`topicization_service.py:1599`); (b) a `0x70C1` lock-skip (`skipped_reason="locked"`) does NOT increment the counter. Also assert the counter persists via the new failure-path checkpoint write (no atomic chunk commit happened) without corrupting `chunks_done`/`attempts` or the pinned plan. `TEST_POSTGRES=1` for the checkpoint-field round-trip + lock path.
2. **F2 malformed-merge → clean halt (folded into F1)** — a merge reply with string group ids yields a clean resumable halt (chunk not committed, recorded as a failed chunk, no exception out of `run_topicization`), and feeds the F1 counter.
3. **F4 reconcile gate** — with a live full checkpoint and >0 cards, `run_reconciliation_for_channel` returns `skipped_reason="full_run_in_progress"` and feeds ZERO docs to discover; after the checkpoint clears, reconcile resumes normally; (if deprioritize chosen) genuinely-appended new refs are still eventually covered.
4. **F9 metrics** — `full_run_chunk_failed_total` increments on each non-advancing halt; drip spend is visible (pre-commit token emit); the resume-without-progress alert expression fires on the synthetic drip.
5. **F3 read-error vs absent** — a transient read error at `_read_full_checkpoint` / the driver marker read ABORTS the invocation (no fresh chunk-0 burn, checkpoint intact); a genuinely-absent checkpoint still starts fresh; the post-lock re-verify no-ops when the checkpoint vanished under `0x70C1`.
6. **F5 scoped wipe** — the chunked path stamps `checkpoint.run_id` into `metadata.topicization_run_id` (assert the stamp equals the checkpoint's `fullrun_*` id, NOT a fresh `run_<now>` timestamp); a stale restart deletes only the cards/bundles carrying that stamp; reconcile/incremental cards on the same channel survive; a checkpoint predating the stamped format falls back to the broad `delete_by_channel`.
7. **F7 re-enable hygiene** — (code option) the legacy monolithic completion deletes any full-checkpoint marker; (runbook) the note is present. A leftover marker with the flag OFF stays inert (BUG-076 round-4 behavior preserved).
8. **No BUG-071..076 regression** — re-run `test_bug071_*`..`test_bug076_*`; assert the flag-OFF paths are byte-for-byte unchanged (cooldown still arms on 0-card monolithic failure when no live checkpoint; atomic per-chunk commit; append-tolerant ref-pinning; pinned chunk span).

---

## Definition of Done

- **F1:** a non-advancing resume is bounded — after N consecutive no-progress resumes the driver stops re-spending (skip or cooldown), an alertable metric fires, and no genuinely-progressing run is ever falsely tripped. **The unbounded drip is closed.**
- **F2:** a malformed-merge reply is a clean resumable halt fed into the F1 counter, never an uncaught crash.
- **F4:** reconcile never double-spends on docs a live full run will cover; coverage is not abandoned (genuine appends still covered after the run completes). **The guaranteed cold-start double-spend is closed.**
- **F9:** commit-stage failures and the drip are visible (`full_run_chunk_failed_total` + pre-commit token spend); the resume-without-progress alert exists.
- **F3:** a transient checkpoint-read error costs 0 tokens (abort + retry next tick), never a fresh re-burn; the read/clear race is closed under `0x70C1`.
- **F5:** the stale-restart wipe is scoped to the prior run's `run_id` — the chunked path stamps `checkpoint.run_id` into card metadata (the per-card `run_<now>` timestamp no longer used as the key), and checkpoints predating the stamp fall back to the broad wipe.
- **F7:** re-enable is safe (runbook note landed; optional legacy-path marker cleanup).
- Everything is **dark-by-default**; **no migration**; **BUG-071..076 signals stay green**; **no `git commit`** without explicit approval.

---

## Known-unrelated pre-existing test failures (IGNORE — fail on clean HEAD too)

- `tests/test_mcp_management.py::TestGetAllChannelStats::test_batch_stats_degrades_to_zeros_on_aggregation_error`.
- The scheduler `caplog` isolation flakes (log-capture cross-test contamination — order-dependent, not a real regression).

---

## Conventions to respect (from `AGENTS.md`)

- Branch `main`. **NO `git commit` without an explicit user request.**
- Do **NOT** create/edit `docs/methodology/**` from this workspace (separate worktree; absent on `main` by design).
- No direct edits to `pyproject.toml` / `requirements.txt` without an explicit request.
- Accepted ADRs (`docs/adr/`) and JSON Schemas (`docs/contracts/`) are **binding**.
- Quality lifecycle: `docs/quality/AGENT_PLAYBOOK.md`.
- Tests per `tests/README.md`; use **`TEST_POSTGRES=1`** for the txn / marker / lock behavior.

---

## Open tunables to confirm at implementation time

- **F1 circuit-breaker:** the consecutive-no-progress limit **N** (`topicization_full_resume_noprogress_limit`, e.g. 3–5) and whether the trip is a **hard-skip** or a **cooldown TTL** (`topicization_full_resume_noprogress_cooldown_s`, e.g. reuse the 3600s re-escalation TTL). Where to store the counter (recommended: `error_details_json.consecutive_noprogress_resumes`, NOT the `attempts`/`chunks_done`-overloaded column).
- **F4:** **hard-skip** reconcile while a checkpoint is live (simpler, safe) vs **deprioritize** (exclude the frozen `planned_refs` from the reconcile candidate pool so genuine new appends are still covered promptly). Recommend hard-skip first; revisit if steady-state coverage lag is observed.
- **F9:** which new alert rules land in the first cut (resume-without-progress; `full_run_chunk_failed_total` sustained) vs deferred; pre-commit token emit granularity.
- **F5:** where to plumb the checkpoint's `fullrun_*` `run_id` into card metadata (into `_build_topic_card` vs overwrite in `_commit_chunk_atomically` — today `metadata.topicization_run_id` is a fresh per-card `run_<now>` timestamp that matches nothing); delete-by-run-id repo method vs service-side filter; and the pre-fix-cards fallback (keep `delete_by_channel` when the checkpoint predates the stamped format).

---

## BUG_LOG note (for the implementer)

Add/append a BUG_LOG entry for this work. **Recommendation:** track it as **BUG-077 — residual token-leak hardening of the committed BUG-076 fix** (a new row in `docs/notes/BUG_LOG.md § Active bugs`, `Severity: High`, `Status: open`, `Linked: BUG-076` and the BUG-071..075 chain), because it is a distinct adversarial-audit finding set against a *shipped* fix and warrants its own severity/closure trail. Acceptable alternative: append a **BUG-076 follow-up row** under the existing `### BUG-076` section (keeps the whole resumable-topicization saga in one place). State this recommendation but leave the final id choice to the implementer/user. Either way, record: the six findings (F1/F4 enable-blockers, F3/F5/F7/F9 hardening), the two verified NON-issues, the anchors above, and the dark-by-default + no-migration + no-BUG-071..076-regression constraints.
