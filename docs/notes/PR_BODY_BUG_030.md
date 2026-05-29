## Summary

Closes **BUG-030**. The bot's digest-scheduler bootstrap (`tg_parser/bot/main.py::_start_digest_scheduler`) read the initial set of active subscriptions inside a **bare `try / except Exception:`** that clamped `active = []` on *any* failure. On a Postgres-startup race (parallel `docker compose up -d`, or an Alembic migration mid-flight) the read raised a transient `OperationalError` / `InterfaceError`, the except swallowed it silently, and the scheduler started with **zero jobs** — no digests delivered until the 60s reconcile loop self-healed.

This PR wraps the initial-load read in a **hand-rolled, bounded retry loop** (5 attempts, escalating backoff `2-3-5-10s`) that retries **only** transient connection-level errors, escalates exhaustion to a `logger.critical` (no longer silent), and **narrows the swallow contract** so schema-shape errors fail loud instead of degrading to an empty job-set.

## Hand-rolled, NOT tenacity (operator decision)

The BUG_LOG "Proposed fix" and the handoff both sketched a `tenacity.AsyncRetrying` implementation. Per **operator decision, that approach was rejected to avoid adding a new runtime dependency** (`tenacity` is not currently in `requirements.txt`, and `AGENTS.md` forbids unrequested dependency edits). Instead this PR mirrors the **existing in-tree hand-rolled retry idiom** already settled in 6+ places:

* `tg_parser/processing/llm/anthropic_client.py:147-263` — `for attempt in range(1, max_retries + 1)` with exponential backoff, per-attempt `logger.warning`, and a final raise. (Closest reference.)
* `tg_parser/api/webhooks.py:69-131` — `for attempt in range(max_retries + 1)` with `await asyncio.sleep(backoff)`.

**No new dependency was added. `requirements.txt` / `pyproject.toml` are untouched.**

## Root cause

`_start_digest_scheduler` runs as one of the first async tasks at bot boot. At `T+259ms` post-start (well before the `f1a2b3c4d5e6 → a8b7c6d5e4f3` migration committed at `T+40s`) the `digest_subscription_repo()` read raised, was caught by the coarse `except Exception:`, and the scheduler logged `digest_scheduler_started active_subscriptions=0`. The only recovery path was the `_reconcile_loop` firing its first tick after `digest_refresh_interval` (default **60s**). The window was empirically observed on the 2026-05-24 VPS step-4 deploy (`digest_scheduler_initial_load_failed @ 10:46:40Z → digest_reconcile added_cron_task @ 10:47:40Z`). Recovery was self-healing within ≤60s, but: (a) any cron tick landing in the degraded window is silently skipped; (b) the failure was logged at `error` with an opaque `exc_info` marker, not escalated; (c) if the reconcile loop is itself degraded by the same transient, the system can stay at `active_subscriptions=0` until a full restart.

## Contract decision: fall-through-to-`[]` on transient exhaustion, fail-loud on schema-shape

Two distinct failure classes are now treated differently:

1. **Transient connection-level errors** (`OperationalError`, `InterfaceError`) — these *self-heal* (DB warming up / pool reset). Retried up to 5 times with escalating backoff. On exhaustion the helper logs **`logger.critical("digest_scheduler_initial_load_exhausted_retries", ...)`** (unmistakable, not silent) and re-raises; the caller then **falls through to `active = []` as a documented last resort**, preserving the existing 60s reconcile-loop self-healing path. Worst-case total wait `2+3+5+10 = 20s`, comfortably inside the 60s reconcile window.

2. **Schema-shape / everything-else errors** (`ProgrammingError`, `IntegrityError` on a half-migrated table, or any non-DBAPI bug) — these will **not** self-heal, so they are **not** retried and **not** swallowed. They propagate out of `_start_digest_scheduler` and crash the bot loud, forcing an operator-visible container restart rather than a silent steady-state degraded scheduler.

**Why the fallback `except` is narrowed to `(OperationalError, InterfaceError)` and not `(OperationalError, InterfaceError, DatabaseError)`** (as the BUG_LOG sketch suggested): in the SQLAlchemy exception hierarchy `OperationalError`, `ProgrammingError`, and `IntegrityError` are **all subclasses of `DatabaseError`**, while `InterfaceError` is a sibling. Catching `DatabaseError` in the fallback would re-swallow `ProgrammingError` / `IntegrityError` to `active = []` — exactly the silent-degradation we are removing. The fallback therefore catches only the two transient connection-level types; all other `DatabaseError` subclasses fail loud. This boundary is locked in by `test_generic_database_error_not_retried` and `test_non_transient_programming_error_not_retried`.

## Before / after — `tg_parser/bot/main.py`

Before:

```python
try:
    async with digest_subscription_repo() as (repo, _db):
        active = await repo.list_active()
except Exception:
    logger.exception("digest_scheduler_initial_load_failed")
    active = []
```

After (initial-load read extracted into a testable helper + narrowed caller):

