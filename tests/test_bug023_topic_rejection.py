"""
Regression tests for BUG-023 — silent topic-quality rejection (no name /
reason / aggregate count logged).

Bug history: surfaced 2026-05-15 by the Claude MCP testing session
(Phase 8 mass incremental topicization 2026-05-14). The original log
emitted ``"Topic failed quality criteria, skipping"`` with zero
structured fields — no proposed title, no specific criterion, no
aggregate at end of run. Operators noting low coverage for a channel
could not understand WHY their candidate topics were rejected.

Closure contract:

1. ``TopicizationPipelineImpl._validate_quality`` returns ``(valid, reason)``
   where ``reason`` is one of: ``singleton_no_anchors`` /
   ``singleton_score_below_min`` / ``singleton_doc_not_found`` /
   ``singleton_text_too_short`` / ``cluster_too_few_anchors`` /
   ``cluster_anchor_score_below_min``.
2. ``_build_topic_card`` records every rejection via
   ``_record_rejection``: structured log event
   ``topic_failed_quality_criteria`` with ``reason`` / ``title`` /
   ``items`` fields, plus aggregate increment on
   ``self.rejection_breakdown[reason]``.
3. ``run_topicization`` surfaces ``rejection_breakdown`` in its stats
   dict; ``IncrementalTopicizeResult.rejection_breakdown`` mirrors the
   same shape for the incremental path.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_parser.domain.models import (
    Anchor,
    MessageType,
    ProcessedDocument,
    TopicType,
)
from tg_parser.processing.topicization import (
    MIN_CLUSTER_SCORE,
    MIN_SINGLETON_LENGTH,
    MIN_SINGLETON_SCORE,
    TopicizationPipelineImpl,
)


def _make_pipeline() -> TopicizationPipelineImpl:
    llm = AsyncMock()
    llm.model = "test-model"
    llm.compute_prompt_id = MagicMock(return_value="test-prompt-id")
    return TopicizationPipelineImpl(
        llm_client=llm,
        processed_doc_repo=AsyncMock(),
        topic_card_repo=AsyncMock(),
        topic_bundle_repo=AsyncMock(),
    )


def _make_anchor(score: float = 0.9, source_ref: str = "tg:ch:post:1") -> Anchor:
    parts = source_ref.split(":")
    return Anchor(
        channel_id=parts[1],
        message_id=parts[3],
        message_type=MessageType(parts[2]),
        anchor_ref=source_ref,
        score=score,
    )


# ---------------------------------------------------------------------------
# T-1 — _validate_quality returns (valid, reason) tuple
# ---------------------------------------------------------------------------


class TestValidateQualityReason:
    """``_validate_quality`` now returns a ``(valid, reason)`` tuple so the
    caller can attribute each rejection to a specific criterion."""

    def test_cluster_passes_returns_true_none(self) -> None:
        pipeline = _make_pipeline()
        anchors = [_make_anchor(0.9, "tg:ch:post:1"), _make_anchor(0.9, "tg:ch:post:2")]
        valid, reason = pipeline._validate_quality(anchors, TopicType.CLUSTER, documents=[])
        assert valid is True
        assert reason is None

    def test_cluster_too_few_anchors_returns_reason(self) -> None:
        pipeline = _make_pipeline()
        valid, reason = pipeline._validate_quality(
            [_make_anchor(0.9)], TopicType.CLUSTER, documents=[]
        )
        assert valid is False
        assert reason == "cluster_too_few_anchors"

    def test_cluster_anchor_score_below_min_returns_reason(self) -> None:
        pipeline = _make_pipeline()
        score = max(0.0, MIN_CLUSTER_SCORE - 0.1)
        anchors = [
            _make_anchor(score, "tg:ch:post:1"),
            _make_anchor(score, "tg:ch:post:2"),
        ]
        valid, reason = pipeline._validate_quality(anchors, TopicType.CLUSTER, documents=[])
        assert valid is False
        assert reason == "cluster_anchor_score_below_min"

    def test_singleton_no_anchors_returns_reason(self) -> None:
        pipeline = _make_pipeline()
        valid, reason = pipeline._validate_quality([], TopicType.SINGLETON, documents=[])
        assert valid is False
        assert reason == "singleton_no_anchors"

    def test_singleton_score_below_min_returns_reason(self) -> None:
        pipeline = _make_pipeline()
        anchor = _make_anchor(max(0.0, MIN_SINGLETON_SCORE - 0.1))
        valid, reason = pipeline._validate_quality([anchor], TopicType.SINGLETON, documents=[])
        assert valid is False
        assert reason == "singleton_score_below_min"

    def test_singleton_doc_not_found_returns_reason(self) -> None:
        pipeline = _make_pipeline()
        anchor = _make_anchor(min(1.0, MIN_SINGLETON_SCORE + 0.1))
        valid, reason = pipeline._validate_quality([anchor], TopicType.SINGLETON, documents=[])
        assert valid is False
        assert reason == "singleton_doc_not_found"

    def test_singleton_text_too_short_returns_reason(self) -> None:
        pipeline = _make_pipeline()
        anchor = _make_anchor(min(1.0, MIN_SINGLETON_SCORE + 0.1), "tg:ch:post:1")
        doc = ProcessedDocument(
            id="doc:tg:ch:post:1",
            source_ref="tg:ch:post:1",
            source_message_id="1",
            channel_id="ch",
            processed_at=datetime.now(UTC),
            text_clean="x" * max(1, MIN_SINGLETON_LENGTH - 1),
            summary="s",
            topics=[],
        )
        valid, reason = pipeline._validate_quality([anchor], TopicType.SINGLETON, documents=[doc])
        assert valid is False
        assert reason == "singleton_text_too_short"


# ---------------------------------------------------------------------------
# T-2 — _record_rejection increments aggregate counter
# ---------------------------------------------------------------------------


def test_record_rejection_increments_breakdown() -> None:
    """``_record_rejection`` must increment the per-reason counter and not
    leak state across instances."""
    pipeline = _make_pipeline()
    assert pipeline.rejection_breakdown == {}

    pipeline._record_rejection(reason="cluster_too_few_anchors", title="A", items=1)
    pipeline._record_rejection(reason="cluster_too_few_anchors", title="B", items=1)
    pipeline._record_rejection(reason="singleton_text_too_short", title="C", items=1)

    assert pipeline.rejection_breakdown == {
        "cluster_too_few_anchors": 2,
        "singleton_text_too_short": 1,
    }


# ---------------------------------------------------------------------------
# T-3 — _build_topic_card records rejection events with structured fields
# ---------------------------------------------------------------------------


def test_build_topic_card_logs_structured_rejection_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A rejected topic must emit a ``topic_failed_quality_criteria`` event
    with ``reason`` / ``title`` / ``items`` fields, NOT the legacy opaque
    ``"Topic failed quality criteria, skipping"`` line."""
    pipeline = _make_pipeline()

    raw_topic = {
        "type": "cluster",
        "title": "Insufficient cluster",
        "summary": "only one anchor",
        "anchors": [{"source_ref": "tg:ch:post:1", "score": 0.9}],
    }

    with caplog.at_level(logging.INFO, logger="tg_parser.processing.topicization"):
        result = pipeline._build_topic_card(raw_topic, channel_id="ch", documents=[])

    assert result is None
    assert pipeline.rejection_breakdown == {"cluster_too_few_anchors": 1}

    rejection_events = [
        rec for rec in caplog.records if "topic_failed_quality_criteria" in rec.getMessage()
    ]
    assert rejection_events, (
        "expected at least one ``topic_failed_quality_criteria`` structured "
        "log event after rejection"
    )

    msg = rejection_events[0].getMessage()
    assert "cluster_too_few_anchors" in msg
    assert "Insufficient cluster" in msg

    legacy_lines = [
        rec
        for rec in caplog.records
        if "Topic failed quality criteria, skipping" in rec.getMessage()
    ]
    assert not legacy_lines, (
        "the opaque ``Topic failed quality criteria, skipping`` line must "
        "be replaced by the structured event (BUG-023)"
    )


