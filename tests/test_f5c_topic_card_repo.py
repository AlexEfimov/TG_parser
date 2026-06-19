"""F5-C TopicCardRepo + TopicCardVersionRepo integration tests (PG-gated).

Covers the new methods added in a4b5c6d7e8f9:

* ``increment_resummary_counter`` — atomic +N on the counter.
* ``list_resummarize_candidates`` — partial-index scan with channel filter.
* ``commit_resummary`` — atomic UPDATE with optimistic version check.
* ``SATopicCardVersionRepo.insert`` + ``list_by_topic`` — append-only audit log.
* round-trip of the three new TopicCard columns through ``upsert / get_by_id``.

Postgres-gated by ``TEST_POSTGRES=1`` to match other storage integration tests.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from tg_parser.domain.models import Anchor, MessageType, TopicCard, TopicCardVersion, TopicType
from tg_parser.storage.sqlalchemy.topic_card_repo import SATopicCardRepo
from tg_parser.storage.sqlalchemy.topic_card_version_repo import SATopicCardVersionRepo

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


def _make_card(
    *,
    topic_id: str = "topic:tg:ch_a:post:1",
    title: str = "Topic A",
    summary: str = "Original summary",
    scope_in: list[str] | None = None,
    scope_out: list[str] | None = None,
    sources: list[str] | None = None,
    summary_version: int = 1,
    counter: int = 0,
    last_summarized_at: datetime | None = None,
) -> TopicCard:
    return TopicCard(
        id=topic_id,
        title=title,
        summary=summary,
        scope_in=list(scope_in or ["aspect-1"]),
        scope_out=list(scope_out or ["excluded-1"]),
        type=TopicType.SINGLETON,
        anchors=[
            Anchor(
                channel_id="ch_a",
                message_id="1",
                message_type=MessageType.POST,
                anchor_ref="tg:ch_a:post:1",
                score=0.9,
            )
        ],
        sources=list(sources or ["ch_a"]),
        updated_at=datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC),
        summary_version=summary_version,
        new_items_since_last_summary=counter,
        last_summarized_at=last_summarized_at,
    )


@pg_only
class TestTopicCardF5CColumns:
    @pytest.mark.asyncio
    async def test_round_trip_new_columns(self, test_db):
        """upsert + get_by_id must preserve the three new F5-C columns."""
        async with test_db.processing_storage_session() as session:
            repo = SATopicCardRepo(session)
            ts = datetime(2026, 4, 25, 9, 0, 0, tzinfo=UTC)
            card = _make_card(
                summary_version=3,
                counter=7,
                last_summarized_at=ts,
            )
            await repo.upsert(card)

            fetched = await repo.get_by_id(card.id)
            assert fetched is not None
            assert fetched.summary_version == 3
            assert fetched.new_items_since_last_summary == 7
            assert fetched.last_summarized_at is not None
            assert fetched.last_summarized_at == ts

    @pytest.mark.asyncio
    async def test_increment_resummary_counter_no_op_for_zero(self, test_db):
        async with test_db.processing_storage_session() as session:
            repo = SATopicCardRepo(session)
            await repo.upsert(_make_card(counter=0))

            await repo.increment_resummary_counter("topic:tg:ch_a:post:1", by=0)
            await repo.increment_resummary_counter("topic:tg:ch_a:post:1", by=-3)

            fetched = await repo.get_by_id("topic:tg:ch_a:post:1")
            assert fetched is not None
            assert fetched.new_items_since_last_summary == 0

    @pytest.mark.asyncio
    async def test_increment_resummary_counter_atomic(self, test_db):
        async with test_db.processing_storage_session() as session:
            repo = SATopicCardRepo(session)
            await repo.upsert(_make_card(counter=2))

            await repo.increment_resummary_counter("topic:tg:ch_a:post:1", by=3)
            await repo.increment_resummary_counter("topic:tg:ch_a:post:1", by=4)

            fetched = await repo.get_by_id("topic:tg:ch_a:post:1")
            assert fetched is not None
            # Initial 2 + 3 + 4 = 9
            assert fetched.new_items_since_last_summary == 9


@pg_only
class TestListResummarizeCandidates:
    @pytest.mark.asyncio
    async def test_threshold_filter(self, test_db):
        async with test_db.processing_storage_session() as session:
            repo = SATopicCardRepo(session)
            await repo.upsert(_make_card(topic_id="topic:t1", counter=2))
            await repo.upsert(_make_card(topic_id="topic:t2", counter=5))
            await repo.upsert(_make_card(topic_id="topic:t3", counter=10))

            candidates = await repo.list_resummarize_candidates(threshold=5)
            ids = sorted(c.id for c in candidates)
            assert ids == ["topic:t2", "topic:t3"]

    @pytest.mark.asyncio
    async def test_channel_filter(self, test_db):
        async with test_db.processing_storage_session() as session:
            repo = SATopicCardRepo(session)
            await repo.upsert(_make_card(topic_id="topic:a1", counter=10, sources=["ch_a"]))
            await repo.upsert(_make_card(topic_id="topic:b1", counter=10, sources=["ch_b"]))
            await repo.upsert(
                _make_card(
                    topic_id="topic:cross",
                    counter=10,
                    sources=["ch_a", "ch_b"],
                )
            )

            for_a = await repo.list_resummarize_candidates(channel_id="ch_a", threshold=5)
            ids = sorted(c.id for c in for_a)
            assert ids == ["topic:a1", "topic:cross"]

    @pytest.mark.asyncio
    async def test_below_threshold_returns_empty(self, test_db):
        async with test_db.processing_storage_session() as session:
            repo = SATopicCardRepo(session)
            await repo.upsert(_make_card(topic_id="topic:x", counter=2))
            assert await repo.list_resummarize_candidates(threshold=5) == []

    @pytest.mark.asyncio
    async def test_ordering_is_counter_desc(self, test_db):
        """Fair-scheduling contract: candidates with the most pending items
        re-summarize first.  The ORDER BY in the SQL is
        ``new_items_since_last_summary DESC, updated_at DESC`` — without
        an ordering test, callers (e.g. ``run_for_channel``) could silently
        pick a wrong order under index-rebuild scenarios.
        """
        async with test_db.processing_storage_session() as session:
            repo = SATopicCardRepo(session)
            await repo.upsert(_make_card(topic_id="topic:low", counter=5))
            await repo.upsert(_make_card(topic_id="topic:high", counter=20))
            await repo.upsert(_make_card(topic_id="topic:mid", counter=10))

            candidates = await repo.list_resummarize_candidates(threshold=5)
            assert [c.id for c in candidates] == [
                "topic:high",
                "topic:mid",
                "topic:low",
            ]


@pg_only
class TestTimeBasedResummarizeCandidates:
    """F5-C P2 / #15 item #4 — time-based re-summarize trigger.

    ``max_age_days = 0`` is the bit-for-bit MVP (counter-only). When > 0, a
    topic with a stale summary AND at least one new item also becomes a
    candidate even if its counter is below the threshold.
    """

    @pytest.mark.asyncio
    async def test_max_age_days_zero_is_counter_only(self, test_db):
        """Default (max_age_days=0): a stale, below-threshold topic with new
        items is NOT a candidate — identical to the pre-P2 MVP behaviour."""
        old = datetime.now(UTC) - timedelta(days=60)
        async with test_db.processing_storage_session() as session:
            repo = SATopicCardRepo(session)
            await repo.upsert(_make_card(topic_id="topic:stale", counter=1, last_summarized_at=old))
            # counter-only: 1 < threshold 5 → empty
            assert await repo.list_resummarize_candidates(threshold=5, max_age_days=0) == []

    @pytest.mark.asyncio
    async def test_time_based_includes_stale_below_threshold(self, test_db):
        old = datetime.now(UTC) - timedelta(days=60)
        async with test_db.processing_storage_session() as session:
            repo = SATopicCardRepo(session)
            await repo.upsert(_make_card(topic_id="topic:stale", counter=1, last_summarized_at=old))
            candidates = await repo.list_resummarize_candidates(threshold=5, max_age_days=14)
            assert [c.id for c in candidates] == ["topic:stale"]

    @pytest.mark.asyncio
    async def test_time_based_excludes_when_no_new_items(self, test_db):
        """Guard preserved: a stale topic with zero new items is never a
        candidate (the partial-index predicate stays new_items > 0)."""
        old = datetime.now(UTC) - timedelta(days=60)
        async with test_db.processing_storage_session() as session:
            repo = SATopicCardRepo(session)
            await repo.upsert(_make_card(topic_id="topic:quiet", counter=0, last_summarized_at=old))
            assert await repo.list_resummarize_candidates(threshold=5, max_age_days=14) == []

    @pytest.mark.asyncio
    async def test_time_based_excludes_recently_summarized(self, test_db):
        recent = datetime.now(UTC) - timedelta(days=1)
        async with test_db.processing_storage_session() as session:
            repo = SATopicCardRepo(session)
            await repo.upsert(
                _make_card(topic_id="topic:fresh", counter=1, last_summarized_at=recent)
            )
            assert await repo.list_resummarize_candidates(threshold=5, max_age_days=14) == []

    @pytest.mark.asyncio
    async def test_time_based_excludes_null_last_summarized(self, test_db):
        """A never-summarized topic (last_summarized_at IS NULL) is only
        reachable via the counter branch, never the time-based branch."""
        async with test_db.processing_storage_session() as session:
            repo = SATopicCardRepo(session)
            await repo.upsert(
                _make_card(topic_id="topic:never", counter=1, last_summarized_at=None)
            )
            assert await repo.list_resummarize_candidates(threshold=5, max_age_days=14) == []

    @pytest.mark.asyncio
    async def test_time_based_still_returns_counter_candidates(self, test_db):
        """Time-based is additive: counter-trigger candidates still match."""
        recent = datetime.now(UTC) - timedelta(days=1)
        old = datetime.now(UTC) - timedelta(days=60)
        async with test_db.processing_storage_session() as session:
            repo = SATopicCardRepo(session)
            await repo.upsert(
                _make_card(topic_id="topic:counter", counter=10, last_summarized_at=recent)
            )
            await repo.upsert(_make_card(topic_id="topic:aged", counter=1, last_summarized_at=old))
            candidates = await repo.list_resummarize_candidates(threshold=5, max_age_days=14)
            assert sorted(c.id for c in candidates) == ["topic:aged", "topic:counter"]


@pg_only
class TestCommitResummary:
    @pytest.mark.asyncio
    async def test_happy_path_bumps_version_and_resets_counter(self, test_db):
        async with test_db.processing_storage_session() as session:
            repo = SATopicCardRepo(session)
            await repo.upsert(_make_card(summary_version=1, counter=8))

            now = datetime(2026, 4, 26, 18, 30, 0, tzinfo=UTC)
            ok = await repo.commit_resummary(
                "topic:tg:ch_a:post:1",
                summary="Refreshed summary",
                scope_in=["new aspect-1", "new aspect-2"],
                scope_out=["new excluded-1"],
                prev_summary_version=1,
                summarized_at=now,
                metadata_extras={"resummarize_run_at": now.isoformat()},
            )
            assert ok is True

            fetched = await repo.get_by_id("topic:tg:ch_a:post:1")
            assert fetched is not None
            assert fetched.summary == "Refreshed summary"
            assert fetched.scope_in == ["new aspect-1", "new aspect-2"]
            assert fetched.scope_out == ["new excluded-1"]
            assert fetched.summary_version == 2
            assert fetched.new_items_since_last_summary == 0
            assert fetched.last_summarized_at == now

    @pytest.mark.asyncio
    async def test_metadata_extras_none_keeps_existing_metadata(self, test_db):
        """Null-safety: ``metadata_extras=None`` must not nuke the existing
        ``metadata_json`` (the SQL uses
        ``COALESCE(:metadata_json, metadata_json)``).  Without this guard,
        a re-summarize that doesn't pass extras would silently drop
        operator-set metadata."""
        async with test_db.processing_storage_session() as session:
            repo = SATopicCardRepo(session)
            card = _make_card()
            # Pre-existing metadata that an operator (or upstream stage)
            # wrote on the card.
            card_with_meta = card.model_copy(
                update={"metadata": {"some_op_field": "preserved_value"}}
            )
            await repo.upsert(card_with_meta)

            ok = await repo.commit_resummary(
                "topic:tg:ch_a:post:1",
                summary="Refreshed",
                scope_in=["x"],
                scope_out=["y"],
                prev_summary_version=1,
                summarized_at=datetime(2026, 4, 26, tzinfo=UTC),
                metadata_extras=None,
            )
            assert ok is True

            fetched = await repo.get_by_id("topic:tg:ch_a:post:1")
            assert fetched is not None
            assert fetched.summary == "Refreshed"
            assert fetched.summary_version == 2
            # Existing metadata survived because COALESCE picked it.
            assert fetched.metadata is not None
            assert fetched.metadata.get("some_op_field") == "preserved_value"

    @pytest.mark.asyncio
    async def test_optimistic_version_check_loses_race(self, test_db):
        async with test_db.processing_storage_session() as session:
            repo = SATopicCardRepo(session)
            await repo.upsert(_make_card(summary_version=4, counter=8))

            now = datetime(2026, 4, 26, 18, 30, 0, tzinfo=UTC)
            ok = await repo.commit_resummary(
                "topic:tg:ch_a:post:1",
                summary="Stale writer",
                scope_in=["x"],
                scope_out=["y"],
                prev_summary_version=3,  # stale prev_v != actual 4
                summarized_at=now,
            )
            assert ok is False

            fetched = await repo.get_by_id("topic:tg:ch_a:post:1")
            assert fetched is not None
            # No fields touched because the WHERE clause did not match.
            assert fetched.summary == "Original summary"
            assert fetched.summary_version == 4
            assert fetched.new_items_since_last_summary == 8


@pg_only
class TestTopicCardVersionRepo:
    @pytest.mark.asyncio
    async def test_insert_and_list(self, test_db):
        async with test_db.processing_storage_session() as session:
            card_repo = SATopicCardRepo(session)
            ver_repo = SATopicCardVersionRepo(session)

            await card_repo.upsert(_make_card())

            v1 = TopicCardVersion(
                id=1,
                topic_id="topic:tg:ch_a:post:1",
                version_no=1,
                summary="v1 summary",
                scope_in=["v1-in"],
                scope_out=["v1-out"],
                supporting_items_count_at_time=3,
                llm_provider="openai",
                llm_model="gpt-4o-mini",
                prompt_version="1.0.0",
                created_at=datetime.now(UTC),
            )
            new_id_1 = await ver_repo.insert(v1)
            assert new_id_1 >= 1

            v2 = TopicCardVersion(
                id=1,
                topic_id="topic:tg:ch_a:post:1",
                version_no=2,
                summary="v2 summary",
                scope_in=["v2-in"],
                scope_out=["v2-out"],
                supporting_items_count_at_time=8,
                llm_provider="openai",
                llm_model="gpt-4o-mini",
                prompt_version="1.0.0",
                created_at=datetime.now(UTC),
            )
            new_id_2 = await ver_repo.insert(v2)
            assert new_id_2 > new_id_1

            versions = await ver_repo.list_by_topic("topic:tg:ch_a:post:1")
            # Newest first
            assert [v.version_no for v in versions] == [2, 1]
            assert versions[0].summary == "v2 summary"
            assert versions[1].supporting_items_count_at_time == 3

    @pytest.mark.asyncio
    async def test_unique_topic_version_collision(self, test_db):
        from sqlalchemy.exc import IntegrityError

        async with test_db.processing_storage_session() as session:
            card_repo = SATopicCardRepo(session)
            ver_repo = SATopicCardVersionRepo(session)
            await card_repo.upsert(_make_card())

            v1 = TopicCardVersion(
                id=1,
                topic_id="topic:tg:ch_a:post:1",
                version_no=7,
                summary="first",
                scope_in=["a"],
                scope_out=["b"],
                supporting_items_count_at_time=1,
                llm_provider=None,
                llm_model=None,
                prompt_version=None,
                created_at=datetime.now(UTC),
            )
            await ver_repo.insert(v1)

            with pytest.raises(IntegrityError):
                await ver_repo.insert(v1)
