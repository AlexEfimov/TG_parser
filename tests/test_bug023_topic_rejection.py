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


# ---------------------------------------------------------------------------
# T-6 — Early-rejection path ``no_valid_anchors_after_parsing`` counted
# ---------------------------------------------------------------------------


def test_build_topic_card_records_no_valid_anchors_after_parsing() -> None:
    """When raw anchors are present but ALL fail source_ref parsing
    (malformed format), the rejection must still be counted under
    ``no_valid_anchors_after_parsing`` — operators rely on this to spot
    LLM output format drift early."""
    pipeline = _make_pipeline()
    raw_topic = {
        "type": "cluster",
        "title": "Malformed anchors",
        "anchors": [
            {"source_ref": "not-a-valid-ref", "score": 0.9},
            {"source_ref": "tg:only:three", "score": 0.8},  # 3 parts, not 4
        ],
    }

    result = pipeline._build_topic_card(raw_topic, channel_id="ch", documents=[])

    assert result is None
    assert pipeline.rejection_breakdown == {"no_valid_anchors_after_parsing": 1}


# ---------------------------------------------------------------------------
# T-7 — Structured event truncates long titles to 80 chars
# ---------------------------------------------------------------------------


def test_record_rejection_truncates_title_to_80_chars(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Title is truncated to 80 chars in the structured event so log
    backends with line-length limits don't drop the rest of the fields.
    The aggregate counter is unaffected by length."""
    pipeline = _make_pipeline()
    long_title = "x" * 200

    with caplog.at_level(logging.INFO, logger="tg_parser.processing.topicization"):
        pipeline._record_rejection(reason="cluster_too_few_anchors", title=long_title, items=3)

    rejection_events = [
        rec for rec in caplog.records if "topic_failed_quality_criteria" in rec.getMessage()
    ]
    assert rejection_events, "expected the structured event to be emitted"

    msg = rejection_events[0].getMessage()
    # The exact 80 char title slice must appear; the 81st char must not.
    assert "x" * 80 in msg
    assert "x" * 81 not in msg
    # Aggregate counter is unaffected by truncation.
    assert pipeline.rejection_breakdown == {"cluster_too_few_anchors": 1}


# ---------------------------------------------------------------------------
# T-8 — IncrementalTopicizeResult defaults rejection_breakdown to {}
# ---------------------------------------------------------------------------


def test_incremental_topicize_result_defaults_to_empty_dict() -> None:
    """Backward-compat contract: callers that construct
    ``IncrementalTopicizeResult`` without ``rejection_breakdown`` (e.g.
    older test fixtures, third-party MCP consumers reconstructing the
    model) must still validate, with the field defaulting to an empty
    dict — never ``None``."""
    from tg_parser.domain.models import IncrementalTopicizeResult

    result = IncrementalTopicizeResult(
        channel_id="ch",
        candidates_count=0,
        assigned_keyword=[],
        assigned_llm=[],
        new_topics=[],
        unassignable=[],
        coverage_before=0.0,
        coverage_after=0.0,
        prompt_id="p",
        model_id="m",
        cross_channel_links_created=0,
    )

    assert result.rejection_breakdown == {}
    assert isinstance(result.rejection_breakdown, dict)

    # Explicit construction with a populated dict round-trips losslessly.
    explicit = IncrementalTopicizeResult(
        channel_id="ch",
        candidates_count=0,
        assigned_keyword=[],
        assigned_llm=[],
        new_topics=[],
        unassignable=[],
        coverage_before=0.0,
        coverage_after=0.0,
        prompt_id="p",
        model_id="m",
        cross_channel_links_created=0,
        rejection_breakdown={"cluster_too_few_anchors": 4},
    )
    assert explicit.rejection_breakdown == {"cluster_too_few_anchors": 4}


# ---------------------------------------------------------------------------
# T-9 — run_topicization surfaces rejection_breakdown in stats dict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_topicization_surfaces_rejection_breakdown_in_stats() -> None:
    """Service-layer ``run_topicization`` must copy
    ``pipeline.rejection_breakdown`` into its returned stats dict
    (defensively, via ``dict(...)``) so downstream consumers — CLI
    renderer, MCP tool result, future metrics — see the per-reason
    aggregate. The copy guarantees later mutation on the pipeline does
    not retroactively affect the returned dict."""
    from unittest.mock import patch

    from tg_parser.services import topicization_service

    fake_pipeline = AsyncMock()
    fake_pipeline.topicize_channel = AsyncMock(return_value=[])
    fake_pipeline.total_input_tokens = 0
    fake_pipeline.total_output_tokens = 0
    fake_pipeline.total_batches = 1
    fake_pipeline.failed_batches = 0
    fake_pipeline.last_batch_error = None
    fake_pipeline.rejection_breakdown = {
        "cluster_too_few_anchors": 4,
        "singleton_text_too_short": 2,
    }

    fake_processed_repo = AsyncMock()
    fake_processed_repo.list_by_channel = AsyncMock(return_value=[])
    fake_topic_card_repo = AsyncMock()
    fake_topic_card_repo.list_by_channel = AsyncMock(return_value=[])
    fake_topic_bundle_repo = AsyncMock()

    with patch.object(
        topicization_service,
        "TopicizationPipelineImpl",
        return_value=fake_pipeline,
    ):
        stats = await topicization_service.run_topicization(
            channel_id="ch",
            processed_repo=fake_processed_repo,
            topic_card_repo=fake_topic_card_repo,
            topic_bundle_repo=fake_topic_bundle_repo,
        )

    assert "rejection_breakdown" in stats
    assert stats["rejection_breakdown"] == {
        "cluster_too_few_anchors": 4,
        "singleton_text_too_short": 2,
    }
    # JSON-serializable contract (consumed by CLI / metrics / MCP).
    import json

    json.dumps(stats["rejection_breakdown"])

    # Defensive-copy guarantee: mutation on the pipeline instance does
    # not leak into the already-returned stats dict.
    fake_pipeline.rejection_breakdown["singleton_no_anchors"] = 99
    assert "singleton_no_anchors" not in stats["rejection_breakdown"]


# ---------------------------------------------------------------------------
# T-10 — CLI full-topicize path renders rejection breakdown summary
# ---------------------------------------------------------------------------


def test_cli_full_topicize_prints_rejection_breakdown() -> None:
    """The full-mode CLI renderer must surface the breakdown as «Quality
    filter rejected N topics: A by reason1, B by reason2, ...» sorted
    by reason alphabetically (stable across runs / log diffs)."""
    from unittest.mock import patch

    from typer.testing import CliRunner

    from tg_parser.cli.app import app

    fake_stats = {
        "topics_count": 3,
        "bundles_count": 3,
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
        "total_batches": 1,
        "failed_batches": 0,
        "last_batch_error": None,
        "total_documents": 50,
        "covered_documents": 30,
        "coverage_pct": 60.0,
        "uncovered_documents": 20,
        "rejection_breakdown": {
            "singleton_text_too_short": 2,
            "cluster_too_few_anchors": 4,
        },
    }

    async def _fake_run_topicization(**_kwargs: object) -> dict:
        return fake_stats

    runner = CliRunner()
    with patch(
        "tg_parser.cli.topicize_cmd.run_topicization",
        side_effect=_fake_run_topicization,
    ):
        result = runner.invoke(app, ["topicize", "--channel", "ch", "--mode", "full"])

    assert result.exit_code == 0, f"unexpected exit: {result.output}"
    out = result.output
    assert "Quality filter rejected 6 topics" in out
    # Alphabetic sort by reason → cluster_* comes before singleton_*.
    cluster_pos = out.find("4 by cluster_too_few_anchors")
    singleton_pos = out.find("2 by singleton_text_too_short")
    assert cluster_pos != -1, f"cluster reason not rendered: {out}"
    assert singleton_pos != -1, f"singleton reason not rendered: {out}"
    assert cluster_pos < singleton_pos, "breakdown must be sorted by reason"


# ---------------------------------------------------------------------------
# T-11 — CLI incremental-topicize path renders rejection breakdown
# ---------------------------------------------------------------------------


def test_cli_incremental_topicize_prints_rejection_breakdown() -> None:
    """The incremental CLI path uses the same ``_print_rejection_breakdown``
    helper via ``_print_incremental_stats`` — when the
    ``IncrementalTopicizeResult`` carries a non-empty breakdown, the
    same summary line must appear."""
    from unittest.mock import patch

    from typer.testing import CliRunner

    from tg_parser.cli.app import app
    from tg_parser.domain.models import IncrementalTopicizeResult

    fake_result = IncrementalTopicizeResult(
        channel_id="ch",
        candidates_count=10,
        assigned_keyword=[],
        assigned_llm=[],
        new_topics=[],
        unassignable=[],
        coverage_before=0.0,
        coverage_after=0.0,
        prompt_id="p",
        model_id="m",
        cross_channel_links_created=0,
        rejection_breakdown={"singleton_score_below_min": 3},
    )

    async def _fake_inc(**_kwargs: object):
        return fake_result

    runner = CliRunner()
    with patch(
        "tg_parser.cli.topicize_cmd.run_incremental_topicization_for_uncovered",
        side_effect=_fake_inc,
    ):
        result = runner.invoke(app, ["topicize", "--channel", "ch", "--mode", "incremental"])

    assert result.exit_code == 0, f"unexpected exit: {result.output}"
    assert "Quality filter rejected 3 topics" in result.output
    assert "3 by singleton_score_below_min" in result.output


# ---------------------------------------------------------------------------
# T-12 — _print_rejection_breakdown is a no-op on empty input
# ---------------------------------------------------------------------------


def test_cli_no_rejection_breakdown_line_when_empty() -> None:
    """When the pipeline produces zero rejections, the CLI must NOT
    print the «Quality filter rejected ...» line at all — operators
    rely on its absence to know there was no quality-filter activity."""
    from unittest.mock import patch

    from typer.testing import CliRunner

    from tg_parser.cli.app import app

    fake_stats = {
        "topics_count": 5,
        "bundles_count": 5,
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
        "total_batches": 1,
        "failed_batches": 0,
        "last_batch_error": None,
        "total_documents": 50,
        "covered_documents": 50,
        "coverage_pct": 100.0,
        "uncovered_documents": 0,
        "rejection_breakdown": {},
    }

    async def _fake_run_topicization(**_kwargs: object) -> dict:
        return fake_stats

    runner = CliRunner()
    with patch(
        "tg_parser.cli.topicize_cmd.run_topicization",
        side_effect=_fake_run_topicization,
    ):
        result = runner.invoke(app, ["topicize", "--channel", "ch", "--mode", "full"])

    assert result.exit_code == 0
    assert "Quality filter rejected" not in result.output
