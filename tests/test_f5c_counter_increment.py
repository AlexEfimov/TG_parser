"""F5-C counter increment integration test.

Verifies that ``_update_bundles_for_assignments`` bumps
``topic_cards.new_items_since_last_summary`` once per add_items batch
when ``topic_card_repo`` is provided.  This is the F5-C trigger point
in the topicization pipeline (Step 5 in START_PROMPT_SPRINT_F5C.md).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tg_parser.domain.models import (
    Anchor,
    BundleItem,
    BundleItemRole,
    MessageType,
    TopicBundle,
    TopicCard,
    TopicType,
)
from tg_parser.services.topicization_service import _update_bundles_for_assignments
from tg_parser.storage.sqlalchemy.topic_bundle_repo import SATopicBundleRepo
from tg_parser.storage.sqlalchemy.topic_card_repo import SATopicCardRepo

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


def _make_doc(source_ref: str):
    """Lightweight stand-in for ProcessedDocument used by _update_bundles_for_assignments."""
    return SimpleNamespace(source_ref=source_ref)


@pg_only
@pytest.mark.asyncio
async def test_counter_bumps_on_add_items(test_db):
    async with test_db.processing_storage_session() as session:
        card_repo = SATopicCardRepo(session)
        bundle_repo = SATopicBundleRepo(session)

        card = TopicCard(
            id="topic:tg:ch:post:1",
            title="T",
            summary="S",
            scope_in=["a"],
            scope_out=["b"],
            type=TopicType.SINGLETON,
            anchors=[
                Anchor(
                    channel_id="ch",
                    message_id="1",
                    message_type=MessageType.POST,
                    anchor_ref="tg:ch:post:1",
                    score=1.0,
                )
            ],
            sources=["ch"],
            updated_at=datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC),
        )
        await card_repo.upsert(card)
        # Bundle starts with one anchor item (required by min_length=1).
        await bundle_repo.upsert(
            TopicBundle(
                topic_id=card.id,
                items=[
                    BundleItem(
                        channel_id="ch",
                        message_id="1",
                        message_type=MessageType.POST,
                        source_ref="tg:ch:post:1",
                        role=BundleItemRole.ANCHOR,
                        score=1.0,
                    )
                ],
                updated_at=datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC),
            )
        )

        assignments = [
            SimpleNamespace(topic_id=card.id, source_ref="tg:ch:post:2", score=0.7),
            SimpleNamespace(topic_id=card.id, source_ref="tg:ch:post:3", score=0.6),
            SimpleNamespace(topic_id=card.id, source_ref="tg:ch:post:4", score=0.5),
        ]
        docs_by_ref = {a.source_ref: _make_doc(a.source_ref) for a in assignments}

        await _update_bundles_for_assignments(
            assignments,
            docs_by_ref,
            bundle_repo,
            method="keyword",
            topic_card_repo=card_repo,
        )

        fetched = await card_repo.get_by_id(card.id)
        assert fetched is not None
        assert fetched.new_items_since_last_summary == 3


@pg_only
@pytest.mark.asyncio
async def test_counter_does_not_bump_when_add_items_fails(test_db):
    """Gotcha #1: counter increment must run AFTER ``add_items``.  If
    ``add_items`` raises (e.g. bundle missing → ``ValueError``), the
    counter must stay at its pre-batch value so we don't trigger a
    re-summarize against a bundle that never received the items.

    The production code in ``_update_bundles_for_assignments`` puts the
    increment inside the same ``try`` block so a raise short-circuits the
    bump (the ``except ValueError`` log handles it).  This test pins
    that ordering."""
    async with test_db.processing_storage_session() as session:
        card_repo = SATopicCardRepo(session)
        bundle_repo = SATopicBundleRepo(session)

        card = TopicCard(
            id="topic:tg:ch:post:5",
            title="T",
            summary="S",
            scope_in=["a"],
            scope_out=["b"],
            type=TopicType.SINGLETON,
            anchors=[
                Anchor(
                    channel_id="ch",
                    message_id="5",
                    message_type=MessageType.POST,
                    anchor_ref="tg:ch:post:5",
                    score=1.0,
                )
            ],
            sources=["ch"],
            updated_at=datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC),
        )
        await card_repo.upsert(card)
        # Deliberately do NOT upsert the bundle — add_items raises
        # ValueError("Bundle not found for topic ...") which the
        # production caller logs and swallows.

        assignments = [
            SimpleNamespace(topic_id=card.id, source_ref="tg:ch:post:6", score=0.5),
            SimpleNamespace(topic_id=card.id, source_ref="tg:ch:post:7", score=0.4),
        ]
        docs_by_ref = {a.source_ref: _make_doc(a.source_ref) for a in assignments}

        await _update_bundles_for_assignments(
            assignments,
            docs_by_ref,
            bundle_repo,
            method="keyword",
            topic_card_repo=card_repo,
        )

        fetched = await card_repo.get_by_id(card.id)
        assert fetched is not None
        # Counter must still be 0 — bundle add failed, so no F5-C signal.
        assert fetched.new_items_since_last_summary == 0


@pg_only
@pytest.mark.asyncio
async def test_counter_no_bump_when_card_repo_omitted(test_db):
    """Backward compatibility: legacy callers without topic_card_repo
    keyword should NOT bump the counter (no AttributeError, no surprise)."""
    async with test_db.processing_storage_session() as session:
        card_repo = SATopicCardRepo(session)
        bundle_repo = SATopicBundleRepo(session)

        card = TopicCard(
            id="topic:tg:ch:post:9",
            title="T",
            summary="S",
            scope_in=["a"],
            scope_out=["b"],
            type=TopicType.SINGLETON,
            anchors=[
                Anchor(
                    channel_id="ch",
                    message_id="9",
                    message_type=MessageType.POST,
                    anchor_ref="tg:ch:post:9",
                    score=1.0,
                )
            ],
            sources=["ch"],
            updated_at=datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC),
        )
        await card_repo.upsert(card)
        await bundle_repo.upsert(
            TopicBundle(
                topic_id=card.id,
                items=[
                    BundleItem(
                        channel_id="ch",
                        message_id="9",
                        message_type=MessageType.POST,
                        source_ref="tg:ch:post:9",
                        role=BundleItemRole.ANCHOR,
                        score=1.0,
                    )
                ],
                updated_at=datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC),
            )
        )

        assignments = [
            SimpleNamespace(topic_id=card.id, source_ref="tg:ch:post:10", score=0.5),
        ]
        docs_by_ref = {"tg:ch:post:10": _make_doc("tg:ch:post:10")}
        await _update_bundles_for_assignments(
            assignments,
            docs_by_ref,
            bundle_repo,
            method="keyword",
            # topic_card_repo intentionally omitted.
        )

        fetched = await card_repo.get_by_id(card.id)
        assert fetched is not None
        assert fetched.new_items_since_last_summary == 0