```python
_INITIAL_LOAD_MAX_ATTEMPTS = 5
_INITIAL_LOAD_BACKOFF_SCHEDULE = (2, 3, 5, 10)  # seconds before attempts 2..5

async def _load_active_subscriptions_with_retry(repo_cm_factory=None) -> list[Any]:
    if repo_cm_factory is None:
        from tg_parser.services.db_context import digest_subscription_repo
        repo_cm_factory = digest_subscription_repo

    last_exc: Exception | None = None
    for attempt in range(1, _INITIAL_LOAD_MAX_ATTEMPTS + 1):
        try:
            async with repo_cm_factory() as (repo, _db):
                return await repo.list_active()
        except (OperationalError, InterfaceError) as exc:
            last_exc = exc
            if attempt < _INITIAL_LOAD_MAX_ATTEMPTS:
                backoff = _INITIAL_LOAD_BACKOFF_SCHEDULE[attempt - 1]
                logger.warning("digest_scheduler_initial_load_retry", attempt=attempt, ...)
                await asyncio.sleep(backoff)
                continue
            logger.critical("digest_scheduler_initial_load_exhausted_retries", ..., exc_info=True)
            raise
    raise RuntimeError("digest scheduler initial-load retry loop exited unexpectedly") from last_exc

# in _start_digest_scheduler():
try:
    active = await _load_active_subscriptions_with_retry()
except (OperationalError, InterfaceError):
    active = []   # last-resort; reconcile loop still self-heals (logged CRITICAL above)
```

`ProgrammingError` / `IntegrityError` / generic `DatabaseError` are deliberately absent from both the retry `except` and the fallback `except`, so they propagate.

## Test plan

New regression file `tests/test_digest_scheduler_initial_load_retry.py` — **10 tests**:

* **Helper-level (7):** happy-path (no retry, no sleep); transient `OperationalError` ×2 then success (asserts 3 `list_active` calls + sleep cadence `[2, 3]`); transient `InterfaceError` retried; exhaustion logs `critical` + re-raises (5 calls, 4 sleeps); backoff schedule strictly escalating (`[2, 3, 5, 10]`); non-transient `ProgrammingError` not retried/not swallowed/no critical; generic `DatabaseError` boundary not retried.
* **Caller-level (3):** transient exhaustion → `critical` logged + `active=[]` fallback + scheduler still starts, no subscriptions registered; `ProgrammingError` propagates out of `_start_digest_scheduler` (fails loud, not swallowed); happy path registers every loaded subscription.

The CRITICAL-log assertion uses `patch.object(logger, "critical")` capturing call args — **not** `caplog` (per the PR #111 self-review lesson that `caplog` is flaky with structlog). `asyncio.sleep` is patched throughout so the suite is fast + deterministic.

### Stash-proof (operator-mandated)

The fix in `tg_parser/bot/main.py` was reverted to `main@ce020ce` shape and the new file rerun:

```
=> 8 failed, 1 passed
```

The 1 pass is the happy-path caller test (unchanged behaviour). The 6 helper tests fail (symbols absent), and crucially the **two behavioral caller tests fail**: pre-fix code swallows `ProgrammingError` to `active = []` (the captured traceback shows the old `digest_scheduler_initial_load_failed` event + `active_subscriptions=0`) and never logs CRITICAL / never retries on exhaustion. Fix restored → **10/10 pass**.

### Self-review gaps found + fixed

* Added `test_generic_database_error_not_retried` to nail the `DatabaseError`-vs-`OperationalError`/`InterfaceError` boundary explicitly called out in the review checklist (the original suite only covered `ProgrammingError`).
* Refactored the test module to reference the new symbols via the `bot_main` module object rather than top-level `import`, so the stash-proof produces **behavioral** failures (caller tests run and demonstrate the silent-swallow bug) instead of a blanket collection `ImportError`.

### Full affected-suite rerun

Normal mode:

```
.venv/bin/python -m pytest tests/test_digest_scheduler_initial_load_retry.py \
    tests/test_bot_*.py tests/test_f6_scheduled_digests.py
=> 532 passed, 23 skipped
```

**Mandatory `TEST_POSTGRES=1` rerun** (per `docs/notes/SKIPPED_TESTS_AUDIT_2026-05-25.md`):

```
TEST_POSTGRES=1 .venv/bin/python -m pytest \
    tests/test_digest_scheduler_initial_load_retry.py tests/test_f6_scheduled_digests.py \
    tests/test_f11_mcp_tools.py tests/test_subscribe_*.py tests/test_api_digests.py \
    tests/test_bot_*.py tests/test_f4b_*.py
=> 757 passed, 1 skipped, 0 failed
```

The single skip is the pre-existing `test_concurrent_two_confirms_race_documented` integration-harness skip (TD-confirm-flow-concurrency-integration) — unrelated to this PR. No fixture-rot observed; the previously Postgres-gated F6 tests all run green.

### `ruff` results

```
ruff check  tg_parser/bot/main.py tests/test_digest_scheduler_initial_load_retry.py => All checks passed!
ruff format --check (same two files)                                                => 2 files already formatted
```

## References

- [`docs/notes/BUG_LOG.md` § BUG-030](docs/notes/BUG_LOG.md)
- [`docs/notes/HANDOFF_NEXT_CHAT_WAVE1_STEP4_POST_WATCH_2026-05-25.md` § 1.3](docs/notes/HANDOFF_NEXT_CHAT_WAVE1_STEP4_POST_WATCH_2026-05-25.md)
- [`docs/notes/SKIPPED_TESTS_AUDIT_2026-05-25.md`](docs/notes/SKIPPED_TESTS_AUDIT_2026-05-25.md) (`TEST_POSTGRES=1` rerun mandate)
- Retry-idiom precedents: `tg_parser/processing/llm/anthropic_client.py:147-263`, `tg_parser/api/webhooks.py:69-131`
- Recent merge precedent: `e50449b`, `6ebad33`, `66e8297`, `af7790f`, `ce020ce`

## Operator action required

- **DO NOT MERGE** without sign-off (per `AGENTS.md` + handoff anti-patterns).
- Out-of-scope follow-ups (deferred per BUG_LOG Layers C/D/E): wire `structlog.processors.format_exc_info` into the bot's deploy logging chain so the CRITICAL traceback renders; add a compose-level `depends_on: postgres: condition: service_healthy` guard on the bot service to eliminate the connection-pool race at the orchestrator level.
