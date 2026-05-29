## Summary

Fixes BUG-029 (Medium — backend correctness). The `subscribe` race-retry branch in `DigestService` (and the symmetric one in `WatchlistService`) re-queried + upserted on the **same** `AsyncSession` after catching an `IntegrityError` from a losing concurrent INSERT, **without** first issuing `await session.rollback()`. A failed INSERT leaves the SQLAlchemy/asyncpg transaction in an aborted state, so the very next `.execute(...)` (the retry `find_by_*` SELECT) raises a transaction-aborted error (`PendingRollbackError` / asyncpg `InFailedSQLTransactionError`) instead of completing the intended idempotent collapse-to-single-row. The losing caller received a misleading 500 and the BUG-022 idempotency contract was broken under a real race.

## Root cause

In `tg_parser/services/digest_service.py` the tail of `subscribe()`:

```python
try:
    created = await self._subscription_repo.create(draft)
except IntegrityError:
    logger.info("digest.subscribe_race_retry_update", owner_id=owner_id, name=name)
    existing = await self._subscription_repo.find_by_owner_and_name(owner_id, name)  # ← runs on aborted txn
    ...
```

Both `find_by_owner_and_name` (SELECT) and `_apply_digest_upsert` (UPDATE) share the session that `create()` just poisoned with the failed flush. SQLAlchemy guards an aborted transaction: any subsequent statement raises until `session.rollback()` is issued. The author intent (idempotent fall-through to UPDATE) was correct; the missing rollback made the retry unreachable. The SA repos expose `.session` (an `AsyncSession`), so the fix is a single `await ...session.rollback()` immediately after the race-retry log line and before the re-query.

## Before / after

Before (`digest_service.py`, and symmetric `watchlist_service.py`):

```python
        except IntegrityError:
            logger.info("digest.subscribe_race_retry_update", owner_id=owner_id, name=name)
            existing = await self._subscription_repo.find_by_owner_and_name(owner_id, name)
```

After:

```python
        except IntegrityError:
            logger.info("digest.subscribe_race_retry_update", owner_id=owner_id, name=name)
            # The failed INSERT leaves the AsyncSession in an aborted-transaction
            # state; without this rollback the subsequent SELECT/UPDATE raise
            # PendingRollbackError and the idempotent-upsert retry can never run
            # (BUG-029).
            await self._subscription_repo.session.rollback()
            existing = await self._subscription_repo.find_by_owner_and_name(owner_id, name)
```

## Scope decision: digest + watchlist (both in this PR)

`WatchlistService.subscribe` has a **structurally identical** `except IntegrityError:` race-retry block (`find_by_user_and_title` + `_apply_upsert` on the same session) and its SA repo (`SAWatchInterestRepo`) likewise exposes `.session`. Because the two bugs are the same shape on tightly-coupled sibling services (both Wave 1 step 3 BUG-022 subscribe-idempotency paths), both are fixed here rather than filing a follow-up. The fix is one line per service. No separate follow-up note needed.

## Test plan

New regression file `tests/test_digest_subscribe_race.py` (7 tests, `TEST_POSTGRES=1`-gated). These **require a real PostgreSQL session** — the in-memory fakes in `tests/test_subscribe_idempotency.py` cannot reproduce the aborted-transaction guard (no real flush), so they pass even on buggy code. Determinism does NOT rely on wall-clock timing:

- **Deterministic single-session reproduction** (`_RaceInjecting*Repo`) — injects the concurrent-winner row through an independent committed session in the exact window between `subscribe()`'s pre-check `find_by_*` (sees no row) and the real INSERT, forcing the `IntegrityError`. Asserts: retry collapses to `created=False`, returns the winner row, **and the same session is still usable afterward** (the core regression — proves rollback restored it), single row in DB.
- **Deterministic update-not-duplicate** — winner row differs from caller payload → retry path performs a real UPDATE (`changed_fields` populated), still one row.
- **Concurrent `asyncio.gather`** — N=4 callers, each own session, gated by an `asyncio.Barrier` (not `sleep`) so all N race the INSERT simultaneously → exactly one create-winner, N-1 deterministically hit the rollback-retry; no transaction-abort error leaks; single row.
- **Single-call baseline** — plain subscribe still creates exactly one row.
- Symmetric digest + watchlist coverage; synthetic owner/chat IDs only (no real `chat_id=5445781511` / `digest_94483db9`).

Self-review-and-rerun loop (operator-mandated + `TEST_POSTGRES=1`):

- [x] Initial green run on the new file under `TEST_POSTGRES=1` (7/7 passed).
- [x] **Stash-proof:** `git stash push -- tg_parser/services/digest_service.py tg_parser/services/watchlist_service.py` and reran on pre-fix `main@ce020ce` shape → **5 failed, 2 passed**: all four deterministic race tests + both concurrent tests fail with `InFailedSQLTransactionError`/`PendingRollbackError` ("current transaction is aborted"); the two no-race baselines correctly stay green. Restored fix (re-applied directly to avoid a stash-stack race with a concurrent worktree agent) → 7/7 green again.
- [x] **Self-review gap found + fixed:** the first draft used a plain `asyncio.gather` for the concurrent tests; pre-fix it was **non-deterministic** (digest concurrent test passed pre-fix one run because the winner committed before the losers' pre-check). Replaced with an `asyncio.Barrier(N)` injected at the INSERT boundary so the IntegrityError window is forced for N-1 callers every run; both concurrent tests now fail deterministically pre-fix. Assertions also check specifically for `PendingRollbackError` absence.
- [x] **Full normal-mode rerun:** `pytest tests/test_digest_subscribe_race.py tests/test_subscribe_*.py tests/test_bot_*.py tests/test_f6_scheduled_digests.py` → **549 passed, 30 skipped** (Postgres-gated + 1 documented confirm-flow concurrency skip).
- [x] **MANDATORY `TEST_POSTGRES=1` rerun:** `TEST_POSTGRES=1 pytest tests/test_digest_subscribe_race.py tests/test_f6_scheduled_digests.py tests/test_f11_mcp_tools.py tests/test_subscribe_*.py tests/test_api_digests.py tests/test_bot_*.py tests/test_f4b_*.py tests/test_watchlist_service.py` → **829 passed, 1 skipped** (documented confirm-flow concurrency skip), 0 failures. Log: `/tmp/bug029_postgres_verify.log`.
- [x] In-memory fakes (`_FakeDigestSubscriptionRepo`, `_FakeInterestRepo`) gained a `.session` stub with a no-op `rollback()` so the existing BUG-022 race tests keep exercising the retry branch against the new code.
- [x] `ruff check` + `ruff format --check` clean on all modified files.

## References

- [`docs/notes/BUG_LOG.md` § BUG-029](BUG_LOG.md)
- [`docs/notes/SKIPPED_TESTS_AUDIT_2026-05-25.md`](SKIPPED_TESTS_AUDIT_2026-05-25.md) — mandatory `TEST_POSTGRES=1` rerun standard for all PRs.
- Related: BUG-022 (subscribe-idempotency contract this bug broke under race), BUG-013 (`AsyncSession`-lifecycle family), ADR 0008 (polymorphic subscription target).
- Recent merges for context: `e50449b`, `6ebad33`, `66e8297`, `af7790f`, housekeeping `ce020ce`.

## Operator action required

- **DO NOT MERGE** without sign-off (per `AGENTS.md`).
- Pure-code fix, no new dependencies, no `pyproject.toml` / `requirements.txt` changes.
