"""Regression suite for BUG-029 — ``subscribe`` race-retry must roll back the
aborted transaction before re-querying.

Root cause (digest + symmetric watchlist): the ``except IntegrityError:``
branch of ``DigestService.subscribe`` / ``WatchlistService.subscribe``
re-attempts ``find_by_*`` + ``_apply_*_upsert`` on the *same* ``AsyncSession``
without first issuing ``await session.rollback()``. A failed INSERT leaves the
SQLAlchemy session in an aborted-transaction state, so the very next
``.execute(...)`` raises ``sqlalchemy.exc.PendingRollbackError`` and the
idempotent-upsert retry can never run — the caller receives a misleading 500
instead of the BUG-022 collapse-to-single-row behaviour.

These tests REQUIRE a real PostgreSQL session: the in-memory fakes in
``tests/test_subscribe_idempotency.py`` cannot reproduce the
aborted-transaction guard (no real flush), so they pass even on the buggy
code. They are gated by ``TEST_POSTGRES=1`` and use the alembic-managed
``tg_parser_test`` schema (UNIQUE (owner_id, name) / UNIQUE (user_id, title)).

Determinism: the core reproduction does NOT rely on wall-clock timing. A thin
repo subclass injects the *concurrent winner* row through an independent,
committed session at the exact moment between ``subscribe``'s pre-check
``find_by_*`` (which sees no row) and the real ``create()`` INSERT — forcing
the IntegrityError window deterministically. A separate ``asyncio.gather`` test
additionally exercises the natural multi-session race.

Synthetic IDs only — no real ``chat_id=5445781511`` / ``digest_94483db9``.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import PendingRollbackError

from tg_parser.domain.models import DigestFormat, NotifyMode
from tg_parser.services.digest_service import DigestService
from tg_parser.services.digest_service import SubscribeResult as DigestSubscribeResult
from tg_parser.services.watchlist_service import SubscribeResult as WatchSubscribeResult
from tg_parser.services.watchlist_service import WatchlistService
from tg_parser.storage.sqlalchemy.digest_subscription_repo import (
    SADigestSubscriptionRepo,
)
from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo
from tg_parser.storage.sqlalchemy.watch_interest_repo import SAWatchInterestRepo

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture
async def _race_db(test_db):
    """Truncate the F6/F11 tables the race tests touch (alembic-managed)."""
    session = test_db.ingestion_state_session()
    try:
        await session.execute(text("DELETE FROM watch_matches"))
        await session.execute(text("DELETE FROM watch_interests"))
        await session.execute(text("DELETE FROM digest_subscriptions"))
        await session.execute(text("DELETE FROM user_auth_mappings"))
        await session.execute(text("UPDATE sources SET owner_id = NULL"))
        await session.execute(text("DELETE FROM users"))
        await session.commit()
    finally:
        await session.close()
    return test_db


async def _make_owner(db, name: str) -> str:
    session = db.ingestion_state_session()
    try:
        user = await SAUserRepo(session).create_user(name)
        return user.id
    finally:
        await session.close()


def _make_digest_service(repo: SADigestSubscriptionRepo) -> DigestService:
    return DigestService(
        processed_repo=None,
        subscription_repo=repo,
        prompt_loader=None,
        llm_client_factory=None,
        workspace_repo=None,
    )


def _make_watchlist_service(repo: SAWatchInterestRepo) -> WatchlistService:
    return WatchlistService(
        interest_repo=repo,
        match_repo=None,  # type: ignore[arg-type]  # subscribe() never touches it
        processed_doc_repo=None,  # type: ignore[arg-type]
        embedding_repo=None,  # type: ignore[arg-type]
        embedding_client=None,
    )


class _RaceInjectingDigestRepo(SADigestSubscriptionRepo):
    """Deterministically opens the BUG-029 race window.

    On the FIRST ``create()`` the repo commits a *conflicting* row through an
    independent session (the concurrent winner) and only THEN runs the real
    INSERT, which now collides with ``UNIQUE (owner_id, name)`` and raises
    ``IntegrityError`` on this session — exactly the state the buggy retry
    branch fails to roll back. Subsequent ``create()`` calls behave normally.

    ``winner_overrides`` lets a test make the winner row differ from the
    caller payload so the retry path performs a real UPDATE (idempotent-update
    semantics) rather than a no-op replay.
    """

    def __init__(self, session, db, *, winner_overrides: dict | None = None):
        super().__init__(session)
        self._db = db
        self._winner_overrides = winner_overrides or {}
        self.winner_id: str | None = None
        self._fired = False

    async def create(self, sub):
        if not self._fired:
            self._fired = True
            self.winner_id = str(uuid.uuid4())
            winner = sub.model_copy(update={"id": self.winner_id, **self._winner_overrides})
            other = self._db.ingestion_state_session()
            try:
                await SADigestSubscriptionRepo(other).create(winner)
            finally:
                await other.close()
        return await super().create(sub)


class _RaceInjectingWatchRepo(SAWatchInterestRepo):
    """Symmetric BUG-029 race-window injector for ``watch_interests``."""

    def __init__(self, session, db, *, winner_overrides: dict | None = None):
        super().__init__(session)
        self._db = db
        self._winner_overrides = winner_overrides or {}
        self.winner_id: str | None = None
        self._fired = False

    async def create(self, interest):
        if not self._fired:
            self._fired = True
            self.winner_id = str(uuid.uuid4())
            winner = interest.model_copy(update={"id": self.winner_id, **self._winner_overrides})
            other = self._db.ingestion_state_session()
            try:
                await SAWatchInterestRepo(other).create(winner)
            finally:
                await other.close()
        return await super().create(interest)


class _BarrierDigestRepo(SADigestSubscriptionRepo):
    """Forces a deterministic N-way INSERT collision for the gather test.

    Every concurrent caller blocks on ``barrier`` *after* ``subscribe``'s
    pre-check ``find_by_owner_and_name`` (which all see as empty) and *before*
    the real INSERT. When the barrier releases, all N INSERTs race the
    ``UNIQUE (owner_id, name)`` constraint at once: exactly one wins, the
    remaining N-1 deterministically hit ``IntegrityError`` and exercise the
    rollback-retry path. Uses an ``asyncio.Barrier`` rather than ``sleep`` so
    the timing is reproducible, not wall-clock dependent.
    """

    def __init__(self, session, barrier: asyncio.Barrier):
        super().__init__(session)
        self._barrier = barrier

    async def create(self, sub):
        await self._barrier.wait()
        return await super().create(sub)


class _BarrierWatchRepo(SAWatchInterestRepo):
    """Symmetric deterministic N-way INSERT collision for ``watch_interests``."""

    def __init__(self, session, barrier: asyncio.Barrier):
        super().__init__(session)
        self._barrier = barrier

    async def create(self, interest):
        await self._barrier.wait()
        return await super().create(interest)


async def _count_digests(db, owner_id: str, name: str) -> int:
    session = db.ingestion_state_session()
    try:
        result = await session.execute(
            text("SELECT COUNT(*) FROM digest_subscriptions WHERE owner_id = :o AND name = :n"),
            {"o": owner_id, "n": name},
        )
        return int(result.scalar_one())
    finally:
        await session.close()


async def _count_interests(db, user_id: str, title: str) -> int:
    session = db.ingestion_state_session()
    try:
        result = await session.execute(
            text("SELECT COUNT(*) FROM watch_interests WHERE user_id = :u AND title = :t"),
            {"u": user_id, "t": title},
        )
        return int(result.scalar_one())
    finally:
        await session.close()


_DIGEST_KW = {
    "channel_ids": ["@durov"],
    "cron_expression": "0 9 * * *",
    "timezone": "UTC",
    "format": DigestFormat.SUMMARY,
    "language": "ru",
}

_WATCH_KW = {
    "channel_ids": ["@durov"],
    "keywords": ["mica"],
    "threshold": 0.6,
    "notify_mode": NotifyMode.INSTANT,
}


# ===========================================================================
# Digest
# ===========================================================================


@pg_only
@pytest.mark.asyncio
class TestDigestSubscribeRace:
    async def test_race_retry_recovers_session_no_pending_rollback(self, _race_db):
        """Core regression: a forced IntegrityError must NOT leave the session
        in an aborted state. Pre-fix this raises ``PendingRollbackError`` from
        the retry ``find_by_owner_and_name`` SELECT."""
        db = _race_db
        owner = await _make_owner(db, "digest-race-owner")
        session = db.ingestion_state_session()
        try:
            repo = _RaceInjectingDigestRepo(session, db)
            svc = _make_digest_service(repo)

            result = await svc.subscribe(owner_id=owner, name="morning", chat_id=111, **_DIGEST_KW)

            assert isinstance(result, DigestSubscribeResult)
            # The race winner already created the row; we collapse to UPDATE.
            assert result.created is False
            assert result.subscription.id == repo.winner_id

            # Post-race usability: the SAME session must still serve queries
            # (proves rollback restored it — the heart of the regression).
            again = await repo.find_by_owner_and_name(owner, "morning")
            assert again is not None
            assert again.id == repo.winner_id
        finally:
            await session.close()

        # Idempotency invariant (BUG-022): a single row, never a duplicate.
        assert await _count_digests(db, owner, "morning") == 1

    async def test_race_retry_applies_update_not_duplicate(self, _race_db):
        """When the winner row differs from the caller payload, the retry path
        performs an UPDATE (changed_fields populated) and still collapses to a
        single row."""
        db = _race_db
        owner = await _make_owner(db, "digest-update-owner")
        session = db.ingestion_state_session()
        try:
            repo = _RaceInjectingDigestRepo(
                session, db, winner_overrides={"cron_expression": "0 18 * * *"}
            )
            svc = _make_digest_service(repo)

            result = await svc.subscribe(owner_id=owner, name="evening", chat_id=222, **_DIGEST_KW)

            assert result.created is False
            assert "cron_expression" in result.changed_fields
            # Caller payload (09:00) wins over the injected winner (18:00).
            assert result.subscription.cron_expression == "0 9 * * *"
        finally:
            await session.close()

        assert await _count_digests(db, owner, "evening") == 1

    async def test_concurrent_subscribe_no_pending_rollback(self, _race_db):
        """Natural multi-session race via asyncio.gather. Each call owns its
        session (mirrors production ``digest_subscription_repo()`` per-request).
        No ``PendingRollbackError`` may leak; exactly one create-winner; the
        race collapses to a single row."""
        db = _race_db
        owner = await _make_owner(db, "digest-gather-owner")
        sessions: list = []
        n = 4
        barrier = asyncio.Barrier(n)

        async def _one() -> DigestSubscribeResult:
            session = db.ingestion_state_session()
            sessions.append(session)
            repo = _BarrierDigestRepo(session, barrier)
            svc = _make_digest_service(repo)
            return await svc.subscribe(owner_id=owner, name="concurrent", chat_id=333, **_DIGEST_KW)

        try:
            results = await asyncio.gather(*[_one() for _ in range(n)], return_exceptions=True)
        finally:
            for s in sessions:
                await s.close()

        for r in results:
            assert not isinstance(r, PendingRollbackError), r
            assert not isinstance(r, Exception), r

        created_flags = [r.created for r in results]  # type: ignore[union-attr]
        assert created_flags.count(True) == 1, "exactly one INSERT winner"
        ids = {r.subscription.id for r in results}  # type: ignore[union-attr]
        assert len(ids) == 1, "race must collapse to a single row"
        assert await _count_digests(db, owner, "concurrent") == 1

    async def test_single_call_baseline(self, _race_db):
        """No race: a plain subscribe still creates exactly one row."""
        db = _race_db
        owner = await _make_owner(db, "digest-baseline-owner")
        session = db.ingestion_state_session()
        try:
            svc = _make_digest_service(SADigestSubscriptionRepo(session))
            result = await svc.subscribe(owner_id=owner, name="solo", chat_id=444, **_DIGEST_KW)
            assert result.created is True
            assert result.changed_fields == []
        finally:
            await session.close()

        assert await _count_digests(db, owner, "solo") == 1


# ===========================================================================
# Watchlist (symmetric BUG-029 fix)
# ===========================================================================


@pg_only
@pytest.mark.asyncio
class TestWatchlistSubscribeRace:
    async def test_race_retry_recovers_session_no_pending_rollback(self, _race_db):
        db = _race_db
        owner = await _make_owner(db, "watch-race-owner")
        session = db.ingestion_state_session()
        try:
            repo = _RaceInjectingWatchRepo(session, db)
            svc = _make_watchlist_service(repo)

            result = await svc.subscribe(
                user_id=owner, title="MiCA watch", chat_id=555, **_WATCH_KW
            )

            assert isinstance(result, WatchSubscribeResult)
            assert result.created is False
            assert result.interest.id == repo.winner_id

            again = await repo.find_by_user_and_title(owner, "MiCA watch")
            assert again is not None
            assert again.id == repo.winner_id
        finally:
            await session.close()

        assert await _count_interests(db, owner, "MiCA watch") == 1

    async def test_concurrent_subscribe_no_pending_rollback(self, _race_db):
        db = _race_db
        owner = await _make_owner(db, "watch-gather-owner")
        sessions: list = []
        n = 4
        barrier = asyncio.Barrier(n)

        async def _one() -> WatchSubscribeResult:
            session = db.ingestion_state_session()
            sessions.append(session)
            repo = _BarrierWatchRepo(session, barrier)
            svc = _make_watchlist_service(repo)
            return await svc.subscribe(user_id=owner, title="DORA watch", chat_id=666, **_WATCH_KW)

        try:
            results = await asyncio.gather(*[_one() for _ in range(n)], return_exceptions=True)
        finally:
            for s in sessions:
                await s.close()

        for r in results:
            assert not isinstance(r, PendingRollbackError), r
            assert not isinstance(r, Exception), r

        created_flags = [r.created for r in results]  # type: ignore[union-attr]
        assert created_flags.count(True) == 1
        ids = {r.interest.id for r in results}  # type: ignore[union-attr]
        assert len(ids) == 1
        assert await _count_interests(db, owner, "DORA watch") == 1

    async def test_single_call_baseline(self, _race_db):
        db = _race_db
        owner = await _make_owner(db, "watch-baseline-owner")
        session = db.ingestion_state_session()
        try:
            svc = _make_watchlist_service(SAWatchInterestRepo(session))
            result = await svc.subscribe(
                user_id=owner, title="solo watch", chat_id=777, **_WATCH_KW
            )
            assert result.created is True
            assert result.changed_fields == []
        finally:
            await session.close()

        assert await _count_interests(db, owner, "solo watch") == 1
