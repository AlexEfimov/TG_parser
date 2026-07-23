"""F5-C #15 item #1 — ``topic_card_versions`` retention/TTL tests (PG-gated).

Covers ``SATopicCardVersionRepo.purge_stale`` + ``count`` (ADR-0018).

Canonical retention predicate (v1): a version row is hard-DELETEd **iff**

1. it is OUTSIDE the newest ``keep_last_n`` versions of its topic, **AND**
2. it is older than ``older_than`` (``created_at < older_than``), **AND**
3. ``version_no > 1`` — the genesis snapshot is NEVER purged.

This is a double floor: recent-floor (keep-last-N) + origin-floor (genesis).

Postgres-gated by ``TEST_POSTGRES=1`` to match other storage integration tests.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from tg_parser.domain.models import Anchor, MessageType, TopicCard, TopicType
from tg_parser.storage.sqlalchemy.topic_card_repo import SATopicCardRepo
from tg_parser.storage.sqlalchemy.topic_card_version_repo import SATopicCardVersionRepo

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


def _make_card(topic_id: str) -> TopicCard:
    return TopicCard(
        id=topic_id,
        title="Topic",
        summary="Summary",
        scope_in=["aspect-1"],
        scope_out=["excluded-1"],
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
        sources=["ch_a"],
        updated_at=datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC),
        summary_version=1,
        new_items_since_last_summary=0,
        last_summarized_at=None,
    )


async def _seed_version(session, *, topic_id: str, version_no: int, age_days: float) -> None:
    """Insert one version row with an explicit ``created_at`` (age control).

    ``insert()`` uses the DB clock for ``created_at``, so we go direct to SQL
    to place rows at precise ages for boundary testing.
    """
    created_at = datetime.now(UTC) - timedelta(days=age_days)
    await session.execute(
        text("""
            INSERT INTO topic_card_versions (
                topic_id, version_no, summary, scope_in_json, scope_out_json,
                supporting_items_count_at_time, created_at
            ) VALUES (
                :topic_id, :version_no, :summary, '["in"]', '["out"]', 0, :created_at
            )
        """),
        {
            "topic_id": topic_id,
            "version_no": version_no,
            "summary": f"v{version_no}",
            "created_at": created_at,
        },
    )
    await session.commit()


async def _remaining_versions(repo: SATopicCardVersionRepo, topic_id: str) -> list[int]:
    versions = await repo.list_by_topic(topic_id, limit=1000)
    return sorted(v.version_no for v in versions)


@pg_only
class TestPurgeStale:
    @pytest.mark.asyncio
    async def test_keeps_last_n_and_genesis_deletes_old_middle(self, test_db):
        """N-floor + genesis-pin: with keep_last_n=2 and 400d-old rows, only
        the middle versions (rn>2, old, version_no>1) are purged."""
        async with test_db.processing_storage_session() as session:
            card_repo = SATopicCardRepo(session)
            ver_repo = SATopicCardVersionRepo(session)
            await card_repo.upsert(_make_card("topic:a"))

            # v1 genesis + v2..v4 all 400d old; v5 recent.
            for vno, age in [(1, 400), (2, 400), (3, 400), (4, 400), (5, 1)]:
                await _seed_version(session, topic_id="topic:a", version_no=vno, age_days=age)

            cutoff = datetime.now(UTC) - timedelta(days=180)
            deleted = await ver_repo.purge_stale(keep_last_n=2, older_than=cutoff)

            # rn>2 → {v3,v2,v1}; old → all; version_no>1 → drop v1 ⇒ delete v2,v3.
            assert deleted == 2
            assert await _remaining_versions(ver_repo, "topic:a") == [1, 4, 5]

    @pytest.mark.asyncio
    async def test_young_rows_outside_n_are_kept(self, test_db):
        """Age-floor: a row outside the newest N but younger than the cutoff
        is NEVER deleted (only genesis is also protected here)."""
        async with test_db.processing_storage_session() as session:
            card_repo = SATopicCardRepo(session)
            ver_repo = SATopicCardVersionRepo(session)
            await card_repo.upsert(_make_card("topic:b"))

            # keep_last_n=1: rn>1 candidates are v1 (genesis, old) + v2 (young).
            await _seed_version(session, topic_id="topic:b", version_no=1, age_days=400)
            await _seed_version(session, topic_id="topic:b", version_no=2, age_days=10)
            await _seed_version(session, topic_id="topic:b", version_no=3, age_days=1)

            cutoff = datetime.now(UTC) - timedelta(days=180)
            deleted = await ver_repo.purge_stale(keep_last_n=1, older_than=cutoff)

            # v2 young (kept by age-floor), v1 genesis (kept by pin) ⇒ 0 deleted.
            assert deleted == 0
            assert await _remaining_versions(ver_repo, "topic:b") == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_genesis_never_purged_even_when_outside_n_and_old(self, test_db):
        """Explicit genesis-pin: version_no=1, outside N, older than M → kept."""
        async with test_db.processing_storage_session() as session:
            card_repo = SATopicCardRepo(session)
            ver_repo = SATopicCardVersionRepo(session)
            await card_repo.upsert(_make_card("topic:g"))

            for vno in range(1, 6):  # v1..v5, all 400d old
                await _seed_version(session, topic_id="topic:g", version_no=vno, age_days=400)

            cutoff = datetime.now(UTC) - timedelta(days=180)
            deleted = await ver_repo.purge_stale(keep_last_n=1, older_than=cutoff)

            # rn>1 → v1..v4; old → all; version_no>1 → v2,v3,v4 (NOT v1) ⇒ 3.
            assert deleted == 3
            remaining = await _remaining_versions(ver_repo, "topic:g")
            assert 1 in remaining  # genesis survives
            assert remaining == [1, 5]

    @pytest.mark.asyncio
    async def test_idempotent_second_run_deletes_zero(self, test_db):
        async with test_db.processing_storage_session() as session:
            card_repo = SATopicCardRepo(session)
            ver_repo = SATopicCardVersionRepo(session)
            await card_repo.upsert(_make_card("topic:i"))

            for vno in range(1, 6):
                await _seed_version(session, topic_id="topic:i", version_no=vno, age_days=400)

            cutoff = datetime.now(UTC) - timedelta(days=180)
            first = await ver_repo.purge_stale(keep_last_n=2, older_than=cutoff)
            second = await ver_repo.purge_stale(keep_last_n=2, older_than=cutoff)

            # keep_last_n=2 ⇒ rn>2 = {v3,v2,v1}; genesis-pin drops v1 ⇒ v2,v3.
            assert first == 2
            assert second == 0
            assert await _remaining_versions(ver_repo, "topic:i") == [1, 4, 5]

    @pytest.mark.asyncio
    async def test_large_retention_or_keep_n_deletes_zero(self, test_db):
        async with test_db.processing_storage_session() as session:
            card_repo = SATopicCardRepo(session)
            ver_repo = SATopicCardVersionRepo(session)
            await card_repo.upsert(_make_card("topic:z"))

            for vno in range(1, 6):
                await _seed_version(session, topic_id="topic:z", version_no=vno, age_days=400)

            # keep_last_n huge ⇒ nothing is "outside N" ⇒ 0.
            cutoff = datetime.now(UTC) - timedelta(days=180)
            assert await ver_repo.purge_stale(keep_last_n=1000, older_than=cutoff) == 0

            # very old cutoff (future-safe: nothing older than 1 day-from-now? no)
            # cutoff far in the past ⇒ no row is older than it ⇒ 0.
            ancient = datetime.now(UTC) - timedelta(days=10000)
            assert await ver_repo.purge_stale(keep_last_n=1, older_than=ancient) == 0
            assert await _remaining_versions(ver_repo, "topic:z") == [1, 2, 3, 4, 5]

    @pytest.mark.asyncio
    async def test_dry_run_counts_without_deleting(self, test_db):
        async with test_db.processing_storage_session() as session:
            card_repo = SATopicCardRepo(session)
            ver_repo = SATopicCardVersionRepo(session)
            await card_repo.upsert(_make_card("topic:d"))

            for vno in range(1, 6):
                await _seed_version(session, topic_id="topic:d", version_no=vno, age_days=400)

            cutoff = datetime.now(UTC) - timedelta(days=180)
            would = await ver_repo.purge_stale(keep_last_n=2, older_than=cutoff, dry_run=True)
            # Dry-run predicate matches DELETE (incl. version_no > 1).
            assert would == 2
            # Nothing deleted.
            assert await ver_repo.count() == 5
            assert await _remaining_versions(ver_repo, "topic:d") == [1, 2, 3, 4, 5]

    @pytest.mark.asyncio
    async def test_count_returns_total_rows(self, test_db):
        async with test_db.processing_storage_session() as session:
            card_repo = SATopicCardRepo(session)
            ver_repo = SATopicCardVersionRepo(session)
            assert await ver_repo.count() == 0
            await card_repo.upsert(_make_card("topic:c"))
            for vno in range(1, 4):
                await _seed_version(session, topic_id="topic:c", version_no=vno, age_days=1)
            assert await ver_repo.count() == 3

    @pytest.mark.asyncio
    async def test_per_topic_partition_independent(self, test_db):
        """keep-last-N is per topic (PARTITION BY topic_id), not global."""
        async with test_db.processing_storage_session() as session:
            card_repo = SATopicCardRepo(session)
            ver_repo = SATopicCardVersionRepo(session)
            await card_repo.upsert(_make_card("topic:p1"))
            await card_repo.upsert(_make_card("topic:p2"))

            for vno in range(1, 5):  # p1: v1..v4 old
                await _seed_version(session, topic_id="topic:p1", version_no=vno, age_days=400)
            for vno in range(1, 3):  # p2: v1..v2 old
                await _seed_version(session, topic_id="topic:p2", version_no=vno, age_days=400)

            cutoff = datetime.now(UTC) - timedelta(days=180)
            deleted = await ver_repo.purge_stale(keep_last_n=2, older_than=cutoff)

            # p1: rn>2 = v2,v1; drop genesis v1 ⇒ delete v2 (1 row).
            # p2: only v1,v2 (rn<=2) ⇒ nothing outside N ⇒ 0.
            assert deleted == 1
            assert await _remaining_versions(ver_repo, "topic:p1") == [1, 3, 4]
            assert await _remaining_versions(ver_repo, "topic:p2") == [1, 2]