# ---------------------------------------------------------------------------
# T-4 — _build_topic_card tracks early-rejection paths (no anchors)
# ---------------------------------------------------------------------------


def test_build_topic_card_records_no_raw_anchors_rejection() -> None:
    """Topics with zero raw anchors must still be counted in the breakdown
    so operators can see early-stage rejections too."""
    pipeline = _make_pipeline()
    raw_topic = {"type": "cluster", "title": "No anchors topic", "anchors": []}
    result = pipeline._build_topic_card(raw_topic, channel_id="ch", documents=[])
    assert result is None
    assert pipeline.rejection_breakdown == {"no_raw_anchors": 1}


# ---------------------------------------------------------------------------
# T-5 — rejection_breakdown resets on each topicize_channel invocation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejection_breakdown_resets_between_runs() -> None:
    """``rejection_breakdown`` must reset at the top of each
    ``topicize_channel`` invocation so state does not leak between
    channels processed on the same pipeline instance."""
    pipeline = _make_pipeline()
    pipeline.rejection_breakdown = {"cluster_too_few_anchors": 7}
    pipeline.processed_doc_repo.list_by_channel = AsyncMock(return_value=[])

    await pipeline.topicize_channel(channel_id="any_channel")

    assert pipeline.rejection_breakdown == {}
