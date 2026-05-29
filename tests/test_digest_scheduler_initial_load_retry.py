"""BUG-030 regression — hand-rolled retry for the digest scheduler initial load.

Covers ``tg_parser/bot/main.py``:

* ``_load_active_subscriptions_with_retry`` — the new bounded, hand-rolled retry
  helper (NOT tenacity; mirrors ``anthropic_client.py`` / ``webhooks.py``).
* ``_start_digest_scheduler`` — the caller-side contract: transient exhaustion
  falls back to an empty job-set (preserving 60s reconcile self-healing) while
  schema-shape errors fail loud instead of being silently swallowed.

All ``asyncio.sleep`` calls are patched so the suite is fast + deterministic.

Per PR #111's self-review lesson (``caplog`` is flaky with structlog) the
CRITICAL-log assertion uses ``patch.object(logger, "critical")`` capturing the
call args rather than ``caplog``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import (
    DatabaseError,
    InterfaceError,
    OperationalError,
    ProgrammingError,
)

from tg_parser.bot import main as bot_main

# NB: the BUG-030 symbols (``_load_active_subscriptions_with_retry`` and the
# ``_INITIAL_LOAD_*`` constants) are referenced via the ``bot_main`` module
# object rather than imported by name. This keeps the module importable against
# *pre-fix* code so the stash-proof exercises real behavioral failures (the
# caller-level tests run and demonstrate the silent-swallow bug) instead of a
# blanket collection ImportError.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _op_error(msg: str = "the database system is starting up") -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception(msg))


def _interface_error(msg: str = "connection already closed") -> InterfaceError:
    return InterfaceError("SELECT 1", {}, Exception(msg))


def _programming_error(msg: str = 'column "target_kind" does not exist') -> ProgrammingError:
    return ProgrammingError("SELECT 1", {}, Exception(msg))


def _database_error(msg: str = "generic database error") -> DatabaseError:
    return DatabaseError("SELECT 1", {}, Exception(msg))


def _repo_factory(list_active_mock: AsyncMock) -> Any:
    """Return a ``repo_cm_factory`` yielding a repo whose ``list_active`` is
    ``list_active_mock``. A fresh context manager is produced per call (mirrors
    the real per-attempt ``async with digest_subscription_repo()``), while the
    same mock is reused so ``side_effect`` sequences persist across attempts.
    """

    @asynccontextmanager
    async def _cm() -> Any:
        repo = MagicMock()
        repo.list_active = list_active_mock
        yield (repo, MagicMock())

    return _cm


def _make_subscription(sub_id: str = "sub-1") -> MagicMock:
    sub = MagicMock()
    sub.id = sub_id
    return sub


# ---------------------------------------------------------------------------
# Helper-level tests — _load_active_subscriptions_with_retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_no_retry_no_sleep() -> None:
    """First attempt succeeds → no retry, no sleep, subscriptions returned."""
    subs = [_make_subscription("sub-a"), _make_subscription("sub-b")]
    list_active = AsyncMock(return_value=subs)

    with patch.object(bot_main.asyncio, "sleep", new=AsyncMock()) as sleep_mock:
        result = await bot_main._load_active_subscriptions_with_retry(_repo_factory(list_active))

    assert result == subs
    assert list_active.await_count == 1
    sleep_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_transient_operational_error_then_success() -> None:
    """Two transient OperationalErrors then success → loop retries to attempt 3."""
    subs = [_make_subscription("sub-a")]
    list_active = AsyncMock(side_effect=[_op_error(), _op_error(), subs])

    with patch.object(bot_main.asyncio, "sleep", new=AsyncMock()) as sleep_mock:
        result = await bot_main._load_active_subscriptions_with_retry(_repo_factory(list_active))

    assert result == subs
    assert result  # non-empty
    assert list_active.await_count == 3
    # Two backoffs before attempts 2 and 3.
    assert [c.args[0] for c in sleep_mock.await_args_list] == [
        bot_main._INITIAL_LOAD_BACKOFF_SCHEDULE[0],
        bot_main._INITIAL_LOAD_BACKOFF_SCHEDULE[1],
    ]


@pytest.mark.asyncio
async def test_transient_interface_error_is_retried() -> None:
    """InterfaceError is also treated as transient and retried."""
    subs = [_make_subscription("sub-a")]
    list_active = AsyncMock(side_effect=[_interface_error(), subs])

    with patch.object(bot_main.asyncio, "sleep", new=AsyncMock()) as sleep_mock:
        result = await bot_main._load_active_subscriptions_with_retry(_repo_factory(list_active))

    assert result == subs
    assert list_active.await_count == 2
    assert sleep_mock.await_count == 1


@pytest.mark.asyncio
async def test_exhaustion_logs_critical_and_reraises() -> None:
    """Always-transient → exhausts retries, logs CRITICAL, re-raises."""
    list_active = AsyncMock(side_effect=_op_error())

    with (
        patch.object(bot_main.asyncio, "sleep", new=AsyncMock()) as sleep_mock,
        patch.object(bot_main.logger, "critical") as critical_mock,
    ):
        with pytest.raises(OperationalError):
            await bot_main._load_active_subscriptions_with_retry(_repo_factory(list_active))

    assert list_active.await_count == bot_main._INITIAL_LOAD_MAX_ATTEMPTS
    # One sleep before each retry (attempts 2..5) = N-1 sleeps.
    assert sleep_mock.await_count == bot_main._INITIAL_LOAD_MAX_ATTEMPTS - 1
    critical_mock.assert_called_once()
    assert critical_mock.call_args.args[0] == "digest_scheduler_initial_load_exhausted_retries"


@pytest.mark.asyncio
async def test_backoff_schedule_is_escalating() -> None:
    """Exhaustion path uses the documented escalating backoff cadence."""
    list_active = AsyncMock(side_effect=_op_error())

    with (
        patch.object(bot_main.asyncio, "sleep", new=AsyncMock()) as sleep_mock,
        patch.object(bot_main.logger, "critical"),
    ):
        with pytest.raises(OperationalError):
            await bot_main._load_active_subscriptions_with_retry(_repo_factory(list_active))

    observed = [c.args[0] for c in sleep_mock.await_args_list]
    assert observed == list(bot_main._INITIAL_LOAD_BACKOFF_SCHEDULE)
    # Strictly increasing — proves exponential-ish escalation, not a flat delay.
    assert all(b < a for b, a in zip(observed, observed[1:], strict=False))


@pytest.mark.asyncio
async def test_non_transient_programming_error_not_retried() -> None:
    """Schema-shape error fails loud: NOT retried, NOT swallowed, no CRITICAL."""
    list_active = AsyncMock(side_effect=_programming_error())

    with (
        patch.object(bot_main.asyncio, "sleep", new=AsyncMock()) as sleep_mock,
        patch.object(bot_main.logger, "critical") as critical_mock,
    ):
        with pytest.raises(ProgrammingError):
            await bot_main._load_active_subscriptions_with_retry(_repo_factory(list_active))

    assert list_active.await_count == 1  # no retry
    sleep_mock.assert_not_awaited()
    critical_mock.assert_not_called()


@pytest.mark.asyncio
async def test_generic_database_error_not_retried() -> None:
    """Boundary: a bare ``DatabaseError`` (parent of OperationalError /
    ProgrammingError / IntegrityError, but NOT one of the two transient
    connection-level types) is NOT retried — only ``OperationalError`` /
    ``InterfaceError`` qualify as transient. It fails loud."""
    list_active = AsyncMock(side_effect=_database_error())

    with (
        patch.object(bot_main.asyncio, "sleep", new=AsyncMock()) as sleep_mock,
        patch.object(bot_main.logger, "critical") as critical_mock,
    ):
        with pytest.raises(DatabaseError):
            await bot_main._load_active_subscriptions_with_retry(_repo_factory(list_active))

    assert list_active.await_count == 1  # no retry
    sleep_mock.assert_not_awaited()
    critical_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Caller-level tests — _start_digest_scheduler contract
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _always_raises_cm(exc: BaseException) -> Any:
    repo = MagicMock()
    repo.list_active = AsyncMock(side_effect=exc)
    yield (repo, MagicMock())


def _patch_scheduler_deps() -> Any:
    """Patch the scheduler/registration deps imported inside
    ``_start_digest_scheduler`` so the function runs without real APScheduler /
    DB side effects. Returns the context-manager stack entries to use.
    """
    scheduler = MagicMock()
    scheduler.is_running = True  # avoid scheduler.start()
    return scheduler


@pytest.mark.asyncio
async def test_start_scheduler_falls_back_to_empty_on_exhausted_retries() -> None:
    """Transient exhaustion → CRITICAL logged + active=[] fallback (self-healing
    preserved) + scheduler still starts; no subscriptions registered."""
    scheduler = _patch_scheduler_deps()
    register = MagicMock()

    @asynccontextmanager
    async def _factory() -> Any:
        repo = MagicMock()
        repo.list_active = AsyncMock(side_effect=_op_error())
        yield (repo, MagicMock())

    with (
        patch.object(bot_main.asyncio, "sleep", new=AsyncMock()),
        patch.object(bot_main.logger, "critical") as critical_mock,
        patch("tg_parser.services.background_scheduler.get_scheduler", return_value=scheduler),
        patch(
            "tg_parser.services.background_scheduler.register_digest_subscription",
            register,
        ),
        patch("tg_parser.services.db_context.digest_subscription_repo", _factory),
    ):
        returned_scheduler, task = await bot_main._start_digest_scheduler()
        if task is not None:
            task.cancel()

    assert returned_scheduler is scheduler
    register.assert_not_called()  # active was []
    critical_mock.assert_called_once()
    assert critical_mock.call_args.args[0] == "digest_scheduler_initial_load_exhausted_retries"


@pytest.mark.asyncio
async def test_start_scheduler_propagates_non_transient_error() -> None:
    """Schema-shape error (ProgrammingError) propagates out of the scheduler
    bootstrap — fails loud, NOT swallowed to active=[]."""
    scheduler = _patch_scheduler_deps()

    @asynccontextmanager
    async def _factory() -> Any:
        repo = MagicMock()
        repo.list_active = AsyncMock(side_effect=_programming_error())
        yield (repo, MagicMock())

    with (
        patch.object(bot_main.asyncio, "sleep", new=AsyncMock()),
        patch("tg_parser.services.background_scheduler.get_scheduler", return_value=scheduler),
        patch("tg_parser.services.db_context.digest_subscription_repo", _factory),
    ):
        with pytest.raises(ProgrammingError):
            await bot_main._start_digest_scheduler()


@pytest.mark.asyncio
async def test_start_scheduler_registers_active_subscriptions_happy_path() -> None:
    """Happy path: subscriptions loaded first try → each is registered."""
    scheduler = _patch_scheduler_deps()
    register = MagicMock()
    subs = [_make_subscription("sub-a"), _make_subscription("sub-b")]

    @asynccontextmanager
    async def _factory() -> Any:
        repo = MagicMock()
        repo.list_active = AsyncMock(return_value=subs)
        yield (repo, MagicMock())

    with (
        patch.object(bot_main.asyncio, "sleep", new=AsyncMock()) as sleep_mock,
        patch("tg_parser.services.background_scheduler.get_scheduler", return_value=scheduler),
        patch(
            "tg_parser.services.background_scheduler.register_digest_subscription",
            register,
        ),
        patch("tg_parser.services.db_context.digest_subscription_repo", _factory),
    ):
        _returned_scheduler, task = await bot_main._start_digest_scheduler()
        if task is not None:
            task.cancel()

    assert register.call_count == 2
    sleep_mock.assert_not_awaited()
