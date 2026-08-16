"""BUG-098 (b) — coverage_counts_by_channel keeps §2.1 semantics after the rewrite.

The hash-join rewrite must still match the old per-channel rule:

* a processed document ``(channel_id=C, source_ref=S)`` is covered iff ``S``
  appears in an **active** bundle (``time_from`` / ``time_to`` both NULL) that
  either lists ``C`` in ``channels_json`` or has ``channels_json IS NULL``;
* snapshot bundles do not count;
* a named bundle for another channel does not inflate this channel's count.

Gated by ``TEST_POSTGRES=1``. Honesty-marker tests (BUG-066 / BUG-098a) stay
untouched: they assert the timeout fallback, not this SQL.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from tg_parser.domain.models import (
    BundleItem,
    BundleItemRole,
    MessageType,
    ProcessedDocument,
    TimeRange,
    TopicBundle,
)
from tg_parser.storage.sqlalchemy.processed_document_repo import SAProcessedDocumentRepo
from tg_parser.storage.sqlalchemy.topic_bundle_repo import SATopicBundleRepo

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)

_NOW = datetime(2026, 8, 16, 12, 0, 0, tzinfo=UTC)
_CHA = "bug098b_a"
_CHB = "bug098b_b"


def _ref(channel_id: str, n: int) -> str:
    return f"tg:{channel_id}:post:{n}"


def _doc(channel_id: str, n: int) -> ProcessedDocument:
    source_ref = _ref(channel_id, n)
    return ProcessedDocument(
        id=f"doc:{source_ref}",
        source_ref=source_ref,
        source_message_id=str(n),
        channel_id=channel_id,
        processed_at=_NOW,
        text_clean=f"clean {source_ref}",
    )


def _item(channel_id: str, n: int) -> BundleItem:
    return BundleItem(
        channel_id=channel_id,
        message_id=str(n),
        message_type=MessageType.POST,
        source_ref=_ref(channel_id, n),
        role=BundleItemRole.SUPPORTING,
    )


@pg_only
@pytest.mark.asyncio
async def test_coverage_counts_active_named_null_and_snapshot(test_db):
    async with test_db.processing_storage_session() as session:
        docs = SAProcessedDocumentRepo(session)
        bundles = SATopicBundleRepo(session)

        for n in (1, 2, 3, 4):
            await docs.upsert(_doc(_CHA, n))
        for n in (1, 2):
            await docs.upsert(_doc(_CHB, n))

        # Named active bundle for A: covers A:1. A:99 is not processed → ignored.
        # B:1 in an A-named bundle must not cover B (channel must match).
        await bundles.upsert(
            TopicBundle(
                topic_id="topic:tg:bug098b_a:post:1",
                items=[_item(_CHA, 1), _item(_CHA, 99), _item(_CHB, 1)],
                updated_at=_NOW,
                channels=[_CHA],
            )
        )
        # Channel-agnostic active bundle: A:2 and B:2 count for their own channels.
        await bundles.upsert(
            TopicBundle(
                topic_id="topic:tg:bug098b_a:post:2",
                items=[_item(_CHA, 2), _item(_CHB, 2)],
                updated_at=_NOW,
                channels=None,
            )
        )
        # Snapshot covering A:3 — must not count.
        await bundles.upsert(
            TopicBundle(
                topic_id="topic:tg:bug098b_a:post:3",
                items=[_item(_CHA, 3)],
                updated_at=_NOW,
                channels=[_CHA],
                time_range=TimeRange.model_validate(
                    {
                        "from": datetime(2026, 1, 1, tzinfo=UTC),
                        "to": datetime(2026, 1, 31, tzinfo=UTC),
                    }
                ),
            )
        )

        counts = await docs.coverage_counts_by_channel()

    assert counts.get(_CHA) == 2  # A:1 named + A:2 agnostic; A:3 snapshot; A:4 uncovered
    assert counts.get(_CHB) == 1  # B:2 agnostic only; B:1 is in an A-named bundle
    assert _CHA in counts
    assert counts.get(_CHA, 0) != 3
