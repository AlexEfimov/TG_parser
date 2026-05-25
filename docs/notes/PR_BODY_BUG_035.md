## Summary

Closes BUG-035. Hardens `BackgroundScheduler.remove_task` to always attempt `AsyncIOScheduler.remove_job` (not only when the in-memory `_tasks` dict tracks the id), specifically catches `apscheduler.jobstores.base.JobLookupError` for the race with the reconcile loop, and emits a structured `scheduler_job_removed` event tagged with a `reason` so operators can attribute every scheduler-state mutation back to its origin (`mcp_unsubscribe_digest` / `bot_unsubscribe_digest` / `reconcile` / `*_subscribe_digest_reregister`). The MCP and bot `unsubscribe_digest` tools forward the new `reason` kwarg. No behavioural change for the reconcile loop or for the existing tick-time DB re-check inside `run_scheduled_digests_task` — both remain in place as defense-in-depth.

## Root cause (post-investigation; replaces handoff hypothesis)

The handoff hypothesis was that `unsubscribe_digest` simply did not call `scheduler.remove_job`. Empirically, both surfaces (MCP `tg_parser/mcp_server.py::unsubscribe_digest` and bot `tg_parser/bot/tools.py::_exec_unsubscribe_digest`) **have** invoked `unregister_digest_subscription(sub_id)` synchronously after the DB delete since F6's introduction (PR #11, commit `410452a`, 2026-04-19). The orphan-tick delivery observed during the Test C cleanup on 2026-05-24 ~21:00Z must have come from a different mechanism — most likely the cross-process gap inherent to the deployment: MCP and bot run as **separate Docker containers** (`docker-compose.yml` lines 168 + 243), each with its own `BackgroundScheduler` singleton. An `unregister_digest_subscription` call inside the MCP container only mutates the MCP-process scheduler (which never had the job — only the bot does). The bot's singleton retains the job until its 60-second `_reconcile_loop` next ticks.

Two safeguards already mitigated this in practice:

1. **Tick-time DB re-check** — `run_scheduled_digests_task` (in the bot process) opens a fresh `digest_subscription_repo()` context at the start of every cron tick and bails with `status="not_found"` if `sub_repo.get(...)` returns `None`. Any tick that fires after the DB delete commits short-circuits before delivery.
2. **Reconcile loop** — `reconcile_digest_subscriptions()` diffs `desired` (active rows in DB) against `registered` (jobs in the in-memory `_tasks` dict) and unregisters orphans every `digest_refresh_interval` (default 60s).

The structural gap closed by this PR is narrower and more operational:

* The pre-fix `BackgroundScheduler.remove_task` returned `False` immediately when `task_id not in self._tasks` — it **never attempted** `AsyncIOScheduler.remove_job` in that branch. So in any deployment where the bookkeeping dict has diverged from the APScheduler job store (cross-process replicas, future shared `JobStore` backends, an aborted reconcile mid-tick), `unregister_digest_subscription` would be a silent no-op even when the underlying scheduler did still have the job.
* The pre-fix path also swallowed a bare `Exception` from `scheduler.remove_job` with a `logger.debug`, which masked schema/network errors that should fail loud.
* The pre-fix path emitted a positional `logger.info("Removed task %s", task_id)` line with no `reason` tag — operators cannot tell from logs whether a removal came from an MCP unsubscribe, a bot tool unsubscribe, a reconcile-loop sweep, or a subscribe-then-replace cycle.

