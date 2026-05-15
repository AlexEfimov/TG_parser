# Fix Sprint — Scheduler Joint Fix (BUG-013 + BUG-014 + BUG-024) — 2026-05-15

> **Scope banner**
> - **Primary bug:** BUG-013 — scheduler shares one `AsyncSession` pair across `asyncio.gather` tasks → `IllegalStateChangeError` + cascading `InterfaceError` on every `incremental_pipeline` tick (~77 % failure rate over the F4-B Core 24h watch window).
> - **Joint scope (single sprint, single PR):** BUG-013 + BUG-014 (offset-naive `rate_limit_until` vs `datetime.now(UTC)` → `TypeError`, ~25 % of ticks) + BUG-024 (`last_attempt_at` invariant not enforced synchronously — close-time failure rolls back the per-task write). All three share a single code surface (`scheduler_service._process_source`) and their fixes compose: BUG-013 (per-task sessions) is a prerequisite for BUG-024 (synchronous commit before pipeline `await`).
> - **Severity:** all three Medium. 0 user-visible data corruption today, but the trio collectively wrecks scheduler observability (success-counter absent, attempt-tracking nulled, ~25 % of sources stuck behind a `TypeError`).
> - **F4-B non-regression note:** **NOT a F4-B regression.** F4-B Core merge [`7953302`](https://github.com/AlexEfimov/TG_parser/commit/7953302) made zero changes to `scheduler_service.py` and only additive changes to `db_context.py`. Verified via `git diff 7953302^ 7953302`. F4-B Core deploy reset the log buffer which made the pre-existing bugs visible enough to file.
> - **Sibling bugs / GH issues:** [#76 BUG-013](https://github.com/AlexEfimov/TG_parser/issues/76), [#77 BUG-014](https://github.com/AlexEfimov/TG_parser/issues/77), [#78 BUG-024](https://github.com/AlexEfimov/TG_parser/issues/78).
> - **Approval gate:** **planning-only artifact. User OK required before Step E implementation starts.** See § 8.

---

## 1. Context & evidence

### 1.1 Required reads (in order, before implementation)

1. `docs/notes/BUG_LOG.md` § **BUG-013** — full entry incl. reproduction trace (lines ~2583-2628), root-cause walk, F4-B non-regression proof.
2. `docs/notes/BUG_LOG.md` § **BUG-014** — full entry incl. reproduction trace (lines ~2632-2660).
3. `docs/notes/BUG_LOG.md` § **BUG-024** — full entry incl. reproduction trace + Phase 3 investigation pointer (lines ~2835-2850).
4. `docs/notes/HANDOFF_POST_WAVE1_STEP2_2026-05-15.md` § Pending #2 (joint scheduler fix-sprint anchor with workflow + 24h watch criteria).
5. `docs/notes/HANDOFF_POST_MCP_INTAKE_2026-05-15.md` § Pending #1 — updated joint scope with optional bonus inclusions (ENH-3 stuck-source gauge, O-8 log-level bump) — **defer those to a follow-up sprint** unless trivial (see § 7).
6. `docs/notes/mcp_testing/2026-05-15_claude_session/01-bug-report.md § ISSUE-4` and `03-investigation-log.md § Phase 3` — invariant details + reproduction context for BUG-024.
7. `docs/quality/AGENT_PLAYBOOK.md` — lifecycle conventions (no surprises here, this is a joint structural fix sprint).
8. `tg_parser/services/scheduler_service.py` — target file (lines 26-318, especially `run_incremental_for_all_sources` and the inner `_process_source` closure; `_pause_source_for_billing` at lines 766-776 — the write-site of `rate_limit_until`).
9. `tg_parser/services/db_context.py` lines 176-192 — `ingestion_and_processing_repos` (unchanged, but referenced as where the close-time exception surfaces).
10. `tg_parser/storage/ports.py` lines 195-352 — `Source` dataclass + `IngestionStateRepo` port (where to add the new `mark_attempt_started` method for BUG-024 fix).
11. `tg_parser/storage/sqlalchemy/ingestion_state_repo.py` lines 255-321 — `record_attempt` impl (the synchronous-commit pattern to mirror for `mark_attempt_started`); lines 422-426 — the `Source.rate_limit_until` field-load path (`parse_iso_datetime`).
12. `tg_parser/domain/json_utils.py` lines 80-94 — `parse_iso_datetime` (root cause of BUG-014 — returns tz-naive datetime by construction; out-of-scope to fix here, see § 7).
13. `tests/test_scheduler_service.py` lines 1-100 — existing fixture patterns (`_mock_ingestion_and_processing_repos`, `_mock_ingestion_state_repo`). New tests follow these patterns.

### 1.2 Evidence summary (do not duplicate full traces; BUG_LOG has them)

| Bug | Frequency in F4-B watch (24 ticks) | Surface | Trace anchor |
|---|---|---|---|
| BUG-013 | 100 % `status="error"` ticks; 18 `IllegalStateChangeError` + 3 `InterfaceError` per 24h | `scheduler_service.py:61-65` opens shared session; `:306` fans out via gather | BUG_LOG § BUG-013 «Reproduction trace» |
| BUG-014 | ~25 % ticks (6/24); affected sources fail at line 89 before any pipeline await | `scheduler_service.py:89` (naive vs aware comparison) | BUG_LOG § BUG-014 «Reproduction trace» |
| BUG-024 | Silent — only visible via `get_pipeline_status` cross-check (`last_success_at` non-null AND `last_attempt_at` null is impossible) | `_safe_record_attempt` in per-task `finally` (lines ~283-297) | BUG_LOG § BUG-024 «Symptoms» |

Reproduction traces, F4-B non-regression proofs, and Why-CI-didn't-catch sections live verbatim in `BUG_LOG.md` — do **not** duplicate them here. This document is the synthesis layer.

---

## 2. Root cause synthesis (joint)

The three bugs share **one code surface** — `_process_source` inside `run_incremental_for_all_sources` — and three **independent** failure modes that happen to co-fire on most ticks:

| # | Failure mode | What it breaks | Compositional relationship |
|---|---|---|---|
| BUG-013 | Shared `AsyncSession` across `asyncio.gather` tasks → SA 2.x concurrency invariant violation | Wrapper close-time + cascading rollback; metric & log signal degraded | **Prerequisite** for BUG-024 fix — without per-task sessions, synchronous commits race on the shared session |
| BUG-014 | `source.rate_limit_until` parsed naive (`parse_iso_datetime` strips `Z`, returns naive UTC datetime) compared against aware `datetime.now(UTC)` → `TypeError` | Affected source skipped that tick before any pipeline work | **Independent** of BUG-013 — different failure path (line 89 fails BEFORE the `try` block that BUG-013 unwinds); same code surface only by file co-location |
| BUG-024 | `last_attempt_at` written in per-task `finally` on the shared session — rollback (BUG-013 cascade) loses the write, or task-cancellation skips the `finally` entirely | Stuck-source detection blind: `last_success_at IS NOT NULL AND last_attempt_at IS NULL` is structurally impossible but happens | **Depends on** BUG-013 fix — per-task sessions make a pre-await synchronous commit naturally safe |

**Why a joint sprint:**
- Three changes, one PR — each fix is small (~5-30 LOC), all touch the same function, the test setup is shared, and the ordering between BUG-013 and BUG-024 is causal (per-task sessions enable the synchronous commit). Splitting would require a precarious intermediate state where BUG-013 is fixed but BUG-024 still writes in `finally`.
- Composing fixes also lets the 24h post-deploy watch validate all three simultaneously (one watch window, three Prometheus / log signals — see § 5 + § 6).

---

## 3. Proposed fix design

### 3.1 BUG-013 — per-task session pattern

**Target:** `tg_parser/services/scheduler_service.py:run_incremental_for_all_sources` (lines 26-318).

**Change shape:**

1. **Keep** an outer one-shot session for the initial `state_repo.list_sources(status="active")` read. Use `ingestion_state_repo()` (single-repo helper at `db_context.py:106`) — this read is sequential, never raced, and finishes before any task is spawned. Close it before the gather. The returned `Source` objects are plain dataclass instances (see `SAIngestionStateRepo.list_sources` → builds `Source(...)` at `ingestion_state_repo.py:422-426`), not session-bound proxies — safe to read attributes after session-close inside per-task closures.
2. **Move** `ingestion_and_processing_repos()` **inside** each `_process_source` task as its first `async with` block. Each task owns a private `(state_repo, processed_repo, db)` triple for the lifetime of its own pipeline work. SQLAlchemy 2.x concurrency invariant is restored: no two tasks share a session.
3. **Drop** `repo_lock` (line 81) — no longer needed since each task has private sessions. Aggregate dict mutations (`aggregate["sources_skipped"] += 1`, `aggregate["total_new_messages"] += n`, `aggregate["retopicized_sources"].append(...)`, `aggregate["errors"][source_id] = ...`) move to either (a) per-task local accumulators that the parent merges after `asyncio.gather`, or (b) keep in-task mutation. **Recommendation: option (b)** — asyncio coroutines are cooperatively scheduled (no preemption except at `await` points); each mutation listed above is a single non-await Python statement, so there is no read-modify-write race window. Each `_process_source` invocation also mutates `aggregate` only for its own source_id (no shared key), so even an interleaving wouldn't conflict semantically. Option (b) keeps the diff minimal; option (a) is strictly stricter but adds parent-side merge plumbing for no observable benefit.
4. **Defensive concurrency guard:** wrap the gather as `await asyncio.gather(*tasks, return_exceptions=True)`. **This is a deliberate semantic change** from the current behaviour: today, the bare `await asyncio.gather(*coros)` cancels sibling coroutines as soon as one raises (asyncio default — see Python docs «If return_exceptions is False (default), the first raised exception is immediately propagated to the task that awaits on gather()»); post-fix, sibling tasks survive and complete. This is desirable here because each `_process_source` already wraps its body in `try/except/finally`, so unhandled escapes are rare (post-BUG-013 + BUG-014 fixes they should be near-zero) — but when they happen we want isolation, not cascade. Iterate the gather's returned list at the end and log per-source unhandled exceptions (these are NOT `stage_errors` — they're escapes from the existing try/except/finally). One `logger.error` line per escape; no Prometheus counter for this sprint.

**Optional kwargs `state_repo` / `processed_repo` on `run_incremental_for_all_sources` (test-injection legacy path):** zero production callers use them (`run_incremental_for_all_sources(output_dir=...)` is the only form in `cli/scheduler_cmd.py`, `_run_scheduler_async`, `incremental_pipeline_task`); existing tests inject by patching the module-level `ingestion_and_processing_repos` name, NOT through the kwargs. **Recommendation:** keep the kwarg signature (no API break) but document that, post-fix, injected repos are used **only** for the outer `list_sources` call and per-task sessions still open inside the closure via the (possibly-patched) `ingestion_and_processing_repos`. This preserves backward compatibility while making the new contract explicit. Alt: drop the kwargs (small cleanup, ~4 LOC). **Default: keep them** — minimal-diff.

**Skip-path (rate_limited) note:** the rate-limited early-return at lines 90-98 currently mutates `aggregate["sources_skipped"]` under `repo_lock`. Post-fix: same mutation, no lock needed (single non-await statement under cooperative scheduling). The early-return path does **not** open the per-task session at all (no need — the rate-limit comparison is on the in-memory `source` object passed in). This keeps the rate-limited skip cheap. BUG-024 invariant note: the rate-limited skip deliberately does NOT call `mark_attempt_started` — skipped is not «attempted», so the existing semantics («`last_attempt_at` reflects attempts to process, not skips») is preserved.

**Interaction with `_record_and_pause_on_billing` / `_pause_source_for_billing` (lines 779-818):** these helpers live inside the per-task `finally` and write to `source.rate_limit_until` + call `state_repo.upsert_source(source)`. Post-fix, `state_repo` is the per-task instance — the upsert commits cleanly on the task's own session before its close. The freshly-written naive-after-round-trip `rate_limit_until` value is read back by the next tick's `_coerce_aware_utc` helper (BUG-014 fix) — closes the loop without further change to the billing-pause path.

**Estimated delta:** ~30 LOC net (move ~4 lines inside the closure, delete `repo_lock` declaration + 4 `async with repo_lock:` blocks, add `return_exceptions=True` + final exception-iteration loop). Sign of the delta is roughly LOC-neutral if the optional kwargs are kept (recommended).

### 3.2 BUG-014 — tz-aware `rate_limit_until` comparison (defensive fix at call site)

**Target:** `tg_parser/services/scheduler_service.py:89`.

**Change shape:** add a tiny helper that coerces a possibly-naive datetime to tz-aware UTC, then use it at the comparison site:

```python
def _coerce_aware_utc(dt: datetime | None) -> datetime | None:
    """BUG-014 defensive coerce: parse_iso_datetime returns tz-naive UTC;
    compare against datetime.now(UTC) would raise TypeError. If tzinfo
    is missing, attach UTC. See follow-up TD-parse-iso-datetime-aware
    for the structural fix at the parse boundary.
    """
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

# at line 89:
rate_limit_until = _coerce_aware_utc(source.rate_limit_until)
rate_limited = rate_limit_until is not None and rate_limit_until > datetime.now(UTC)
```

**Why defensive coerce, not parse-time fix:** `parse_iso_datetime` is called from many call-sites across the codebase (search shows usage in raw_message_repo, processed_doc_repo, attempt-reading paths). A parse-time fix (attach `UTC` when input ends with `Z`) is correct but requires an audit of every consumer that currently relies on naive UTC. That audit is **out of scope** for this fix-sprint (see § 7) — the scheduler is the only place currently observed to mix the parsed value with a tz-aware comparison.

**Estimated delta:** ~6 LOC (helper + 2-line call site).

### 3.3 BUG-024 — synchronous `last_attempt_at` write before first pipeline `await`

**Target:** new method on `IngestionStateRepo` + call site in `_process_source` before pipeline work.

**Change shape:**

1. Add abstract method to `tg_parser/storage/ports.py:IngestionStateRepo`:

   ```python
   @abstractmethod
   async def mark_attempt_started(self, source_id: str) -> None:
       """Synchronously commit ``last_attempt_at = now()`` for a source.

       BUG-024: called from the scheduler BEFORE the first pipeline
       ``await`` so the invariant «if the scheduler attempted a source,
       last_attempt_at is non-null» holds even on per-task crash /
       cancellation / outer-session-close failure. Idempotent — safe
       to call multiple times per tick (the value is monotonically
       advancing). Issues its own commit; caller does not need to.
       """
       pass
   ```

2. Implement on `tg_parser/storage/sqlalchemy/ingestion_state_repo.py:SAIngestionStateRepo` — mirror `record_attempt` (lines 255-321) but with the UPDATE-only SQL and a self-contained `commit()`:

   ```python
   async def mark_attempt_started(self, source_id: str) -> None:
       now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
       await self.session.execute(
           text(
               "UPDATE sources "
               "SET last_attempt_at = :now, updated_at = :now "
               "WHERE source_id = :source_id"
           ),
           {"source_id": source_id, "now": now},
       )
       await self.session.commit()
   ```

3. Call from `_process_source` immediately **after** the rate-limited early-return and **before** the first pipeline `await`:

   ```python
   # ... rate_limited check returns early ...
   logger.info("Processing source %s (channel=%s)", source_id, channel_id)
   await state_repo.mark_attempt_started(source_id)  # BUG-024: synchronous commit
   # ... existing semaphore + run_full_pipeline ...
   ```

   After BUG-013 fix, `state_repo` here is the per-task instance — the commit cannot race siblings.

4. **Compatibility with existing `record_attempt`:** the existing `record_attempt` in the per-task `finally` writes `last_attempt_at` redundantly (since `mark_attempt_started` already set it). The redundant write is harmless (same source_id, later timestamp on success-path; same-or-equal timestamp on failure-path). Leave `record_attempt` unchanged — it remains the source of truth for `source_attempts` table + `fail_count` / `last_success_at` / `last_error` columns. The two writes are NOT competing semantic-wise.

5. **Other implementations of `IngestionStateRepo`:** verified at planning time — only `SAIngestionStateRepo` subclasses the port (Grep `class .*IngestionStateRepo` returns just `ports.py:239` definition + `sqlalchemy/ingestion_state_repo.py:19` impl). No in-memory test-fake exists; mock-based tests use `AsyncMock()` which auto-specs new attributes. Re-verify at implementation time in case a fake landed between planning and Step E.

**Estimated delta:** ~15 LOC port + impl + call site.

### 3.4 Composition order (for reviewer mental model)

When reading the diff, mental order should be:

1. Add `mark_attempt_started` method to port + SA impl (BUG-024 prep, no behavioural effect yet — pure prep that the per-task session refactor can then activate).
2. Refactor `_process_source` to per-task sessions + `return_exceptions=True` (BUG-013) — the structural change.
3. Insert `_coerce_aware_utc` helper + line 89 call (BUG-014) — small defensive fix, easy to read after the structural refactor settles.
4. Insert `await state_repo.mark_attempt_started(source_id)` call site (BUG-024 activation — now safe because step 2 made state_repo per-task).

The PR commit (see § 6) lays them out in this order.

**Alternative ordering** (small-to-large, fix-difficulty ascending): BUG-014 defensive coerce first (1-line risk-free fix) → BUG-013 structural per-task refactor → BUG-024 method definition + call site. Both orderings produce the same final code; pick whichever feels cleaner during implementation. The ordering only affects how the diff hunks appear to the reviewer; commit is a single atomic squash (see § 6.2).

---

## 4. Test plan

### 4.1 Test discovery (existing surface)

- `tests/test_scheduler_service.py` (only file matched by `tests/**/test_scheduler*.py`; nothing under `tests/services/`). Existing patterns: `_mock_ingestion_and_processing_repos` + `_mock_ingestion_state_repo` async-context-manager helpers. Mocks `AsyncMock`/`MagicMock`. No testcontainers Postgres dependency — all existing tests are pure-mock unit.
- Sibling: `tests/test_db_context.py` (if exists; check at sprint start) — informational, do not extend.

**Decision:** extend `tests/test_scheduler_service.py` with new test classes. Do **not** add testcontainers Postgres dependency in this sprint (would inflate scope and CI runtime). Pure-mock tests suffice to pin all three contracts; the post-deploy 24h watch (§ 5.3) validates against real Postgres in prod.

### 4.2 New tests (proposed minimum set)

#### T-1 — BUG-013: per-task session isolation (concurrent sources, no `IllegalStateChangeError`)

**File:** `tests/test_scheduler_service.py` — new test `test_bug013_per_task_session_isolation_across_concurrent_sources`.

**Setup:** 3 mock sources, each with its own per-task call to `ingestion_and_processing_repos` returning **distinct** mock `state_repo` / `processed_repo` instances. Assert that no two tasks ever receive the same mock session reference.

**Required new test fixture:** existing `_mock_ingestion_and_processing_repos(state_repo, processed_repo)` (test file lines 26-35) returns the same triple every call. T-1 needs a sibling helper `_mock_ingestion_and_processing_repos_queue(triples)` that yields a different triple per `__aenter__`:

```python
def _mock_ingestion_and_processing_repos_queue(triples):
    """Test helper for BUG-013: yield a distinct mock triple per call.

    triples: iterable of (state_repo, processed_repo, mock_db) tuples.
    """
    iterator = iter(triples)

    @asynccontextmanager
    async def _cm():
        triple = next(iterator)  # StopIteration → test bug, fail loudly
        yield triple

    return _cm
```

**Pattern sketch:**

```python
@pytest.mark.asyncio
async def test_bug013_per_task_session_isolation_across_concurrent_sources():
    sources = [Source(source_id=f"s{i}", channel_id=f"ch{i}", status="active",
                      include_comments=False) for i in range(3)]
    # Outer state_repo (only used for list_sources)
    outer_state_repo = AsyncMock()
    outer_state_repo.list_sources.return_value = sources
    # Per-task triples — distinct mocks
    per_task_triples = [(AsyncMock(name=f"state_{i}"),
                         AsyncMock(name=f"processed_{i}"),
                         MagicMock()) for i in range(3)]
    # ... patch ingestion_state_repo (outer) + ingestion_and_processing_repos (per-task queue)
    # Run run_incremental_for_all_sources; assert mock_calls on each per_task
    # triple's state_repo shows exactly one source's worth of operations.
    # Assert outer_state_repo.list_sources called once; .record_attempt NOT called
    # on outer (per-task triples handle it).
```

Acceptance: the test fails on `main` (single session triple shared by `_mock_ingestion_and_processing_repos`) and passes on the fix branch (distinct triples consumed in order).

#### T-2 — BUG-013: `asyncio.gather(return_exceptions=True)` does not cancel sibling tasks

**File:** same — new test `test_bug013_gather_isolates_per_task_failures`.

**Setup:** 3 mock sources; rig source #2 to raise `TypeError` from inside `_process_source` (simulating BUG-014 path or any per-task crash). Assert sources #1 and #3 still complete `run_full_pipeline` mock + appear in `sources_succeeded`. Assert source #2's exception is logged (capture via `caplog`) and does NOT cascade.

#### T-3 — BUG-014: tz-aware `rate_limit_until` comparison with naive value

**File:** same — new test `test_bug014_rate_limit_until_naive_value_does_not_raise`.

**Setup:** source with `rate_limit_until = datetime(2030, 1, 1, 0, 0, 0)` (naive, far future). Run `run_incremental_for_all_sources` over `[source]`. Assert no exception, source counted in `sources_skipped` (rate-limited path taken correctly), and `_coerce_aware_utc` helper accessible via direct import for an explicit unit assert.

#### T-4 — BUG-024: `last_attempt_at` non-null after `_process_source` runs (success path)

**File:** same — new test `test_bug024_last_attempt_at_committed_before_pipeline_await`.

**Setup:** mock `state_repo.mark_attempt_started` as `AsyncMock`. Run `_process_source` (or `run_incremental_for_all_sources` with single source). Assert `mark_attempt_started` was called exactly once with the source_id BEFORE any call to `run_full_pipeline`. Use `mock_calls` ordering or two-mock-spec collation (helper: `MagicMock(spec=...)` chain).

#### T-5 — BUG-024: `last_attempt_at` non-null even on per-task simulated failure

**File:** same — new test `test_bug024_last_attempt_at_committed_even_when_pipeline_raises`.

**Setup:** rig `run_full_pipeline` to raise mid-execution. Assert `mark_attempt_started` was still called pre-await; assert `record_attempt` was still called in `finally` with `success=False`. Both writes are independent — the invariant survives.

#### T-6 (optional) — Contract pin: `_coerce_aware_utc` invariants

**File:** same — small unit test class — fixed dt round-trip checks: `None → None`, naive → aware UTC, already-aware → identity.

### 4.3 Total new tests

~5 tests + 1 small contract class = **6 net** (4 mandatory, 2 belt-and-braces). Existing test count + 6 should hold; if any existing test asserts the `repo_lock` import or session-sharing behaviour directly, update it minimally to reflect the new contract.

### 4.4 Regression check

Run full `pytest -q` to capture baseline before vs after. **Expected delta:** +6 passed tests; 0 regressions. If baseline drifts unexpectedly, pause and investigate before continuing.

---

## 5. Risk / regression matrix

### 5.1 What we touch (this sprint)

| Surface | Change | Risk |
|---|---|---|
| `tg_parser/services/scheduler_service.py` | Move session open inside per-task closure; drop `repo_lock`; `gather(return_exceptions=True)` (semantic change: siblings now survive a per-task escape, see § 3.1 step 4); insert `_coerce_aware_utc` helper + call; insert `mark_attempt_started` call site | **Primary** — scheduler hot path. Mitigated by tests T-1..T-5 and 24h post-deploy watch. Semantic change of `gather` is the largest behavioural delta and is deliberate; tests T-2 pins the new contract. |
| `tg_parser/storage/ports.py` | Add abstract `mark_attempt_started` | Low — new method, no breaking change to existing consumers. Mock-based tests adapt via `AsyncMock` auto-spec. |
| `tg_parser/storage/sqlalchemy/ingestion_state_repo.py` | Add `mark_attempt_started` impl | Low — simple UPDATE + commit; mirrors `record_attempt` pattern. |
| `tests/test_scheduler_service.py` | +6 new tests | Low. |

### 5.2 What we deliberately do NOT touch (this sprint)

| Surface | Why deferred | Where it goes |
|---|---|---|
| `tg_parser/services/db_context.py` | Minimal-blast-radius rule — the `ingestion_and_processing_repos` context manager is correct; the bug is the caller pattern. F4-B Core's additive change to `db_context.py` stays untouched (workspace_repo continues to live there). | Out of scope; no change. |
| `tg_parser/domain/json_utils.py:parse_iso_datetime` (parse-time tz-aware fix) | Cross-cutting — every caller currently expects naive UTC. Audit required before flipping. | § 7 follow-up — file as separate TD after this sprint lands; the scheduler defensive coerce is sufficient short-term. |
| `tg_parser/storage/sqlalchemy/_metadata.py` (`rate_limit_until` String → TIMESTAMPTZ migration) | Alembic migration + read-path changes — large surface. The defensive coerce + parse-time fix (when it lands) makes a column-type migration unnecessary; only do it if a future audit identifies cases the defensive layer misses. | § 7 follow-up — ADR or larger TD candidate. |
| ENH-3 stuck-source Prometheus gauge | Tempting bonus (HANDOFF_POST_MCP_INTAKE Pending #1 mentions it). | § 7 — defer to follow-up unless trivial in implementation (sub-15 LOC + 1 metric registration); even then prefer separate PR for clean 24h watch attribution. |
| O-8 log-level bump (`rate_limit_*_adjusted` INFO → WARN) | Same as ENH-3 — bonus that muddies attribution of the 24h watch signals. | § 7 — defer. |
| `_pause_source_for_billing` (line 766-776 — write-site of `rate_limit_until`) | The write currently stores tz-aware `datetime.now(UTC)` via `_format_datetime` → it round-trips through `parse_iso_datetime` to naive on the next read. The fix-scope-as-defensive-coerce keeps this write untouched (no behaviour change). | Stays as-is. |
| `incremental_pipeline_task` wrapper / `BackgroundScheduler` integration | The fix isolates per-task crashes via `return_exceptions=True` but the outer task wrapper's success/error metric logic is unchanged. After the fix, the wrapper will see successful completion of `run_incremental_for_all_sources` → success counter starts incrementing again (this IS the desired behavioural change, see § 5.3). | Stays as-is; behaviour fix lands transparently. |
| F4-B Core (workspace scoping) | Zero changes — F4-B's invariant (workspace_id filtering on scoped reads) is unaffected because the scheduler does not consume workspace_id. The `workspace_repo` context manager remains untouched. | Stays as-is; non-regression baseline preserved. |

### 5.3 Validation matrix

#### Pre-merge (CI gates)

- [ ] `pytest -q` — baseline + 6 new tests, 0 regressions.
- [ ] `ruff check .` + `ruff format --check .` clean.
- [ ] Full GitHub Actions CI matrix green (Test Python 3.12, Lint Documentation, Alembic Guardrails, Alembic Runtime Upgrade Smoke, Docker Build).
- [ ] PR description includes `Closes #76, #77, #78`.
- [ ] `git diff origin/main...HEAD -- pyproject.toml requirements*.txt` returns empty (AGENTS.md hard rule).
- [ ] `git diff origin/main...HEAD -- tg_parser/services/db_context.py` returns empty (this sprint does not touch db_context).

#### Post-merge / post-deploy (24h watch — same signals as HANDOFF § Pending #2)

Validate from prod (`tg_parser_mcp.tgp.efimov.mobi` VPS), 24h after deploy:

```bash
# 1. BUG-013 closure — IllegalStateChangeError + InterfaceError → 0
ssh prod 'docker logs --since 24h tg_parser 2>&1 \
  | grep -cE "IllegalStateChangeError|InterfaceError"'
# Expected: 0 (was 21+ per 24h pre-fix)

# 2. BUG-013 closure (positive) — scheduler success counter > 0
ssh prod 'docker exec tg_parser_prometheus wget -qO- \
  "http://localhost:9090/api/v1/query?query=increase(tg_parser_scheduler_tasks_total{task_name=\"incremental_pipeline\",status=\"success\"}[24h])" \
  | python3 -m json.tool'
# Expected: ≥ 20 (was 0 pre-fix)

# 3. BUG-014 closure — TypeError → 0
ssh prod 'docker logs --since 24h tg_parser 2>&1 \
  | grep -cE "TypeError: can.t compare offset-naive"'
# Expected: 0 (was ~6 per 24h pre-fix)

# 4. BUG-024 closure — last_attempt_at non-null for any source that ticked
# Direct SQL via docker exec (admin fallback):
ssh prod 'docker exec tg_parser_postgres psql -U tg_parser -d tg_parser_state -t -c \
  "SELECT COUNT(*) FROM sources \
   WHERE status='\''active'\'' \
     AND last_success_at IS NOT NULL \
     AND last_attempt_at IS NULL;"'
# Expected: 0 (any row violating the invariant)
```

If ANY check fails — roll back per § 6 deploy + 24h watch criteria.

---

## 6. Execution sequence

### 6.1 Branch

Already created (this planning phase): `fix/bug-013-014-024-scheduler-sessions` off `origin/main` (HEAD `0aeed08`). Step E continues on the same branch.

### 6.2 Commit structure — recommendation: **single atomic joint-fix commit**

**Recommendation:** ONE atomic commit covering all three fixes + tests + the BUG_LOG closure rows + CHANGELOG entry.

**Reasoning:**

- BUG-024 fix depends on BUG-013 fix being already applied (per-task sessions enable synchronous commit). Splitting BUG-013 from BUG-024 would create an intermediate commit where BUG-024 is half-fixed.
- BUG-014 fix is mechanically independent but co-located in the same function — splitting it adds friction for the reviewer (two diffs touching the same `_process_source` body).
- A single commit makes rollback trivial (`git revert <sha>`) — and rollback is what matters for prod safety. Per-bug rollback is unnecessary because the failure modes are all silent / non-data-corrupting; if we needed surgical rollback, we'd be in a worse situation than just reverting the whole sprint.
- Mirrors Session G precedent (BUG-009 + scope guard single-commit sprint).

**Alt:** separate commits per bug + a final test+docs commit. **Rejected** because the per-bug intermediate states create review burden without giving reviewers anything they couldn't get from a single well-organized diff with section banners.

**Commit message template** (HEREDOC body):

```
fix(scheduler): per-task sessions + tz-aware rate_limit + sync attempt-at (BUG-013/014/024)

Joint fix-sprint closing three pre-existing scheduler bugs surfaced by
F4-B Core 24h watch window (2026-05-13 → 2026-05-14):

* BUG-013: move ingestion_and_processing_repos() inside per-task closure
  in _process_source; drop repo_lock; gather(*, return_exceptions=True)
  isolates per-task failures. SQLAlchemy 2.x AsyncSession concurrency
  invariant restored. Closes #76.

* BUG-014: defensive _coerce_aware_utc helper at line 89 comparison;
  source.rate_limit_until parsed naive by parse_iso_datetime is now
  coerced to tz-aware UTC before compare. Parse-time fix deferred (see
  follow-up TD). Closes #77.

* BUG-024: new IngestionStateRepo.mark_attempt_started method + call
  site in _process_source before first pipeline await — synchronous
  commit invariant for last_attempt_at. Safe per-task after BUG-013.
  Closes #78.

Tests: +6 in tests/test_scheduler_service.py (T-1..T-6 per planning
artifact § 4.2). 0 regressions in default pytest suite.

Non-regression: F4-B Core invariants untouched (db_context.py unchanged;
workspace_repo / workspace_id contract preserved). Hard rules: no edits
to pyproject.toml / requirements*.txt; no docs/methodology/** touched.

See: docs/notes/START_PROMPT_FIX_BUG013_SCHEDULER_SESSION_2026-05-15.md
```

### 6.3 PR template

**Title:** `fix(scheduler): per-task sessions + tz-aware rate_limit + sync attempt-at (BUG-013/014/024)`

**Body** (HEREDOC, pass via `--body-file` to avoid heredoc-shell hangs — Session G/PR #56 lesson):

```
## Summary
Joint fix-sprint closing three pre-existing scheduler bugs surfaced by F4-B Core
24h watch window (2026-05-13 → 2026-05-14). All three Medium severity, all share
`scheduler_service._process_source` as code surface, fixes compose (BUG-013 →
BUG-024). Planning artifact: `docs/notes/START_PROMPT_FIX_BUG013_SCHEDULER_SESSION_2026-05-15.md`.

Closes #76 (BUG-013). Closes #77 (BUG-014). Closes #78 (BUG-024).

## Changes
- `tg_parser/services/scheduler_service.py` — per-task session open inside
  `_process_source`; `repo_lock` dropped; `gather(return_exceptions=True)`;
  `_coerce_aware_utc` helper + line-89 call; `mark_attempt_started` call site.
- `tg_parser/storage/ports.py` — new abstract `IngestionStateRepo.mark_attempt_started`.
- `tg_parser/storage/sqlalchemy/ingestion_state_repo.py` — `mark_attempt_started`
  impl (UPDATE + commit, mirrors `record_attempt` pattern).
- `tests/test_scheduler_service.py` — +6 tests (per-task isolation, gather isolation,
  tz-aware coerce, sync attempt-at on success + failure path, coerce-helper contract).
- `docs/notes/BUG_LOG.md` § BUG-013/014/024 — append `Update 2026-05-XX — joint
  fix-sprint landed` closure rows.
- `CHANGELOG.md` — new `## [Unreleased]` block.

## F4-B non-regression
- `git diff origin/main...HEAD -- tg_parser/services/db_context.py` ⇒ empty.
- `workspace_repo` context manager + `workspace_id`-scoped read tools untouched.

## Test plan (CI gates)
- [ ] `pytest -q` baseline + 6 new, 0 regressions
- [ ] `ruff check .` + `ruff format --check .` clean
- [ ] Full Actions matrix green (5 checks)

## Smoke (post-deploy 24h watch)
[Copy from § 5.3 of planning artifact]
```

### 6.4 CI gates

Same as § 5.3 pre-merge. Single PR; squash-merge to keep history tidy.

### 6.5 Deploy + 24h watch

Per HANDOFF § Pending #2 step 4 sequence: `git pull` on prod VPS → `docker compose build tg_parser && docker compose up -d --no-deps --force-recreate tg_parser tg_bot tg_parser_mcp`. Track watch window open time in a temporary scratch note; close after 24h via § 5.3 post-deploy checklist.

### 6.6 Closure

Per HANDOFF § Pending #2 step 5 — `REVIEW_2026-05-XX_BUG013_14_24_DONE.md` mirror of Session G / Session J DONE marker pattern. Update `BUG_LOG.md` § BUG-013/014/024 status `open → resolved` with closure SHA + watch verdict.

---

## 7. Out-of-scope / follow-ups

| Item | Why deferred | Suggested follow-up |
|---|---|---|
| **TD-parse-iso-datetime-aware** — make `parse_iso_datetime` attach `UTC` when input ends with `Z` (parse-boundary fix for BUG-014's structural cause) | Cross-cutting — every caller currently expects naive UTC; audit required. The defensive coerce in scheduler is sufficient short-term. | File as TD issue post-merge with explicit consumer audit task. ~5 LOC fix + audit. Could land in Wave 1 step 3 housekeeping. |
| **Alembic migration `rate_limit_until` String → TIMESTAMPTZ** | Larger surface (migration + read-path adaptation); the defensive + parse-time layers make this unnecessary unless a future audit identifies a gap. | Open as ADR candidate if/when the parse-time fix audit surfaces consumers that genuinely want tz-aware semantics from this column. |
| **ENH-3 stuck-source detection — Prometheus gauge + structured `health_check`** | Cleanly separable. Mixing it into this PR muddies the 24h watch attribution (was the success-counter recovery from BUG-013 fix, or from a new metric?). | Separate small PR after fix-sprint 24h watch closure. See HANDOFF_POST_MCP_INTAKE Pending #1 bonus list. |
| **O-8 log-level bump for `rate_limit_*_adjusted` INFO → WARN** | Same as ENH-3 — clean separation. | Same separate PR (quick housekeeping bundle). |
| **DB-level tz-aware migration / ADR on datetime persistence strategy** | Out of scope for fix-sprint; design discussion. | Wave 1 step 3 ADR (numbered TBD) if the structural fix in `parse_iso_datetime` proves insufficient. |
| **`_pause_source_for_billing` symmetric write-time fix** | The write currently round-trips through `_format_datetime("...Z")` → `parse_iso_datetime` → naive — fixing only the read path (this sprint) is sufficient. Co-changing the write adds review surface for no observable behaviour change. | Bundles naturally with TD-parse-iso-datetime-aware. |

---

## 8. Approval checkpoint

**THIS IS A PLANNING-ONLY ARTIFACT. USER OK REQUIRED BEFORE STEP E (IMPLEMENTATION).**

Approval is required for:

1. **Joint-fix scope** — three bugs, single sprint, single PR — vs splitting (e.g. BUG-013 + BUG-024 together, BUG-014 separate). Planning recommendation: keep joint per § 6.2 reasoning. **Question for user:** confirm joint, or split BUG-014?
2. **Per-task session pattern** — option (b) from § 3.1 step 3 (keep aggregate dict mutation cooperative under GIL, no parent-merge dance) — minimal-diff path. **Question for user:** confirm option (b), or prefer per-task local accumulators + parent merge after gather (option (a))?
3. **`asyncio.gather(*, return_exceptions=True)`** — defensive change that isolates sibling tasks from per-task crashes. Adds 4-5 LOC at the gather call and one log-line loop after. **Question for user:** confirm include? (Recommendation: yes — small, clearly value-additive, well-aligned with the per-task isolation goal.)
4. **Defensive `_coerce_aware_utc` helper at call site vs parse-time fix in `parse_iso_datetime`** — planning recommends call-site defensive coerce for THIS sprint, with parse-time fix as a follow-up TD. **Question for user:** confirm, or push parse-time fix into this sprint (would require consumer audit)?
5. **New `IngestionStateRepo.mark_attempt_started` method** — adds port + impl. Mock-based test fakes adapt via `AsyncMock` auto-spec. **Method-name alternatives considered:**
   - `mark_attempt_started(source_id)` — **recommended.** Reads as a verb-event, explicit about timing (before-await). Mirrors `record_attempt(...)`'s verb-style.
   - `update_attempt_at(source_id)` — name used informally in HANDOFF § Pending #2. Reads as a state-mutation; less explicit about the timing semantic. Acceptable but slightly less narrative.
   - `touch_last_attempt(source_id)` — too colloquial; `touch` carries Unix-filesystem connotation. Reject.
   
   **Question for user:** confirm `mark_attempt_started` or override with `update_attempt_at`?
6. **Out-of-scope items** in § 7 — confirm deferral of ENH-3, O-8, parse-time fix, `_pause_source_for_billing` symmetric, DB migration.

**Default answers if user says «proceed with defaults»:** confirm all six recommendations as planned. Implementation worker (Step E) proceeds with no further gating.

---

## 9. Changelog

| Дата | Изменение |
|---|---|
| 2026-05-15 ~17:00 UTC+4 | Первая версия. Planning artifact for joint fix-sprint BUG-013 + BUG-014 + BUG-024. GH issues filed: [#76](https://github.com/AlexEfimov/TG_parser/issues/76), [#77](https://github.com/AlexEfimov/TG_parser/issues/77), [#78](https://github.com/AlexEfimov/TG_parser/issues/78). Sprint branch `fix/bug-013-014-024-scheduler-sessions` created off `origin/main` (HEAD `0aeed08`). Awaiting user approval for Step E (implementation). |
| 2026-05-15 ~17:25 UTC+4 | Self-review pass. § 3.1 step 1 — added Source-object detachment note (plain dataclass, not session-bound proxy); § 3.1 step 3 — replaced GIL handwaving with cleaner asyncio cooperative-scheduling reasoning + "no shared aggregate key per source" argument; § 3.1 step 4 — explicit «semantic change» flag for `gather(return_exceptions=True)`; § 3.1 — new paragraph on optional `state_repo` / `processed_repo` kwargs (zero production callers verified via Grep; recommend keep-for-compat); new paragraph on rate-limited skip + BUG-024 invariant scope («skipped is not attempted»); new paragraph on `_record_and_pause_on_billing` interaction with the per-task session post-fix. § 3.3 step 5 — tightened «no in-memory test-fake exists; verified at planning time». § 3.4 — added alternative reviewer ordering (BUG-014 → BUG-013 → BUG-024) for implementation flexibility. § 4.2 T-1 — added required `_mock_ingestion_and_processing_repos_queue` helper sketch and explicit fixture pattern with outer + per-task mocks. § 5.1 — flagged `gather` semantic change as the largest behavioural delta in the risk row. § 8 item 5 — enumerated method-name alternatives (`mark_attempt_started` vs `update_attempt_at` vs `touch_last_attempt`) with rationale. No design issues found; no commits / src edits made; artifact remains planning-only. |
