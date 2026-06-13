"""F11 — Topic Watchlist repository integration tests (PG-gated).

Postgres-backed tests are gated by ``TEST_POSTGRES=1`` (matches existing
F4 / F6 storage tests).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tg_parser.domain.models import (
    NotifyMode,
    WatchInterest,
    WatchMatch,
)
from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo
from tg_parser.storage.sqlalchemy.watch_interest_repo import SAWatchInterestRepo
from tg_parser.storage.sqlalchemy.watch_match_repo import SAWatchMatchRepo

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------


@pytest.fixture
async def _watchlist_db(test_db):
    """Truncate F4 + F11 tables (alembic-managed schema, DI-19)."""
    session = test_db.ingestion_state_session()
    try:
        await session.execute(text("DELETE FROM watch_matches"))
        await session.execute(text("DELETE FROM watch_interests"))
        await session.execute(text("DELETE FROM user_auth_mappings"))
        await session.execute(text("UPDATE sources SET owner_id = NULL"))
        await session.execute(text("DELETE FROM users"))
        await session.commit()
    finally:
        await session.close()
    return test_db


@pytest.fixture
async def user_repo(_watchlist_db):
    session = _watchlist_db.ingestion_state_session()
    try:
        yield SAUserRepo(session)
    finally:
        await session.close()


@pytest.fixture
async def interest_repo(_watchlist_db):
    session = _watchlist_db.ingestion_state_session()
    try:
        yield SAWatchInterestRepo(session)
    finally:
        await session.close()


@pytest.fixture
async def match_repo(_watchlist_db):
    session = _watchlist_db.ingestion_state_session()
    try:
        yield SAWatchMatchRepo(session)
    finally:
        await session.close()


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _make_interest(
    *,
    owner_id: str,
    title: str = "MiCA / EU crypto regulation",
    keywords: list[str] | None = None,
    channel_ids: list[str] | None = None,
    threshold: float = 0.6,
    embedding: list[float] | None = None,
    is_active: bool = True,
) -> WatchInterest:
    return WatchInterest(
        id="",
        user_id=owner_id,
        chat_id=12345,
        title=title,
        description="Watch crypto regulation news",
        keywords=list(keywords or ["mica", "regulation"]),
        exclude_keywords=["meme"],
        channel_ids=list(channel_ids or ["crypto_news"]),
        threshold=threshold,
        notify_mode=NotifyMode.INSTANT,
        is_active=is_active,
        embedding=embedding,
    )


# ----------------------------------------------------------------------------
# WatchInterestRepo
# ----------------------------------------------------------------------------


@pg_only
class TestWatchInterestRepo:
    async def test_create_and_get_round_trip(self, interest_repo, user_repo):
        owner = await user_repo.create_user("alice_f11")
        emb = [0.5] * 1536
        draft = _make_interest(owner_id=owner.id, embedding=emb)
        created = await interest_repo.create(draft)

        assert created.id and created.id != ""
        assert created.user_id == owner.id
        assert created.title == draft.title
        assert created.keywords == draft.keywords
        assert created.exclude_keywords == draft.exclude_keywords
        assert created.channel_ids == draft.channel_ids
        assert created.threshold == pytest.approx(draft.threshold)
        assert created.notify_mode == NotifyMode.INSTANT
        assert created.is_active is True
        assert created.embedding is not None
        assert len(created.embedding) == 1536
        assert created.created_at is not None
        assert created.updated_at is not None

        fetched = await interest_repo.get(created.id)
        assert fetched is not None
        assert fetched.id == created.id

    async def test_list_active_for_channel_filters(self, interest_repo, user_repo):
        owner = await user_repo.create_user("bob_f11")
        await interest_repo.create(_make_interest(owner_id=owner.id, channel_ids=["ch_a", "ch_b"]))
        await interest_repo.create(
            _make_interest(owner_id=owner.id, channel_ids=["ch_c"], title="other interest")
        )
        # Inactive interest should not be returned even if channel matches.
        inactive = await interest_repo.create(
            _make_interest(
                owner_id=owner.id,
                channel_ids=["ch_a"],
                title="paused interest",
            )
        )
        await interest_repo.soft_delete(inactive.id)

        for_a = await interest_repo.list_active_for_channel("ch_a")
        for_c = await interest_repo.list_active_for_channel("ch_c")
        for_unknown = await interest_repo.list_active_for_channel("ch_zzz")

        assert {i.title for i in for_a} == {"MiCA / EU crypto regulation"}
        assert {i.title for i in for_c} == {"other interest"}
        assert for_unknown == []

    async def test_update_embedding_and_round_trip_pgvector(self, interest_repo, user_repo):
        owner = await user_repo.create_user("carol_f11")
        created = await interest_repo.create(_make_interest(owner_id=owner.id, embedding=None))
        assert created.embedding is None

        new_emb = [float(i) / 1000.0 for i in range(1536)]
        await interest_repo.update_embedding(created.id, new_emb)

        fetched = await interest_repo.get(created.id)
        assert fetched is not None
        assert fetched.embedding is not None
        assert len(fetched.embedding) == 1536
        # pgvector stores at f4 precision; allow loose tolerance on each elt.
        assert fetched.embedding[0] == pytest.approx(0.0)
        assert fetched.embedding[100] == pytest.approx(0.1, abs=1e-4)
        assert fetched.embedding[-1] == pytest.approx(1.535, abs=1e-3)

    async def test_soft_delete_preserves_match_history(self, interest_repo, match_repo, user_repo):
        owner = await user_repo.create_user("dave_f11")
        interest = await interest_repo.create(_make_interest(owner_id=owner.id))

        match = WatchMatch(
            id=0,
            interest_id=interest.id,
            source_ref="tg:crypto_news:post:1",
            channel_id="crypto_news",
            keyword_score=0.5,
            semantic_score=0.8,
            combined_score=0.68,
            notified=False,
        )
        inserted = await match_repo.upsert_many([match])
        assert len(inserted) == 1

        ok = await interest_repo.soft_delete(interest.id)
        assert ok is True

        # Interest still exists, but is_active = False
        still_there = await interest_repo.get(interest.id)
        assert still_there is not None
        assert still_there.is_active is False

        # Match history is preserved (FK CASCADE only fires on hard DELETE).
        history = await match_repo.list_for_interest(interest.id)
        assert len(history) == 1

        # Second soft_delete is a no-op.
        ok_again = await interest_repo.soft_delete(interest.id)
        assert ok_again is False

    async def test_touch_checked_and_match_advance_timestamps(self, interest_repo, user_repo):
        owner = await user_repo.create_user("eve_f11")
        interest = await interest_repo.create(_make_interest(owner_id=owner.id))
        assert interest.last_checked_at is None
        assert interest.last_match_at is None

        ts = datetime(2026, 4, 25, 12, 0, 0, tzinfo=UTC)
        await interest_repo.touch_checked(interest.id, ts)
        await interest_repo.touch_match(interest.id, ts)

        fetched = await interest_repo.get(interest.id)
        assert fetched is not None
        assert fetched.last_checked_at is not None
        assert fetched.last_match_at is not None

    async def test_threshold_range_check_constraint(self, interest_repo, user_repo):
        from pydantic import ValidationError

        # Pydantic blocks out-of-range thresholds at the model boundary
        # (ge=0, le=1); make sure that is the case so the DB never sees it.
        owner = await user_repo.create_user("frank_f11")
        with pytest.raises(ValidationError):
            _make_interest(owner_id=owner.id, threshold=1.5)

    async def test_list_for_user_scopes_to_owner(self, interest_repo, user_repo):
        # list_for_user returns ONLY the caller's interests — used by
        # bot/MCP/CLI list_watchlists for non-admins (gotcha: admin path
        # uses list_all instead).
        alice = await user_repo.create_user("alice_lfu")
        bob = await user_repo.create_user("bob_lfu")
        await interest_repo.create(_make_interest(owner_id=alice.id, title="alice-1"))
        await interest_repo.create(_make_interest(owner_id=alice.id, title="alice-2"))
        await interest_repo.create(_make_interest(owner_id=bob.id, title="bob-1"))

        alice_list = await interest_repo.list_for_user(alice.id)
        bob_list = await interest_repo.list_for_user(bob.id)
        ghost = await interest_repo.list_for_user("00000000-0000-0000-0000-000000000000")

        assert {i.title for i in alice_list} == {"alice-1", "alice-2"}
        assert {i.title for i in bob_list} == {"bob-1"}
        assert ghost == []

    async def test_list_all_returns_every_interest_active_or_not(self, interest_repo, user_repo):
        # list_all is the admin-only entry point used by the bot's
        # ``list_watchlists`` exec — must include soft-deleted interests so
        # admins can audit historical subscriptions.
        owner = await user_repo.create_user("admin_view")
        i1 = await interest_repo.create(_make_interest(owner_id=owner.id, title="active-1"))
        i2 = await interest_repo.create(_make_interest(owner_id=owner.id, title="active-2"))
        await interest_repo.soft_delete(i2.id)

        rows = await interest_repo.list_all()
        titles = {row.title: row.is_active for row in rows}
        assert "active-1" in titles
        assert "active-2" in titles
        assert titles["active-1"] is True
        assert titles["active-2"] is False
        # Ordered by created_at ASC so admins see oldest first.
        ids = [row.id for row in rows]
        assert ids.index(i1.id) < ids.index(i2.id)

    async def test_create_with_provided_id_persists_that_id(self, interest_repo, user_repo):
        # The ``provided_id`` branch in create() lets callers (e.g. MCP
        # idempotent ingest, future "import watchlist" CLI) supply a
        # deterministic UUID instead of relying on the DB default. Verify
        # the round-trip preserves the value verbatim.
        owner = await user_repo.create_user("provided_id_user")
        explicit_id = "11111111-2222-3333-4444-555555555555"
        draft = _make_interest(owner_id=owner.id, title="provided-id")
        with_id = draft.model_copy(update={"id": explicit_id})

        created = await interest_repo.create(with_id)
        assert created.id == explicit_id

        fetched = await interest_repo.get(explicit_id)
        assert fetched is not None
        assert fetched.title == "provided-id"

    async def test_threshold_source_round_trip(self, interest_repo, user_repo):
        # BUG-054 / ADR 0015: threshold_source persists on create and is
        # rewritable via update_subscribe_fields; an unset value round-trips
        # as NULL (legacy/back-compat rows).
        owner = await user_repo.create_user("threshold_src_user")

        # Explicit provenance survives create.
        auto_draft = _make_interest(owner_id=owner.id, title="auto-src").model_copy(
            update={"threshold_source": "auto"}
        )
        created = await interest_repo.create(auto_draft)
        assert created.threshold_source == "auto"
        fetched = await interest_repo.get(created.id)
        assert fetched is not None
        assert fetched.threshold_source == "auto"

        # update_subscribe_fields can flip the provenance.
        updated = await interest_repo.update_subscribe_fields(
            created.id, threshold=0.33, threshold_source="manual"
        )
        assert updated is not None
        assert updated.threshold_source == "manual"
        assert updated.threshold == pytest.approx(0.33)

        # Unset provenance round-trips as NULL.
        null_draft = _make_interest(owner_id=owner.id, title="null-src")
        created_null = await interest_repo.create(null_draft)
        assert created_null.threshold_source is None
        fetched_null = await interest_repo.get(created_null.id)
        assert fetched_null is not None
        assert fetched_null.threshold_source is None

    async def test_notify_mode_batch_round_trip(self, interest_repo, user_repo):
        # Default tests use NotifyMode.INSTANT; ensure BATCH also serialises
        # to the DB and back without coercion to INSTANT (would silently
        # break F6-style scheduled-digest opt-outs).
        owner = await user_repo.create_user("batch_user")
        draft = _make_interest(owner_id=owner.id, title="batch-mode").model_copy(
            update={"notify_mode": NotifyMode.BATCH}
        )
        created = await interest_repo.create(draft)
        assert created.notify_mode == NotifyMode.BATCH
        fetched = await interest_repo.get(created.id)
        assert fetched is not None
        assert fetched.notify_mode == NotifyMode.BATCH

    async def test_list_active_for_channel_orders_by_created_at(self, interest_repo, user_repo):
        # Stable ordering matters for snapshot-style logging
        # (``watchlist.check_interests interests=N``) — deterministic order
        # makes flake-hunting easier when we add metric labels per interest.
        owner = await user_repo.create_user("ordering_user")
        first = await interest_repo.create(
            _make_interest(owner_id=owner.id, channel_ids=["ch_x"], title="first")
        )
        second = await interest_repo.create(
            _make_interest(owner_id=owner.id, channel_ids=["ch_x"], title="second")
        )
        third = await interest_repo.create(
            _make_interest(owner_id=owner.id, channel_ids=["ch_x"], title="third")
        )

        rows = await interest_repo.list_active_for_channel("ch_x")
        ids = [r.id for r in rows]
        assert ids == [first.id, second.id, third.id]


# ----------------------------------------------------------------------------
# WatchMatchRepo
# ----------------------------------------------------------------------------


@pg_only
class TestWatchMatchRepo:
    async def _seed_interest(self, interest_repo, user_repo, name: str = "u"):
        owner = await user_repo.create_user(name)
        return await interest_repo.create(_make_interest(owner_id=owner.id))

    async def test_upsert_many_returns_only_new(self, interest_repo, match_repo, user_repo):
        interest = await self._seed_interest(interest_repo, user_repo, "u1")
        m1 = WatchMatch(
            id=0,
            interest_id=interest.id,
            source_ref="tg:crypto_news:post:1",
            channel_id="crypto_news",
            keyword_score=0.5,
            semantic_score=0.7,
            combined_score=0.62,
            notified=False,
        )
        m2 = WatchMatch(
            id=0,
            interest_id=interest.id,
            source_ref="tg:crypto_news:post:2",
            channel_id="crypto_news",
            keyword_score=1.0,
            semantic_score=0.9,
            combined_score=0.94,
            notified=False,
        )

        first = await match_repo.upsert_many([m1, m2])
        assert len(first) == 2
        assert {m.source_ref for m in first} == {
            "tg:crypto_news:post:1",
            "tg:crypto_news:post:2",
        }

        # Re-running with the same (interest_id, source_ref) pair returns nothing.
        again = await match_repo.upsert_many([m1, m2])
        assert again == []

    async def test_list_for_interest_with_since_cursor(self, interest_repo, match_repo, user_repo):
        interest = await self._seed_interest(interest_repo, user_repo, "u2")
        await match_repo.upsert_many(
            [
                WatchMatch(
                    id=0,
                    interest_id=interest.id,
                    source_ref=f"tg:crypto_news:post:{i}",
                    channel_id="crypto_news",
                    keyword_score=0.5,
                    semantic_score=0.7,
                    combined_score=0.62,
                    notified=False,
                )
                for i in range(3)
            ]
        )

        all_rows = await match_repo.list_for_interest(interest.id)
        assert len(all_rows) == 3
        future = datetime.now(UTC).replace(year=2099)
        empty = await match_repo.list_for_interest(interest.id, since=future)
        assert empty == []

    async def test_mark_notified_flips_flag(self, interest_repo, match_repo, user_repo):
        interest = await self._seed_interest(interest_repo, user_repo, "u3")
        inserted = await match_repo.upsert_many(
            [
                WatchMatch(
                    id=0,
                    interest_id=interest.id,
                    source_ref="tg:crypto_news:post:42",
                    channel_id="crypto_news",
                    keyword_score=0.5,
                    semantic_score=0.7,
                    combined_score=0.62,
                    notified=False,
                )
            ]
        )
        match_id = inserted[0].id
        await match_repo.mark_notified([match_id])

        rows = await match_repo.list_for_interest(interest.id)
        assert len(rows) == 1
        assert rows[0].notified is True


# ----------------------------------------------------------------------------
# Schema-level constraint checks
# ----------------------------------------------------------------------------


@pg_only
class TestWatchlistSchemaConstraints:
    async def test_user_id_fk_blocks_orphan_interests(self, interest_repo):
        with pytest.raises(IntegrityError):
            await interest_repo.create(
                _make_interest(owner_id="00000000-0000-0000-0000-000000000000")
            )

    async def test_unique_interest_source_blocks_dup_via_raw_insert(
        self, interest_repo, user_repo, _watchlist_db
    ):
        owner = await user_repo.create_user("g_f11")
        interest = await interest_repo.create(_make_interest(owner_id=owner.id))

        session = _watchlist_db.ingestion_state_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO watch_matches "
                    "(interest_id, source_ref, channel_id, "
                    " keyword_score, semantic_score, combined_score) "
                    "VALUES (:iid, :sr, :ch, 0.5, 0.5, 0.5)"
                ),
                {
                    "iid": interest.id,
                    "sr": "tg:crypto_news:post:1",
                    "ch": "crypto_news",
                },
            )
            await session.commit()
            with pytest.raises(IntegrityError):
                await session.execute(
                    text(
                        "INSERT INTO watch_matches "
                        "(interest_id, source_ref, channel_id, "
                        " keyword_score, semantic_score, combined_score) "
                        "VALUES (:iid, :sr, :ch, 0.5, 0.5, 0.5)"
                    ),
                    {
                        "iid": interest.id,
                        "sr": "tg:crypto_news:post:1",
                        "ch": "crypto_news",
                    },
                )
                await session.commit()
        finally:
            await session.close()
