"""BUG-070 regression tests: Telethon session "database is locked" fix.

Two independent defenses are covered:

1. Part 1 — in-process serialization: a process-wide ``asyncio.Lock`` wraps the
   whole Telethon client lifetime in ``run_ingestion`` (connect -> use ->
   disconnect), so two concurrent sources can never be inside the session
   critical-section at the same time, and the lock is released even when a
   source raises.

2. Part 2 — WAL + busy_timeout: the Telethon ``SQLiteSession`` subclass applies
   ``PRAGMA journal_mode=WAL`` and a configurable ``PRAGMA busy_timeout`` to its
   connection, and the ``telegram_session_busy_timeout_ms`` setting is threaded
   from ``Settings`` through ``TelethonClient.connect()``.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

import tg_parser.ingestion.telegram.telethon_client as telethon_client
from tg_parser.config.settings import Settings
from tg_parser.ingestion.telegram import TelethonClient
from tg_parser.ingestion.telegram.telethon_client import (
    SessionLockContentionError,
    _WALSQLiteSession,
    telethon_session_lock,
    telethon_session_lock_guard,
)
from tg_parser.services.ingestion_service import run_ingestion


@pytest.fixture(autouse=True)
def _reset_session_lock():
    """M3 (BUG-070): rebind the module-level session lock per test.

    ``telethon_client._SESSION_LOCK`` is created at import and an
    ``asyncio.Lock`` binds to the FIRST event loop it is awaited on. Under
    pytest-asyncio's function-scoped event loops, a lock first contended in one
    test would raise ``RuntimeError: ... bound to a different event loop`` in a
    later test. Resetting it to a fresh ``asyncio.Lock()`` around every test
    keeps each test's loop self-contained. ``telethon_session_lock()`` /
    ``telethon_session_lock_guard`` read the module global at call time, so the
    rebind is picked up everywhere.
    """
    telethon_client._SESSION_LOCK = asyncio.Lock()
    yield
    telethon_client._SESSION_LOCK = asyncio.Lock()


# ---------------------------------------------------------------------------
# Part 1 — in-process lock serializes Telethon session access
# ---------------------------------------------------------------------------


def _make_fake_client_factory():
    """Factory for a TelethonClient stand-in with async connect/disconnect."""

    def _factory(*_args, **_kwargs):
        client = Mock()
        client.connect = AsyncMock()
        client.disconnect = AsyncMock()
        return client

    return _factory


@pytest.mark.asyncio
async def test_ingestion_serializes_concurrent_session_access():
    """Two concurrent run_ingestion calls never overlap the critical section."""
    lock = telethon_session_lock()
    assert not lock.locked()

    state = {"active": 0, "max_active": 0}

    async def fake_ingest(**_kwargs):
        # Inside the lock-protected section. Record peak concurrency.
        state["active"] += 1
        state["max_active"] = max(state["max_active"], state["active"])
        # Yield control so a sibling task would run here if not serialized.
        await asyncio.sleep(0.05)
        state["active"] -= 1
        return {
            "posts_collected": 0,
            "comments_collected": 0,
            "duration_seconds": 0.0,
        }

    def make_orchestrator(*_args, **_kwargs):
        orch = Mock()
        orch.ingest_source = AsyncMock(side_effect=fake_ingest)
        return orch

    with (
        patch(
            "tg_parser.services.ingestion_service.TelethonClient",
            side_effect=_make_fake_client_factory(),
        ),
        patch(
            "tg_parser.services.ingestion_service.IngestionOrchestrator",
            side_effect=make_orchestrator,
        ),
    ):
        await asyncio.gather(
            run_ingestion("source-a", state_repo=Mock(), raw_repo=Mock()),
            run_ingestion("source-b", state_repo=Mock(), raw_repo=Mock()),
        )

    # If the lock were absent, both tasks would enter concurrently -> 2.
    assert state["max_active"] == 1
    assert not lock.locked()


@pytest.mark.asyncio
async def test_session_lock_released_on_exception():
    """A source raising inside the critical section still releases the lock."""
    lock = telethon_session_lock()
    assert not lock.locked()

    def make_failing_client(*_args, **_kwargs):
        client = Mock()
        # connect() raising mirrors the real "database is locked" collision.
        client.connect = AsyncMock(side_effect=RuntimeError("database is locked"))
        client.disconnect = AsyncMock()
        return client

    with patch(
        "tg_parser.services.ingestion_service.TelethonClient",
        side_effect=make_failing_client,
    ):
        with pytest.raises(RuntimeError, match="database is locked"):
            await run_ingestion("source-x", state_repo=Mock(), raw_repo=Mock())

    # Lock must be free again — otherwise every later tick would deadlock.
    assert not lock.locked()

    # And a subsequent ingestion can still acquire it.
    async with telethon_session_lock():
        assert telethon_session_lock().locked()
    assert not telethon_session_lock().locked()


# ---------------------------------------------------------------------------
# Part 2 — WAL + busy_timeout PRAGMAs on the Telethon session connection
# ---------------------------------------------------------------------------


def test_wal_session_applies_pragmas(tmp_path):
    """_WALSQLiteSession sets journal_mode=WAL and the configured busy_timeout."""
    session_path = str(tmp_path / "session_wal")
    session = _WALSQLiteSession(session_path, busy_timeout_ms=4321)
    try:
        cursor = session._cursor()
        journal_mode = cursor.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = cursor.execute("PRAGMA busy_timeout").fetchone()[0]
        cursor.close()

        assert journal_mode.lower() == "wal"
        assert busy_timeout == 4321
    finally:
        session.close()


def test_wal_session_reapplies_busy_timeout_after_reopen(tmp_path):
    """busy_timeout (per-connection) is re-applied when the connection reopens."""
    session_path = str(tmp_path / "session_reopen")
    session = _WALSQLiteSession(session_path, busy_timeout_ms=2500)
    try:
        first = session._cursor()
        first.close()
        session.close()  # drops the underlying connection

        # Next _cursor() opens a fresh connection; PRAGMAs must be re-applied.
        cursor = session._cursor()
        assert cursor.execute("PRAGMA busy_timeout").fetchone()[0] == 2500
        assert cursor.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        cursor.close()
    finally:
        session.close()


@pytest.mark.asyncio
async def test_connect_builds_wal_session_from_setting(tmp_path):
    """TelethonClient.connect threads telegram_session_busy_timeout_ms through."""
    settings = Settings(
        telegram_api_id=12345,
        telegram_api_hash="test_hash",
        telegram_phone="+1234567890",
        telegram_session_name=str(tmp_path / "client_session"),
        telegram_session_busy_timeout_ms=7777,
    )
    client = TelethonClient(settings)

    captured: dict = {}

    def fake_tg_client(session=None, api_id=None, api_hash=None):
        captured["session"] = session
        fake = Mock()
        fake.start = AsyncMock()
        return fake

    with patch(
        "tg_parser.ingestion.telegram.telethon_client.TelethonTelegramClient",
        side_effect=fake_tg_client,
    ):
        await client.connect()

    session = captured["session"]
    assert isinstance(session, _WALSQLiteSession)
    assert session._busy_timeout_ms == 7777

    # The configured timeout reaches the actual sqlite connection.
    cursor = session._cursor()
    try:
        assert cursor.execute("PRAGMA busy_timeout").fetchone()[0] == 7777
        assert cursor.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        cursor.close()
        session.close()


def test_busy_timeout_setting_default_and_override(monkeypatch):
    """The new setting defaults to 5000ms and is overridable via env."""
    assert Settings().telegram_session_busy_timeout_ms == 5000

    monkeypatch.setenv("TELEGRAM_SESSION_BUSY_TIMEOUT_MS", "1234")
    assert Settings().telegram_session_busy_timeout_ms == 1234


def test_busy_timeout_setting_rejects_zero(monkeypatch):
    """N2 (BUG-070): gt=0 — 0ms (instant-fail / pre-fix bug) is not configurable."""
    from pydantic import ValidationError

    monkeypatch.setenv("TELEGRAM_SESSION_BUSY_TIMEOUT_MS", "0")
    with pytest.raises(ValidationError):
        Settings()


# ---------------------------------------------------------------------------
# H1 — bounded lock-wait: SessionLockContentionError instead of pipeline_timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_lock_guard_raises_contention_on_wait_timeout():
    """telethon_session_lock_guard raises SessionLockContentionError when the
    wait budget elapses while a sibling holds the lock — and the holder keeps
    the lock (the waiter never acquired it)."""
    lock = telethon_session_lock()

    async with telethon_session_lock_guard(1.0):  # holder
        assert lock.locked()
        with pytest.raises(SessionLockContentionError):
            async with telethon_session_lock_guard(0.05):
                pytest.fail("waiter must not enter the critical section")
        # The holder still owns the lock; the failed waiter did not steal it.
        assert lock.locked()

    assert not lock.locked()


@pytest.mark.asyncio
async def test_session_lock_guard_acquires_when_free():
    """With no contention the guard acquires immediately and releases on exit."""
    lock = telethon_session_lock()
    assert not lock.locked()
    async with telethon_session_lock_guard(1.0):
        assert lock.locked()
    assert not lock.locked()


@pytest.mark.asyncio
async def test_run_ingestion_raises_contention_when_session_busy(monkeypatch):
    """run_ingestion aborts with SessionLockContentionError (never connecting)
    when the session lock cannot be acquired within the configured budget."""
    import tg_parser.services.ingestion_service as ing

    monkeypatch.setattr(ing.settings, "scheduler_session_lock_wait_timeout_s", 0.05)

    connect_called = {"value": False}

    def make_client(*_args, **_kwargs):
        client = Mock()

        async def _connect():
            connect_called["value"] = True

        client.connect = AsyncMock(side_effect=_connect)
        client.disconnect = AsyncMock()
        return client

    lock = telethon_session_lock()
    async with telethon_session_lock_guard(1.0):  # session is busy
        with patch(
            "tg_parser.services.ingestion_service.TelethonClient",
            side_effect=make_client,
        ):
            with pytest.raises(SessionLockContentionError):
                await run_ingestion("busy-source", state_repo=Mock(), raw_repo=Mock())

    # Contention aborted BEFORE connect() — no Telethon session was opened.
    assert connect_called["value"] is False
    assert not lock.locked()


# ---------------------------------------------------------------------------
# M2 — cancellation release + processing not serialized by the session lock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_lock_released_on_cancellation():
    """M2(a): cancelling a run_ingestion task while it holds the session lock
    still releases the lock (async with guarantees the finally release runs)."""
    lock = telethon_session_lock()
    assert not lock.locked()

    entered = asyncio.Event()

    async def fake_ingest(**_kwargs):
        entered.set()
        # Block inside the lock-protected critical section until cancelled.
        await asyncio.sleep(3600)
        return {"posts_collected": 0, "comments_collected": 0, "duration_seconds": 0.0}

    def make_orchestrator(*_args, **_kwargs):
        orch = Mock()
        orch.ingest_source = AsyncMock(side_effect=fake_ingest)
        return orch

    with (
        patch(
            "tg_parser.services.ingestion_service.TelethonClient",
            side_effect=_make_fake_client_factory(),
        ),
        patch(
            "tg_parser.services.ingestion_service.IngestionOrchestrator",
            side_effect=make_orchestrator,
        ),
    ):
        task = asyncio.create_task(
            run_ingestion("source-cancel", state_repo=Mock(), raw_repo=Mock())
        )
        await asyncio.wait_for(entered.wait(), timeout=2.0)
        assert lock.locked(), "lock must be held while inside the critical section"

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    # The cancelled task must not leave the lock held — otherwise every later
    # tick would deadlock.
    assert not lock.locked()


@pytest.mark.asyncio
async def test_processing_runs_in_parallel_while_session_lock_held():
    """M2(b): the session lock serializes ONLY ingestion. A processing-stage
    coroutine makes progress while ingestion holds the lock (the lock is
    acquired and released entirely within run_ingestion)."""
    lock = telethon_session_lock()
    order: list[str] = []
    release_holder = asyncio.Event()

    async def holder_ingest(**_kwargs):
        order.append("ingest_enter")
        await release_holder.wait()  # keep the session lock held
        order.append("ingest_exit")
        return {"posts_collected": 0, "comments_collected": 0, "duration_seconds": 0.0}

    def make_orchestrator(*_args, **_kwargs):
        orch = Mock()
        orch.ingest_source = AsyncMock(side_effect=holder_ingest)
        return orch

    async def processing_stage():
        # Stand-in for run_processing / run_topicization — an LLM-bound stage
        # that does NOT touch the session lock, so it must not be gated by it.
        order.append("process_done")
        return {"processed_count": 1}

    with (
        patch(
            "tg_parser.services.ingestion_service.TelethonClient",
            side_effect=_make_fake_client_factory(),
        ),
        patch(
            "tg_parser.services.ingestion_service.IngestionOrchestrator",
            side_effect=make_orchestrator,
        ),
    ):
        holder = asyncio.create_task(run_ingestion("holder", state_repo=Mock(), raw_repo=Mock()))
        for _ in range(200):
            if lock.locked():
                break
            await asyncio.sleep(0.005)
        assert lock.locked(), "ingestion should hold the session lock"

        # Processing completes while ingestion still holds the lock.
        result = await asyncio.wait_for(processing_stage(), timeout=1.0)
        assert result["processed_count"] == 1
        assert "process_done" in order
        assert "ingest_exit" not in order, "ingestion must still be holding the lock"

        release_holder.set()
        await holder

    assert not lock.locked()


def test_processing_topicization_modules_do_not_import_session_lock():
    """M2(b) structural guard: the processing/topicization services never import
    the session-lock symbols — only ingestion serializes on the session."""
    import tg_parser.services.processing_service as processing_service
    import tg_parser.services.topicization_service as topicization_service

    for module in (processing_service, topicization_service):
        assert not hasattr(module, "telethon_session_lock")
        assert not hasattr(module, "telethon_session_lock_guard")
        assert not hasattr(module, "_SESSION_LOCK")
