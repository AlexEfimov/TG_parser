"""F5-C #15 item #2 — ``SATopicCardVersionRepo.get_two_versions`` (PG-gated).

Read-path for the diff API. Verifies:

* a requested pair resolves to a ``{version_no: TopicCardVersion}`` mapping;
* a purged / missing ``version_no`` (retention gap, ADR-0018) is simply
  **absent** from the result (robust to gaps by construction) — never raises;
* genesis (v1) always resolves.

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


async def _seed_version(session, *, topic_id: str, version_no: int) -> None:
    created_at = datetime.now(UTC) - timedelta(days=version_no)
    await session.execute(
        text("""
            INSERT INTO topic_card_versions (
                topic_id, version_no, summary, scope_in_json, scope_out_json,
                supporting_items_count_at_time, created_at
            ) VALUES (
                :topic_id, :version_no, :summary,
                '["in-a", "in-b"]', '["out-a"]', 0, :created_at
            )
        """),
        {
            "topic_id": topic_id,
            "version_no": version_no,
            "summary": f"summary v{version_no}",
            "created_at": created_at,
        },
    )
    await session.commit()


@pg_only
class TestGetTwoVersions:
    @pytest.mark.asyncio
    async def test_resolves_existing_pair(self, test_db):
        async with test_db.processing_storage_session() as session:
            card_repo = SATopicCardRepo(session)
            ver_repo = SATopicCardVersionRepo(session)
            await card_repo.upsert(_make_card("topic:pair"))
            for vno in (1, 2, 3):
                await _seed_version(session, topic_id="topic:pair", version_no=vno)

            got = await ver_repo.get_two_versions("topic:pair", 1, 3)

            assert set(got.keys()) == {1, 3}
            assert got[1].version_no == 1
            assert got[3].version_no == 3
            assert got[1].summary == "summary v1"
            assert got[1].scope_in == ["in-a", "in-b"]

    @pytest.mark.asyncio
    async def test_gap_missing_version_is_absent_not_error(self, test_db):
        """A purged/missing version_no is simply absent (robust to gaps)."""
        async with test_db.processing_storage_session() as session:
            card_repo = SATopicCardRepo(session)
            ver_repo = SATopicCardVersionRepo(session)
            await card_repo.upsert(_make_card("topic:gap"))
            # v2 was reclaimed by retention → only v1 (genesis) and v5 exist.
            for vno in (1, 5):
                await _seed_version(session, topic_id="topic:gap", version_no=vno)

            got = await ver_repo.get_two_versions("topic:gap", 1, 2)

            # Genesis resolves; the gap (v2) is absent, no exception.
            assert set(got.keys()) == {1}
            assert 2 not in got

    @pytest.mark.asyncio
    async def test_both_missing_returns_empty(self, test_db):
        async with test_db.processing_storage_session() as session:
            card_repo = SATopicCardRepo(session)
            ver_repo = SATopicCardVersionRepo(session)
            await card_repo.upsert(_make_card("topic:none"))
            await _seed_version(session, topic_id="topic:none", version_no=1)

            got = await ver_repo.get_two_versions("topic:none", 7, 8)

            assert got == {}

    @pytest.mark.asyncio
    async def test_same_version_twice_returns_single_entry(self, test_db):
        async with test_db.processing_storage_session() as session:
            card_repo = SATopicCardRepo(session)
            ver_repo = SATopicCardVersionRepo(session)
            await card_repo.upsert(_make_card("topic:same"))
            await _seed_version(session, topic_id="topic:same", version_no=1)

            got = await ver_repo.get_two_versions("topic:same", 1, 1)

            assert set(got.keys()) == {1}
