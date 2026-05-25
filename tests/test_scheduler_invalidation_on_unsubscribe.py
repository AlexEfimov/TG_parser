"""BUG-035 regression suite — synchronous scheduler invalidation on unsubscribe.

Background
==========

Empirical observation (Wave 1 step 4 VPS watch session, 2026-05-24 ~21:00 UTC):

    operator → MCP unsubscribe_digest(...) at ~20:58Z (DB row hard-deleted) →
    APScheduler in-memory job still armed inside the bot process →
    21:00 cron tick fired → one stray digest delivered

The handoff (`docs/notes/HANDOFF_NEXT_CHAT_WAVE1_STEP4_POST_WATCH_2026-05-25.md`
§ 3.1, lines 122-133) prescribed a synchronous ``scheduler.remove_job`` call
inside ``unsubscribe_digest`` so the very next cron tick is bounded to a no-op
instead of relying solely on the 60-second reconcile loop.

This file covers four layers:

A. **Unit-level scheduler hardening** — :meth:`BackgroundScheduler.remove_task`
   must now always attempt ``scheduler.remove_job`` (even when the in-memory
   ``_tasks`` dict has gone stale), specifically catch
   :class:`apscheduler.jobstores.base.JobLookupError` for the "already gone"
   race with the reconcile loop, and emit a structured ``scheduler_job_removed``
   log event with a ``reason`` tag for telemetry. Other exceptions still
   propagate so schema/network issues fail loud.

B. **End-to-end MCP / bot unsubscribe contract** — both the MCP tool
   :func:`tg_parser.mcp_server.unsubscribe_digest` and the bot tool
   :func:`tg_parser.bot.tools._exec_unsubscribe_digest` must remove the
   APScheduler job *synchronously* before returning success to the caller.

C. **Anti-regression for existing safeguards** — :func:`run_scheduled_digests_task`
   already re-reads the subscription from the DB at tick time and bails with
   ``status="not_found"`` if the row is gone (the immediate cross-process
   safeguard); :func:`reconcile_digest_subscriptions` already detects and
   removes orphan scheduler jobs whose DB row was deleted out-of-band. Both
   must keep working alongside the new synchronous hook so cross-process
   MCP↔bot deployments and external (psql) deletes stay self-healing.

D. **Watchlist scope decision** — :func:`unsubscribe_watchlist` is *not*
   symmetric to ``unsubscribe_digest`` because the F11 matcher does not own a
   per-interest APScheduler job. Instead it queries
   :meth:`WatchInterestRepoPort.list_active_for_channel` at the start of every
   pipeline tick, which already filters on ``is_active = TRUE``. A
   soft-deleted interest therefore drops out of consideration on the very
   next tick — invalidation is by construction. Locked in here by a regression
   test so any future change that adds APScheduler-driven scheduling to
   watchlists will trip this guard and force a symmetric fix.

References
----------
- ``docs/notes/BUG_LOG.md`` § BUG-035
- ``docs/notes/HANDOFF_NEXT_CHAT_WAVE1_STEP4_POST_WATCH_2026-05-25.md`` § 3.1
- ``docs/notes/WATCH_WINDOW_WAVE1_STEP4_VPS_2026-05-24.md`` (Test C cleanup
  evidence)
- ``docs/notes/SKIPPED_TESTS_AUDIT_2026-05-25.md`` — ``TEST_POSTGRES=1`` rerun
  is now standard for every PR; the Postgres-gated tests below MUST exit
  green under that env.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apscheduler.jobstores.base import JobLookupError

from tg_parser.domain.models import (
    DigestFormat,
    DigestSubscription,
    NotifyMode,
    ProcessedDocument,
    WatchInterest,
)
from tg_parser.services.background_scheduler import (
    BackgroundScheduler,
    _digest_job_id,
    register_digest_subscription,
    unregister_digest_subscription,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_subscription(
    *,
    sub_id: str | None = None,
    owner_id: str = "00000000-0000-0000-0000-0000000000bb",
    chat_id: int = 999_001,
    name: str | None = None,
    channel_ids: list[str] | None = None,
    cron_expression: str = "0 9 * * *",
    timezone: str = "UTC",
    is_active: bool = True,
) -> DigestSubscription:
    return DigestSubscription(
        id=sub_id if sub_id is not None else str(uuid.uuid4()),
        owner_id=owner_id,
        chat_id=chat_id,
        name=name or f"bug035-sub-{uuid.uuid4().hex[:8]}",
        channel_ids=channel_ids or ["bug035_test_channel"],
        cron_expression=cron_expression,
        timezone=timezone,
        format=DigestFormat.SUMMARY,
        language="ru",
        is_active=is_active,
    )


def _make_current_user(user_id: str, *, name: str = "bug035-tester", role: str = "admin"):
    from tg_parser.auth.models import CurrentUser

    return CurrentUser(
        id=user_id,
        name=name,
        role=role,
        allowed_channel_ids=None if role == "admin" else set(),
        max_channels=999,
    )


def _make_interest(
    *,
    interest_id: str | None = None,
    user_id: str = "user-bug035",
    keywords: list[str] | None = None,
    channel_ids: list[str] | None = None,
    is_active: bool = True,
) -> WatchInterest:
    return WatchInterest(
        id=interest_id or f"int-bug035-{uuid.uuid4().hex[:8]}",
        user_id=user_id,
        chat_id=42,
        title="BUG-035 watchlist scope guard",
        description="Symmetric coverage probe — soft-delete must drop from matcher.",
        keywords=list(keywords or ["bug035_keyword"]),
        exclude_keywords=[],
        channel_ids=list(channel_ids or ["bug035_test_channel"]),
        threshold=0.5,
        notify_mode=NotifyMode.INSTANT,
        is_active=is_active,
        embedding=None,
    )


pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


# ===========================================================================
# Layer A — unit-level BackgroundScheduler.remove_task hardening
# ===========================================================================


class TestRemoveTaskHardening:
    """Cover the new ``remove_task`` contract introduced by the BUG-035 fix."""

    def test_remove_task_returns_false_when_nothing_to_remove(self):
        """No in-memory entry, no scheduler job → no-op + False."""
        sched = BackgroundScheduler()
        assert sched.remove_task("digest:never-existed") is False

    def test_remove_task_removes_apscheduler_job_when_dict_empty(self):
        """Cross-process simulation: another path seeded the APScheduler
        directly; this scheduler's ``_tasks`` dict was never populated.

        Pre-fix ``remove_task`` returned ``False`` immediately when
        ``task_id not in self._tasks``, leaving the APScheduler job armed.
        The hardened version must always attempt ``scheduler.remove_job``
        so a divergence between the in-memory bookkeeping dict and the
        scheduler's job store cannot cause an orphan tick.
        """
        sched = BackgroundScheduler()
        sub_id = "11111111-1111-1111-1111-111111111111"
        job_id = _digest_job_id(sub_id)

        sched._scheduler.add_job(
            func=lambda: None,
            trigger="cron",
            hour=0,
            id=job_id,
            replace_existing=True,
        )
        assert sched._scheduler.get_job(job_id) is not None
        assert job_id not in sched._tasks

        assert sched.remove_task(job_id, reason="cross_process_probe") is True
        assert sched._scheduler.get_job(job_id) is None

    def test_remove_task_removes_when_dict_only(self):
        """In-memory entry exists but scheduler doesn't have the job (e.g.
        scheduler was restarted) → ``remove_task`` still cleans the dict
        and reports True so the caller knows it did *something*."""
        sched = BackgroundScheduler()
        job_id = "digest:dict-only-1234"
        sched._tasks[job_id] = lambda: None
        assert sched._scheduler.get_job(job_id) is None

        assert sched.remove_task(job_id) is True
        assert job_id not in sched._tasks

    def test_remove_task_idempotent_double_call(self):
        sched = BackgroundScheduler()
        sub = _make_subscription(sub_id="22222222-2222-2222-2222-222222222222")
        register_digest_subscription(sub, sched)
        assert sched.remove_task(_digest_job_id(sub.id)) is True
        assert sched.remove_task(_digest_job_id(sub.id)) is False

    def test_remove_task_swallows_job_lookup_error_from_apscheduler(self):
        """The library raises ``JobLookupError`` if the job is gone before
        we ask for it (race with reconcile / sibling process). We must
        treat that as the idempotent path — no exception bubbles up."""
        sched = BackgroundScheduler()
        sched._scheduler = MagicMock()
        sched._scheduler.remove_job = MagicMock(side_effect=JobLookupError("missing"))

        result = sched.remove_task("digest:gone-already", reason="race_with_reconcile")
        assert result is False
        sched._scheduler.remove_job.assert_called_once_with("digest:gone-already")

    def test_remove_task_propagates_unexpected_exceptions(self):
        """Schema mismatch / network errors must fail loud, not be
        silently swallowed (operator-mandated invariant per handoff)."""
        sched = BackgroundScheduler()
        sched._scheduler = MagicMock()
        sched._scheduler.remove_job = MagicMock(side_effect=RuntimeError("db gone"))

        with pytest.raises(RuntimeError, match="db gone"):
            sched.remove_task("digest:explode")

    def test_remove_task_emits_structured_reason_in_log(self, caplog):
        """Operator visibility: ``reason`` is forwarded to the log event."""
        sched = BackgroundScheduler()
        sub = _make_subscription(sub_id="33333333-3333-3333-3333-333333333333")
        register_digest_subscription(sub, sched)

        import logging

        with caplog.at_level(logging.INFO):
            sched.remove_task(_digest_job_id(sub.id), reason="mcp_unsubscribe_digest")

        joined = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "scheduler_job_removed" in joined
        assert "mcp_unsubscribe_digest" in joined


class TestUnregisterDigestSubscription:
    """Cover the public helper used by both MCP and bot tools."""

    def test_unregister_passes_reason_to_remove_task(self):
        sched = BackgroundScheduler()
        sub = _make_subscription(sub_id="44444444-4444-4444-4444-444444444444")
        register_digest_subscription(sub, sched)

        # Capture by patching the bound method on this scheduler instance.
        with patch.object(sched, "remove_task", wraps=sched.remove_task) as spy:
            unregister_digest_subscription(sub.id, sched, reason="bot_unsubscribe_digest")
            spy.assert_called_once_with(_digest_job_id(sub.id), reason="bot_unsubscribe_digest")

    def test_unregister_idempotent_returns_false_on_second_call(self):
        sched = BackgroundScheduler()
        sub = _make_subscription(sub_id="55555555-5555-5555-5555-555555555555")
        register_digest_subscription(sub, sched)
        assert unregister_digest_subscription(sub.id, sched) is True
        assert unregister_digest_subscription(sub.id, sched) is False

    def test_unregister_default_reason_is_unsubscribe(self):
        """Backward-compatible: existing callers without ``reason=`` still
        get a sensible tag in the log."""
        sched = BackgroundScheduler()
        sub = _make_subscription(sub_id="66666666-6666-6666-6666-666666666666")
        register_digest_subscription(sub, sched)
        with patch.object(sched, "remove_task", wraps=sched.remove_task) as spy:
            unregister_digest_subscription(sub.id, sched)
            spy.assert_called_once_with(_digest_job_id(sub.id), reason="unsubscribe")


# ===========================================================================
# Layer B — end-to-end MCP / bot unsubscribe contract
# ===========================================================================


@pg_only
class TestMcpUnsubscribeDigestSynchronous:
    """The MCP tool must invalidate the in-process scheduler job before
    returning success — no reliance on the reconcile loop in the same
    process."""

    async def test_mcp_unsubscribe_digest_removes_scheduler_job_atomically(self, _digest_db):
        from tg_parser.mcp_server import unsubscribe_digest
        from tg_parser.services.background_scheduler import (
            get_registered_digest_subscription_ids,
            get_scheduler,
        )
        from tg_parser.services.db_context import digest_subscription_repo
        from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo

        session = _digest_db.ingestion_state_session()
        try:
            user_repo = SAUserRepo(session)
            owner = await user_repo.create_user("alice_bug035_mcp")
        finally:
            await session.close()

        sub = _make_subscription(owner_id=owner.id, chat_id=987_001)
        async with digest_subscription_repo() as (repo, _db):
            await repo.create(sub)

        # NOTE: Do NOT call ``scheduler.start()`` in tests — AsyncIOScheduler
        # binds to the running event loop on start, but pytest-asyncio
        # creates a fresh loop per test, so the second test would crash
        # with "Event loop is closed" on the next ``add_job``. APScheduler
        # registers jobs into ``_pending_jobs`` while in ``STATE_STOPPED``
        # so the invariants we want to check (presence/absence in the
        # job store + in-memory ``_tasks`` dict) work without ``start()``.
        scheduler = get_scheduler()
        register_digest_subscription(sub, scheduler)

        # Capture the structured ``scheduler_job_removed`` event directly
        # via the module's structlog binding rather than ``caplog`` —
        # pytest-asyncio + structlog stdlib routing has a known
        # test-order-dependent caplog issue that swallows records when
        # ``test_db`` is the first session-scoped DB-dependent fixture
        # acquired inside a caplog context.  Direct logger patching is
        # both more deterministic and more explicit about the contract
        # under test: the new ``reason`` kwarg must reach the log site.
        # Wrap the structlog binding so we can introspect both the event
        # name and the kwargs. Pre-fix code emits a positional
        # ``logger.info("Removed task %s", task_id)`` call which is
        # captured here as ``(args=("Removed task %s", "digest:..."),
        # kwargs={})`` — no ``scheduler_job_removed`` event, no
        # ``reason`` kwarg, so the contract assertions below trip
        # cleanly without a TypeError.
        captured: list[tuple[tuple, dict]] = []
        from tg_parser.services import background_scheduler as bs_module

        original_info = bs_module.logger.info

        def _capture_info(*args, **kwargs):
            captured.append((args, kwargs))
            return original_info(*args, **kwargs)

        try:
            assert sub.id in get_registered_digest_subscription_ids()

            current_user = _make_current_user(owner.id, name=owner.name)
            with (
                patch.object(bs_module.logger, "info", side_effect=_capture_info),
                patch(
                    "tg_parser.mcp_server.resolve_mcp_user",
                    AsyncMock(return_value=current_user),
                ),
            ):
                result = await unsubscribe_digest(subscription_id=sub.id)

            assert result.success is True
            assert sub.id not in get_registered_digest_subscription_ids(), (
                "MCP unsubscribe_digest must invalidate the in-process scheduler "
                "job synchronously; the reconcile loop is defense-in-depth only."
            )

            removed_events = [
                kwargs
                for args, kwargs in captured
                if len(args) >= 1 and args[0] == "scheduler_job_removed"
            ]
            assert len(removed_events) >= 1, (
                "Post-fix MCP unsubscribe_digest must emit the structured "
                "'scheduler_job_removed' event so operators can correlate "
                "the scheduler invalidation with the originating MCP call. "
                f"Got captured calls: {captured!r}"
            )
            assert removed_events[-1].get("reason") == "mcp_unsubscribe_digest", (
                "Post-fix MCP unsubscribe_digest must pass reason="
                "'mcp_unsubscribe_digest' through to remove_task so Grafana / "
                "Loki dashboards can distinguish MCP-driven invalidations "
                "from bot-tool / reconcile-loop / API-route invalidations. "
                f"Got: {removed_events[-1]!r}"
            )
            assert removed_events[-1].get("task_id") == _digest_job_id(sub.id)
        finally:
            unregister_digest_subscription(sub.id, scheduler)

    async def test_mcp_unsubscribe_digest_is_idempotent(self, _digest_db):
        """Second unsubscribe must not raise (handles race with reconcile
        loop / parallel operator clicks)."""
        from tg_parser.mcp_server import unsubscribe_digest
        from tg_parser.services.db_context import digest_subscription_repo
        from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo

        session = _digest_db.ingestion_state_session()
        try:
            user_repo = SAUserRepo(session)
            owner = await user_repo.create_user("alice_bug035_idem")
        finally:
            await session.close()

        sub = _make_subscription(owner_id=owner.id, chat_id=987_002)
        async with digest_subscription_repo() as (repo, _db):
            await repo.create(sub)

        from tg_parser.services.background_scheduler import get_scheduler

        scheduler = get_scheduler()
        register_digest_subscription(sub, scheduler)
        try:
            current_user = _make_current_user(owner.id, name=owner.name)
            with patch(
                "tg_parser.mcp_server.resolve_mcp_user",
                AsyncMock(return_value=current_user),
            ):
                first = await unsubscribe_digest(subscription_id=sub.id)
                second = await unsubscribe_digest(subscription_id=sub.id)

            assert first.success is True
            assert second.success is False
            assert "not found" in second.message.lower()
        finally:
            unregister_digest_subscription(sub.id, scheduler)


@pg_only
class TestBotUnsubscribeDigestSynchronous:
    """Same contract for the bot-tool path — this is the one that actually
    runs inside the bot process where the digest jobs live."""

    async def test_bot_unsubscribe_digest_removes_scheduler_job_atomically(self, _digest_db):
        from tg_parser.bot.tools import _exec_unsubscribe_digest
        from tg_parser.services.background_scheduler import (
            get_registered_digest_subscription_ids,
            get_scheduler,
        )
        from tg_parser.services.db_context import digest_subscription_repo
        from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo

        session = _digest_db.ingestion_state_session()
        try:
            user_repo = SAUserRepo(session)
            owner = await user_repo.create_user("bob_bug035_bot")
        finally:
            await session.close()

        sub = _make_subscription(owner_id=owner.id, chat_id=987_003)
        async with digest_subscription_repo() as (repo, _db):
            await repo.create(sub)

        scheduler = get_scheduler()
        register_digest_subscription(sub, scheduler)

        captured: list[tuple[tuple, dict]] = []
        from tg_parser.services import background_scheduler as bs_module

        original_info = bs_module.logger.info

        def _capture_info(*args, **kwargs):
            captured.append((args, kwargs))
            return original_info(*args, **kwargs)

        try:
            assert sub.id in get_registered_digest_subscription_ids()

            with patch.object(bs_module.logger, "info", side_effect=_capture_info):
                result = await _exec_unsubscribe_digest(
                    {"subscription_id": sub.id},
                    current_user=_make_current_user(owner.id, name=owner.name),
                )
            assert result.get("deleted") is True
            assert sub.id not in get_registered_digest_subscription_ids(), (
                "Bot _exec_unsubscribe_digest must invalidate the in-process "
                "scheduler job synchronously."
            )

            removed_events = [
                kwargs
                for args, kwargs in captured
                if len(args) >= 1 and args[0] == "scheduler_job_removed"
            ]
            assert len(removed_events) >= 1, (
                "Post-fix bot _exec_unsubscribe_digest must emit the "
                "structured 'scheduler_job_removed' event. "
                f"Got captured calls: {captured!r}"
            )
            assert removed_events[-1].get("reason") == "bot_unsubscribe_digest", (
                "Post-fix bot _exec_unsubscribe_digest must pass reason="
                "'bot_unsubscribe_digest' so the structured log distinguishes "
                "this call site from the MCP path. Pre-fix code did not pass "
                "any reason tag — this assertion enforces the new contract. "
                f"Got: {removed_events[-1]!r}"
            )
        finally:
            unregister_digest_subscription(sub.id, scheduler)


# ===========================================================================
# Layer C — anti-regression for the existing safeguards
# ===========================================================================


@pg_only
class TestTickTimeSafeguard:
    """``run_scheduled_digests_task`` re-reads the subscription from the
    DB before delivering; this guards against the cross-process gap where
    the bot's APScheduler still has a job for an MCP-deleted subscription
    and against the sub-tick race where the cron tick fires moments after
    a DB delete commits.

    A regression in this guard would re-open the BUG-035 attack surface
    even with the new synchronous ``remove_job`` call in place, so we
    lock it in here.
    """

    async def test_run_scheduled_digests_task_returns_not_found_after_db_delete(self, _digest_db):
        from tg_parser.services.db_context import digest_subscription_repo
        from tg_parser.services.scheduler_service import run_scheduled_digests_task
        from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo

        session = _digest_db.ingestion_state_session()
        try:
            user_repo = SAUserRepo(session)
            owner = await user_repo.create_user("carol_bug035_tick")
        finally:
            await session.close()

        sub = _make_subscription(owner_id=owner.id, chat_id=987_004)
        async with digest_subscription_repo() as (repo, _db):
            await repo.create(sub)
            await repo.delete(sub.id)

        result = await run_scheduled_digests_task(sub.id)
        assert result["status"] == "not_found", (
            "tick-time DB re-check must short-circuit when the row is gone; "
            "without this, a cron tick that fires before the bot's reconcile "
            "loop catches the MCP-side delete would still deliver a stale "
            "digest (the exact BUG-035 symptom)."
        )

    async def test_no_send_message_after_unsubscribe_and_tick(self, _digest_db):
        """End-to-end proof: subscribe → register job → unsubscribe via MCP
        → manually fire the tick (simulating the cron firing in the gap
        between DB delete commit and reconcile-loop cleanup) → assert
        ``bot.send_message`` was NEVER awaited.

        Uses an ``AsyncMock`` Bot so any accidental delivery shows up as
        ``await_count > 0``."""
        from tg_parser.mcp_server import unsubscribe_digest
        from tg_parser.services.background_scheduler import get_scheduler
        from tg_parser.services.db_context import digest_subscription_repo
        from tg_parser.services.scheduler_service import run_scheduled_digests_task
        from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo

        session = _digest_db.ingestion_state_session()
        try:
            user_repo = SAUserRepo(session)
            owner = await user_repo.create_user("dora_bug035_nosend")
        finally:
            await session.close()

        sub = _make_subscription(owner_id=owner.id, chat_id=987_005)
        async with digest_subscription_repo() as (repo, _db):
            await repo.create(sub)

        scheduler = get_scheduler()
        register_digest_subscription(sub, scheduler)

        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()
        mock_bot.send_document = AsyncMock()

        try:
            current_user = _make_current_user(owner.id, name=owner.name)
            with patch(
                "tg_parser.mcp_server.resolve_mcp_user",
                AsyncMock(return_value=current_user),
            ):
                ack = await unsubscribe_digest(subscription_id=sub.id)
            assert ack.success is True

            with patch(
                "tg_parser.bot.runtime.get_bot",
                return_value=mock_bot,
            ):
                result = await run_scheduled_digests_task(sub.id)

            assert result["status"] == "not_found"
            assert mock_bot.send_message.await_count == 0, (
                "No delivery may happen after unsubscribe — explicit "
                "await_count==0 check (rather than 'no side effects')."
            )
            assert mock_bot.send_document.await_count == 0
        finally:
            unregister_digest_subscription(sub.id, scheduler)


@pg_only
class TestReconcileLoopOrphanCleanup:
    """Even if the synchronous hook regressed or an operator hard-deletes a
    DB row out-of-band (via ``psql``), the reconcile loop must still
    detect and remove the orphan APScheduler job. This was working
    before BUG-035 — guard against accidentally regressing it while
    adding the synchronous fix."""

    async def test_reconcile_loop_removes_orphan_job_after_external_db_delete(self, _digest_db):
        from tg_parser.services.background_scheduler import (
            get_registered_digest_subscription_ids,
            get_scheduler,
        )
        from tg_parser.services.db_context import digest_subscription_repo
        from tg_parser.services.scheduler_service import reconcile_digest_subscriptions
        from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo

        session = _digest_db.ingestion_state_session()
        try:
            user_repo = SAUserRepo(session)
            owner = await user_repo.create_user("erin_bug035_reconcile")
        finally:
            await session.close()

        sub = _make_subscription(owner_id=owner.id, chat_id=987_006)
        async with digest_subscription_repo() as (repo, _db):
            await repo.create(sub)

        scheduler = get_scheduler()
        register_digest_subscription(sub, scheduler)
        assert sub.id in get_registered_digest_subscription_ids()

        async with digest_subscription_repo() as (repo, _db):
            await repo.delete(sub.id)

        try:
            stats = await reconcile_digest_subscriptions()
            assert sub.id in stats["removed"]
            assert sub.id not in get_registered_digest_subscription_ids()
        finally:
            unregister_digest_subscription(sub.id, scheduler)


# ===========================================================================
# Layer D — watchlist scope decision (no symmetric bug by construction)
# ===========================================================================


class TestWatchlistInvalidationByConstruction:
    """The F11 watchlist matcher does not own a per-interest APScheduler
    job; it queries ``WatchInterestRepo.list_active_for_channel`` at the
    start of every pipeline tick, which filters on ``is_active = TRUE``.
    Therefore soft-delete (the action that ``unsubscribe_watchlist``
    performs) immediately removes the interest from consideration — no
    in-memory scheduler state to invalidate, no orphan-tick window to
    close.

    These tests lock that invariant in place: any future change that
    introduces per-interest APScheduler scheduling for watchlists would
    fail these guards, forcing a symmetric fix to be added in this file.
    """

    def setup_method(self):
        sys.path.insert(0, str(PROJECT_ROOT / "tests"))

    async def test_soft_deleted_interest_is_excluded_from_active_query(self):
        """Direct repo invariant: ``list_active_for_channel`` must not
        return a soft-deleted (``is_active=False``) interest."""
        from test_watchlist_service import _FakeInterestRepo  # type: ignore[import-not-found]

        ir = _FakeInterestRepo()
        await ir.create(
            _make_interest(
                interest_id="int-watchlist-active",
                channel_ids=["bug035_test_channel"],
                is_active=True,
            )
        )
        await ir.create(
            _make_interest(
                interest_id="int-watchlist-paused",
                channel_ids=["bug035_test_channel"],
            )
        )

        before = await ir.list_active_for_channel("bug035_test_channel")
        assert {i.id for i in before} == {"int-watchlist-active", "int-watchlist-paused"}

        soft_deleted = await ir.soft_delete("int-watchlist-paused")
        assert soft_deleted is True

        after = await ir.list_active_for_channel("bug035_test_channel")
        assert {i.id for i in after} == {"int-watchlist-active"}

    async def test_check_interests_skips_soft_deleted_interest(self):
        """End-to-end matcher invariant: even when a soft-deleted interest
        would have matched a document on keywords + threshold, the
        matcher must skip it because its source query is gated on
        ``is_active = TRUE``. This is the watchlist-symmetric guarantee
        that the BUG-035 fix relies on for the watchlist scope decision."""
        from test_watchlist_service import (  # type: ignore[import-not-found]
            _FakeEmbeddingRepo,
            _FakeInterestRepo,
            _FakeMatchRepo,
            _FakeProcessedDocRepo,
        )

        from tg_parser.services.watchlist_service import WatchlistService

        doc = ProcessedDocument(
            id="doc:tg:bug035_test_channel:post:1",
            source_ref="tg:bug035_test_channel:post:1",
            source_message_id="1",
            channel_id="bug035_test_channel",
            processed_at=datetime(2026, 5, 24, 21, 0, tzinfo=UTC),
            text_clean="bug035_keyword appears in this document body",
            summary="bug035_keyword summary",
            topics=[],
            entities=[],
        )

        ir = _FakeInterestRepo()
        await ir.create(
            _make_interest(
                interest_id="int-watch-soft-deleted",
                channel_ids=["bug035_test_channel"],
                keywords=["bug035_keyword"],
            )
        )
        await ir.soft_delete("int-watch-soft-deleted")

        mr = _FakeMatchRepo()
        service = WatchlistService(
            interest_repo=ir,
            match_repo=mr,
            processed_doc_repo=_FakeProcessedDocRepo([doc]),
            embedding_repo=_FakeEmbeddingRepo(),
            embedding_client=None,
        )

        inserted = await service.check_interests(
            channel_id="bug035_test_channel",
            new_doc_refs=[doc.source_ref],
            bot=None,
        )

        assert inserted == [], (
            "A soft-deleted watchlist interest must NEVER produce a match "
            "on a subsequent pipeline tick. If this fails, the watchlist "
            "scope decision in the BUG-035 PR (digest-only) is invalidated "
            "and a symmetric scheduler-invalidation fix is required."
        )
        assert mr.upsert_calls == 0


# ===========================================================================
# Layer E — Prometheus assertion (per handoff requirement)
# ===========================================================================


@pg_only
class TestPrometheusPublishCounterNotIncrementedAfterUnsubscribe:
    """Per handoff: ``tg_digest_channel_publish_total`` MUST NOT increment
    after unsubscribe. The counter is incremented by
    ``record_digest_channel_publish`` inside the deliver path; if the
    tick-time DB re-check correctly bails with ``not_found``, the
    counter stays untouched.

    Uses ``CollectorRegistry`` value sampling rather than asserting on
    Prometheus internals."""

    async def test_channel_publish_counter_unchanged_after_unsubscribe_then_tick(self, _digest_db):
        from tg_parser.api.metrics import DIGEST_CHANNEL_PUBLISH
        from tg_parser.mcp_server import unsubscribe_digest
        from tg_parser.services.background_scheduler import get_scheduler
        from tg_parser.services.db_context import digest_subscription_repo
        from tg_parser.services.scheduler_service import run_scheduled_digests_task
        from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo

        session = _digest_db.ingestion_state_session()
        try:
            user_repo = SAUserRepo(session)
            owner = await user_repo.create_user("frank_bug035_metric")
        finally:
            await session.close()

        sub = _make_subscription(owner_id=owner.id, chat_id=987_007)
        async with digest_subscription_repo() as (repo, _db):
            await repo.create(sub)

        scheduler = get_scheduler()
        register_digest_subscription(sub, scheduler)

        def _snapshot() -> dict[str, float]:
            out: dict[str, float] = {}
            for metric in DIGEST_CHANNEL_PUBLISH.collect():
                for sample in metric.samples:
                    out[sample.labels.get("result", "")] = (
                        out.get(sample.labels.get("result", ""), 0.0) + sample.value
                    )
            return out

        before = _snapshot()
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()
        mock_bot.send_document = AsyncMock()

        try:
            current_user = _make_current_user(owner.id, name=owner.name)
            with patch(
                "tg_parser.mcp_server.resolve_mcp_user",
                AsyncMock(return_value=current_user),
            ):
                ack = await unsubscribe_digest(subscription_id=sub.id)
            assert ack.success is True

            with patch(
                "tg_parser.bot.runtime.get_bot",
                return_value=mock_bot,
            ):
                result = await run_scheduled_digests_task(sub.id)
            assert result["status"] == "not_found"

            after = _snapshot()
            assert after == before, (
                f"Prometheus tg_digest_channel_publish_total leaked an "
                f"increment after unsubscribe + tick. Before={before} "
                f"After={after}. This signals an orphan delivery slipped "
                f"past the tick-time DB re-check."
            )
        finally:
            unregister_digest_subscription(sub.id, scheduler)


# ===========================================================================
# Postgres test fixtures (shared with the existing F6 suite)
# ===========================================================================


@pytest.fixture
async def _digest_db(test_db):
    """Truncate digest + user tables for a clean per-test slate.

    Mirrors the helper fixture in ``tests/test_f6_scheduled_digests.py`` so
    the new test classes are self-contained — they do not import from the
    F6 module to avoid coupling regression to that suite's evolution.
    """
    session = test_db.ingestion_state_session()
    try:
        from sqlalchemy import text

        await session.execute(text("DELETE FROM digest_subscriptions"))
        await session.execute(text("DELETE FROM user_auth_mappings"))
        await session.execute(text("UPDATE sources SET owner_id = NULL"))
        await session.execute(text("DELETE FROM users"))
        await session.commit()
    finally:
        await session.close()
    return test_db