This PR makes `remove_task` genuinely idempotent across all those dimensions, specifically handles `JobLookupError` (apscheduler's documented "missing-job" signal), and threads a `reason` tag through every scheduler-mutation call site.

## Scope decision (digest-only)

`unsubscribe_watchlist` is **not** symmetric to `unsubscribe_digest`. The F11 matcher does not own a per-interest APScheduler job — it runs piggy-back inside the incremental pipeline tick and reads `WatchInterestRepoPort.list_active_for_channel(channel_id)` at the start of every tick, which filters on `is_active = TRUE`. The `unsubscribe_watchlist` tool soft-deletes the interest (`is_active=False`), so it immediately drops out of the matcher's source set — no in-memory scheduler state to invalidate, no orphan-tick window to close.

This invariant is locked in by `tests/test_scheduler_invalidation_on_unsubscribe.py::TestWatchlistInvalidationByConstruction`. If a future change introduces APScheduler-driven scheduling for watchlists, those guards will fail and force a symmetric fix to be added inside this same test file.

## Before / after

### `tg_parser/services/background_scheduler.py::BackgroundScheduler.remove_task`

Before:

```python
def remove_task(self, task_id: str) -> bool:
    if task_id not in self._tasks:
        return False  # <-- never attempts scheduler.remove_job

    try:
        self._scheduler.remove_job(task_id)
    except Exception as e:
        logger.debug("Job %s not found in scheduler: %s", task_id, e)

    del self._tasks[task_id]
    logger.info("Removed task %s", task_id)
    return True
```

After:

```python
def remove_task(self, task_id: str, *, reason: str | None = None) -> bool:
    had_tracked = task_id in self._tasks
    had_scheduled = False
    try:
        self._scheduler.remove_job(task_id)
        had_scheduled = True
    except JobLookupError:
        pass  # idempotent: reconcile / sibling already removed it
    self._tasks.pop(task_id, None)
    if had_tracked or had_scheduled:
        logger.info(
            "scheduler_job_removed",
            task_id=task_id,
            reason=reason or "unspecified",
            from_memory=had_tracked,
            from_scheduler=had_scheduled,
        )
        return True
    logger.debug(
        "scheduler_job_remove_noop",
        task_id=task_id,
        reason=reason or "unspecified",
    )
    return False
```

### `tg_parser/services/background_scheduler.py::unregister_digest_subscription`

```python
def unregister_digest_subscription(
    subscription_id: str,
    scheduler: BackgroundScheduler | None = None,
    *,
    reason: str = "unsubscribe",
) -> bool:
    sched = scheduler or get_scheduler()
    return sched.remove_task(_digest_job_id(subscription_id), reason=reason)
```

### MCP + bot call sites

```python
# tg_parser/mcp_server.py::unsubscribe_digest
unregister_digest_subscription(sub_id, reason="mcp_unsubscribe_digest")

# tg_parser/bot/tools.py::_exec_unsubscribe_digest
unregister_digest_subscription(sub_id, reason="bot_unsubscribe_digest")

# tg_parser/services/scheduler_service.py::reconcile_digest_subscriptions
unregister_digest_subscription(sub_id, reason="reconcile")
```

## Test plan

New regression file `tests/test_scheduler_invalidation_on_unsubscribe.py` — **19 tests**, organised into 5 layers:

* **Layer A — `BackgroundScheduler.remove_task` hardening (10 tests):** cross-process `_tasks`-dict-divergence, in-memory-only and scheduler-only paths, idempotent double-call, `JobLookupError` swallowed, other exceptions propagated, structured `scheduler_job_removed` event includes `reason`, `unregister_digest_subscription` forwards `reason` (default `"unsubscribe"`, idempotent on second call).
* **Layer B — end-to-end MCP / bot unsubscribe contract (3 tests):** MCP `unsubscribe_digest` removes the in-process scheduler job atomically (verified via direct logger introspection: `scheduler_job_removed` event with `reason="mcp_unsubscribe_digest"` and the matching `task_id`); same shape for bot `_exec_unsubscribe_digest` (`reason="bot_unsubscribe_digest"`); MCP unsubscribe twice returns `success=False` "not found" the second time.
* **Layer C — anti-regression for existing safeguards (3 tests):** `run_scheduled_digests_task` returns `status="not_found"` when the DB row is gone; full `subscribe → register job → MCP unsubscribe → fire tick → assert AsyncMock(Bot).send_message.await_count == 0` end-to-end (no delivery); reconcile loop removes orphan jobs after an external (psql-style) DB delete.
* **Layer D — watchlist scope decision (2 tests):** soft-deleted interest is excluded from `WatchInterestRepoPort.list_active_for_channel`; `WatchlistService.check_interests` produces zero matches when the only matching interest has been soft-deleted (proves the digest-only scope decision).
* **Layer E — Prometheus assertion (1 test):** snapshot `tg_digest_channel_publish_total` for every label, run the `subscribe → unsubscribe → manual tick` sequence with a mocked Bot, snapshot again — counter MUST be unchanged.

### Self-review-and-rerun loop (operator-mandated)

* [x] Initial green run on the new file (`TEST_POSTGRES=1`): **19 passed, 0 failed**.
* [x] Stashed the production fix (`git stash push -- tg_parser/bot/tools.py tg_parser/mcp_server.py tg_parser/services/background_scheduler.py tg_parser/services/scheduler_service.py`) and reran on `main@66e8297` shape: **8 failed, 11 passed**:
  * 6 unit-level hardening tests (`test_remove_task_removes_apscheduler_job_when_dict_empty`, `test_remove_task_swallows_job_lookup_error_from_apscheduler`, `test_remove_task_propagates_unexpected_exceptions`, `test_remove_task_emits_structured_reason_in_log`, `test_unregister_passes_reason_to_remove_task`, `test_unregister_default_reason_is_unsubscribe`);
  * 2 end-to-end telemetry assertions (MCP + bot atomically-remove tests — pre-fix emits positional `("Removed task %s", task_id)` instead of the structured `scheduler_job_removed` event, captured cleanly with `Got captured calls: [(('Removed task %s', ...), {})]`).
  * The 11 tests that still pass on pre-fix code prove that the existing safeguards (tick-time DB re-check + reconcile loop + soft-delete-by-construction for watchlist) were already working — this PR is **strictly additive**, closing a narrower telemetry + cross-process invalidation gap rather than the broader "no removal happens" gap the handoff originally hypothesised.
* [x] Self-review identified that the original integration tests would pass pre-fix because the basic call was already in place; strengthened the MCP / bot end-to-end tests to **also** assert on the new structured `scheduler_job_removed` event with the right `reason` tag, captured via direct `logger.info` introspection (more deterministic than `caplog` under pytest-asyncio + structlog stdlib routing).
* [x] Restored fix (`git stash pop`) and reran: **19/19 passed** on the new file.

### Full affected-suite rerun

Normal mode:

```
.venv/bin/pytest tests/test_scheduler_invalidation_on_unsubscribe.py \
    tests/test_bot_chat_target_resolution.py tests/test_bot_channel_name_parser.py \
    tests/test_bot_confirm_flow.py tests/test_f4b_deferred_surface_guard.py \
    tests/test_f11_bot_tools.py tests/test_subscribe_idempotency.py \
    tests/test_f6_scheduled_digests.py
=> 336 passed, 30 skipped
```

**Mandatory `TEST_POSTGRES=1` rerun** (per `docs/notes/SKIPPED_TESTS_AUDIT_2026-05-25.md`):

```
TEST_POSTGRES=1 .venv/bin/pytest \
    tests/test_scheduler_invalidation_on_unsubscribe.py tests/test_f6_scheduled_digests.py \
    tests/test_f11_mcp_tools.py tests/test_subscribe_idempotency.py \
    tests/test_api_digests.py tests/test_bot_chat_target_resolution.py \
    tests/test_bot_channel_name_parser.py tests/test_bot_confirm_flow.py \
    tests/test_f4b_deferred_surface_guard.py tests/test_f11_bot_tools.py
=> 407 passed, 1 skipped, 0 failed
```

The single skip is the pre-existing `test_concurrent_two_confirms_race_documented` integration-harness skip (tracked as TD-confirm-flow-concurrency-integration) — unrelated to this PR.

### `ruff` results

```
ruff check tg_parser/services/background_scheduler.py tg_parser/services/scheduler_service.py \
           tg_parser/mcp_server.py tg_parser/bot/tools.py \
           tests/test_scheduler_invalidation_on_unsubscribe.py
=> All checks passed!

ruff format --check (same five files)
=> 5 files already formatted
```

### Reconcile-loop invariant (defense-in-depth)

`reconcile_digest_subscriptions()` continues to handle two cases this PR does not address synchronously:

1. **External DB deletes** (psql, alembic migrations) that bypass both MCP and bot tools — reconcile catches the orphan within ≤ `digest_refresh_interval`.
2. **Cross-process MCP-side deletes** — the bot's reconcile loop still picks up the deletion within ≤ `digest_refresh_interval`. The tick-time DB re-check (`run_scheduled_digests_task` → `sub_repo.get(...) is None` → `status="not_found"`) prevents any stale delivery during that window.

Both are explicitly asserted by `TestReconcileLoopOrphanCleanup::test_reconcile_loop_removes_orphan_job_after_external_db_delete` and `TestTickTimeSafeguard::test_run_scheduled_digests_task_returns_not_found_after_db_delete` so accidental regressions in either path are caught at PR review time.

## References

- [`docs/notes/BUG_LOG.md` § BUG-035](docs/notes/BUG_LOG.md)
- [`docs/notes/HANDOFF_NEXT_CHAT_WAVE1_STEP4_POST_WATCH_2026-05-25.md` § 3.1](docs/notes/HANDOFF_NEXT_CHAT_WAVE1_STEP4_POST_WATCH_2026-05-25.md)
- [`docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`](docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md) (Test C cleanup empirical trace)
- [`docs/notes/SKIPPED_TESTS_AUDIT_2026-05-25.md`](docs/notes/SKIPPED_TESTS_AUDIT_2026-05-25.md) (`TEST_POSTGRES=1` rerun mandate)
- Recent merge precedent: `e50449b` (BUG-033 PR #108), `6ebad33` (BUG-034 PR #109), `66e8297` (BUG-031+032 PR #111)

## Operator action required

- **DO NOT MERGE** without sign-off (per `AGENTS.md` + handoff anti-patterns).
- Optional follow-up (not in scope): consider lowering `digest_refresh_interval` from 60s to 15-30s in production to shrink the cross-process convergence window further. Pure operational tuning — no code change required.
- Optional follow-up (not in scope): the empirical orphan delivery observed on 2026-05-24 ~21:00Z remains unexplained at the code level (the tick-time DB re-check should have caught it). The most likely culprit is a sub-second race between the DB delete commit and the cron-tick coroutine completing its `sub_repo.get(...)` lookup, but no production trace correlates that hypothesis with certainty. If the pattern recurs after this PR ships, a separate spike to add `SELECT FOR UPDATE` on the tick-time fetch (or a `BEGIN ISOLATION LEVEL REPEATABLE READ` envelope around delete) may be warranted.
