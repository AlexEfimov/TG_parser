"""
Regression tests for BUG-018 — CLI ``tg-parser topicize`` exit code on
systemic LLM-batch failures.

Bug history: surfaced 2026-05-15 by the Claude MCP testing session
(Phase 5 manual topicization 2026-05-14 ~07:33 UTC). All 17 batches for
``kdl_ru`` failed with ``Your credit balance is too low to access the
Anthropic API``; CLI nonetheless printed ✅ and exited 0.

Closure contract:

1. Pipeline tracks ``failed_batches`` / ``total_batches`` / ``last_batch_error``
   on the ``TopicizationPipelineImpl`` instance.
2. ``run_topicization`` surfaces these in its returned stats dict.
3. CLI ``topicize`` exits with code 2 when ``failed_batches/total_batches > 0.5``
   (systemic-fail class), preserving the previous «exit 1 on top-level
   exception» path for the single-batch case where the exception still
   propagates unchanged.
4. Partial-fail (≤50 % errored) stays exit 0 with a warning summary.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from tg_parser.cli.app import app
from tg_parser.domain.models import ProcessedDocument
from tg_parser.processing.topicization import TopicizationPipelineImpl

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers — mirror the minimal shape used in tests/test_topicization.py
# ---------------------------------------------------------------------------


def _make_doc(idx: int, channel_id: str = "kdl_ru") -> ProcessedDocument:
    source_ref = f"tg:{channel_id}:post:{idx}"
    return ProcessedDocument(
        id=f"doc:{source_ref}",
        source_ref=source_ref,
        source_message_id=str(idx),
        channel_id=channel_id,
        processed_at=datetime.now(UTC),
        text_clean=f"sample text {idx} " * 30,
        summary=f"summary {idx}",
        topics=["sample"],
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


# ---------------------------------------------------------------------------
# T-1 — pipeline counts failed multi-batch errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topicize_channel_counts_all_batches_failed() -> None:
    """If every batch raises, ``failed_batches == total_batches`` and the
    first error class is captured in ``last_batch_error``."""

    pipeline = _make_pipeline()

    # Generate enough docs to force the multi-batch (>50) path so we
    # exercise the ``return_exceptions=True`` aggregation site.
    docs = [_make_doc(i) for i in range(120)]
    pipeline.processed_doc_repo.list_by_channel = AsyncMock(return_value=docs)

    async def _always_fail(_batch: list[dict]) -> list[dict]:
        raise RuntimeError("Your credit balance is too low to access the Anthropic API")

    with patch.object(pipeline, "_generate_topics_batch", side_effect=_always_fail):
        topic_cards = await pipeline.topicize_channel(channel_id="kdl_ru")

    assert topic_cards == []
    assert pipeline.total_batches >= 2
    assert pipeline.failed_batches == pipeline.total_batches
    assert pipeline.last_batch_error is not None
    assert "credit balance" in pipeline.last_batch_error
    assert "RuntimeError" in pipeline.last_batch_error


# ---------------------------------------------------------------------------
# T-2 — pipeline counts partial failures separately from successes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topicize_channel_partial_failure_records_partial_count() -> None:
    """When only some batches error, the counter reflects the partial ratio
    and successful batches still contribute topics."""

    pipeline = _make_pipeline()
    docs = [_make_doc(i) for i in range(120)]
    pipeline.processed_doc_repo.list_by_channel = AsyncMock(return_value=docs)

    call_state = {"count": 0}

    async def _flaky(batch: list[dict]) -> list[dict]:
        call_state["count"] += 1
        if call_state["count"] == 1:
            raise RuntimeError("transient")
        return []

    with (
        patch.object(pipeline, "_generate_topics_batch", side_effect=_flaky),
        patch.object(pipeline, "_merge_topics", AsyncMock(return_value=[])),
    ):
        await pipeline.topicize_channel(channel_id="kdl_ru")

    assert pipeline.total_batches >= 2
    assert pipeline.failed_batches == 1
    assert pipeline.last_batch_error is not None


# ---------------------------------------------------------------------------
# T-3 — pipeline state resets between invocations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topicize_channel_resets_counters_between_runs() -> None:
    """A second invocation must not inherit ``failed_batches`` from the
    first — the per-channel state lives on the pipeline instance."""

    pipeline = _make_pipeline()
    docs = [_make_doc(i) for i in range(120)]
    pipeline.processed_doc_repo.list_by_channel = AsyncMock(return_value=docs)

    async def _always_fail(_batch: list[dict]) -> list[dict]:
        raise RuntimeError("boom")

    with patch.object(pipeline, "_generate_topics_batch", side_effect=_always_fail):
        await pipeline.topicize_channel(channel_id="kdl_ru")

    pipeline.processed_doc_repo.list_by_channel = AsyncMock(return_value=[])
    await pipeline.topicize_channel(channel_id="kdl_ru")

    assert pipeline.total_batches == 0
    assert pipeline.failed_batches == 0
    assert pipeline.last_batch_error is None


# ---------------------------------------------------------------------------
# T-4 — CLI exits with code 2 on systemic batch failure
# ---------------------------------------------------------------------------


def test_cli_topicize_exits_non_zero_on_systemic_failure() -> None:
    """Mock ``run_topicization`` to simulate 17/17 batches errored. The CLI
    must exit non-zero (code 2) and surface the first error class so
    automation scripts can distinguish systemic failure from «no data»."""

    fake_stats = {
        "topics_count": 0,
        "bundles_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "total_batches": 17,
        "failed_batches": 17,
        "last_batch_error": (
            "RuntimeError: Your credit balance is too low to access the Anthropic API"
        ),
        "total_documents": 841,
        "covered_documents": 0,
        "coverage_pct": 0.0,
        "uncovered_documents": 841,
    }

    async def _fake_run_topicization(**_kwargs: object) -> dict:
        return fake_stats

    with patch(
        "tg_parser.cli.topicize_cmd.run_topicization",
        side_effect=_fake_run_topicization,
    ):
        result = runner.invoke(
            app,
            ["topicize", "--channel", "kdl_ru", "--mode", "full"],
        )

    assert result.exit_code == 2, (
        f"expected exit code 2 on systemic batch failure, got {result.exit_code}.\n"
        f"output={result.output}"
    )

    combined = result.output
    assert "17/17" in combined
    assert "aborted" in combined.lower() or "failed" in combined.lower()
    assert "credit balance" in combined
    # The misleading «возможно, недостаточно данных» line must NOT appear
    # when batch failures are the actual cause.
    assert "недостаточно данных" not in combined


# ---------------------------------------------------------------------------
# T-5 — CLI stays exit 0 on partial-fail (≤50% errored)
# ---------------------------------------------------------------------------


def test_cli_topicize_partial_failure_exits_zero_with_warning() -> None:
    """Partial fail (e.g. 3/17 errored, 14 succeeded with topics created) is
    NOT a systemic failure — the CLI exits 0 but prints a warning summary."""

    fake_stats = {
        "topics_count": 12,
        "bundles_count": 12,
        "input_tokens": 1000,
        "output_tokens": 500,
        "total_tokens": 1500,
        "total_batches": 17,
        "failed_batches": 3,
        "last_batch_error": "RuntimeError: transient 520",
        "total_documents": 841,
        "covered_documents": 600,
        "coverage_pct": 71.3,
        "uncovered_documents": 241,
    }

    async def _fake_run_topicization(**_kwargs: object) -> dict:
        return fake_stats

    with patch(
        "tg_parser.cli.topicize_cmd.run_topicization",
        side_effect=_fake_run_topicization,
    ):
        result = runner.invoke(
            app,
            ["topicize", "--channel", "kdl_ru", "--mode", "full"],
        )

    assert result.exit_code == 0, (
        f"expected exit code 0 on partial fail, got {result.exit_code}.\noutput={result.output}"
    )
    combined = result.output
    assert "3/17" in combined
    assert "Topicization завершён" in combined


# ---------------------------------------------------------------------------
# T-6 — CLI still exits 0 with «недостаточно данных» when truly no data
# ---------------------------------------------------------------------------


def test_cli_topicize_no_data_still_exits_zero() -> None:
    """If 0 topics and 0 batches failed (no batches were ever attempted —
    e.g. empty channel), preserve the legacy «недостаточно данных» hint
    and exit 0. This is genuinely a «no data» case, not a systemic fail."""

    fake_stats = {
        "topics_count": 0,
        "bundles_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "total_batches": 0,
        "failed_batches": 0,
        "last_batch_error": None,
        "total_documents": 0,
        "covered_documents": 0,
        "coverage_pct": 0.0,
        "uncovered_documents": 0,
    }

    async def _fake_run_topicization(**_kwargs: object) -> dict:
        return fake_stats

    with patch(
        "tg_parser.cli.topicize_cmd.run_topicization",
        side_effect=_fake_run_topicization,
    ):
        result = runner.invoke(
            app,
            ["topicize", "--channel", "empty_channel", "--mode", "full"],
        )

    assert result.exit_code == 0
    combined = result.output
    assert "недостаточно данных" in combined
