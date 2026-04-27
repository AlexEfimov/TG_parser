"""
Tests for the incremental-pipeline scheduler service (Session 30).

Tests cover:
- run_incremental_for_all_sources: iterate sources, run pipeline, record attempts
- Retopicization threshold logic
- Error isolation between sources
- get_scheduler_status
- BackgroundScheduler integration with incremental_pipeline_task
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from tg_parser.storage.ports import Source

# ============================================================================
# Helpers
# ============================================================================


def _mock_ingestion_and_processing_repos(state_repo, processed_repo):
    """Create a mock async context manager for ingestion_and_processing_repos."""

    @asynccontextmanager
    async def _cm():
        mock_db = MagicMock()
        mock_db.close = AsyncMock()
        yield state_repo, processed_repo, mock_db

    return _cm


def _mock_ingestion_state_repo(state_repo):
    """Create a mock async context manager for ingestion_state_repo."""

    @asynccontextmanager
    async def _cm():
        mock_db = MagicMock()
        mock_db.close = AsyncMock()
        yield state_repo, mock_db

    return _cm


def _ok_incr_result():
    """Build an :class:`IncrementalTopicizeResult` representing a successful tick.

    Lazy-import inside the helper so that test files that don't need the
    domain model (e.g., the helper-only unit tests) don't pay the import
    cost. Used by TD-05 watchlist-billing tests.
    """
    from tg_parser.domain.models import IncrementalTopicizeResult

    return IncrementalTopicizeResult(
        assigned_keyword=[],
        unassignable=[],
        coverage_before=0.0,
        coverage_after=0.0,
    )


# ============================================================================
# Tests: run_incremental_for_all_sources
# ============================================================================


@pytest.mark.asyncio
async def test_no_active_sources_returns_zero():
    """With no active sources the function returns immediately."""
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = []

    with patch(
        "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
        _mock_ingestion_and_processing_repos(mock_state_repo, AsyncMock()),
    ):
        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert result["sources_total"] == 0
    assert result["sources_succeeded"] == 0
    assert result["sources_failed"] == 0


@pytest.mark.asyncio
async def test_single_source_success():
    """One active source processes successfully."""
    source = Source(
        source_id="s1",
        channel_id="ch1",
        status="active",
        include_comments=False,
    )

    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]
    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_by_channel.return_value = []

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, mock_processed_repo),
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion", new_callable=AsyncMock
        ) as mock_ingest,
        patch(
            "tg_parser.services.pipeline_service.run_processing", new_callable=AsyncMock
        ) as mock_process,
        patch(
            "tg_parser.services.pipeline_service.run_export", new_callable=AsyncMock
        ) as mock_export,
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch1",
        ),
    ):
        mock_ingest.return_value = {
            "posts_collected": 3,
            "comments_collected": 0,
            "errors": 0,
            "duration_seconds": 0.5,
        }
        mock_process.return_value = {
            "processed_count": 3,
            "skipped_count": 0,
            "failed_count": 0,
            "total_count": 3,
        }
        mock_export.return_value = {"kb_entries_count": 3, "topics_count": 0, "channels_count": 1}

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert result["sources_total"] == 1
    assert result["sources_succeeded"] == 1
    assert result["sources_failed"] == 0
    assert result["total_new_messages"] == 3

    mock_state_repo.record_attempt.assert_awaited_once()
    attempt_kwargs = mock_state_repo.record_attempt.call_args.kwargs
    assert attempt_kwargs["success"] is True
    assert attempt_kwargs["details"]["trigger"] == "scheduled"


@pytest.mark.asyncio
async def test_source_failure_does_not_block_others():
    """If one source fails, the other still runs."""
    source_ok = Source(source_id="ok", channel_id="ch_ok", status="active", include_comments=False)
    source_fail = Source(
        source_id="fail", channel_id="ch_fail", status="active", include_comments=False
    )

    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source_fail, source_ok]
    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_by_channel.return_value = []

    ok_ingest = {
        "posts_collected": 1,
        "comments_collected": 0,
        "errors": 0,
        "duration_seconds": 0.1,
    }
    ok_process = {"processed_count": 1, "skipped_count": 0, "failed_count": 0, "total_count": 1}
    ok_export = {"kb_entries_count": 1, "topics_count": 0, "channels_count": 1}

    async def mock_ingest_side_effect(**kwargs):
        source_id = kwargs.get("source_id", "")
        if source_id == "fail":
            raise RuntimeError("Telegram FloodWait")
        return ok_ingest

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, mock_processed_repo),
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion",
            new_callable=AsyncMock,
            side_effect=mock_ingest_side_effect,
        ),
        patch(
            "tg_parser.services.pipeline_service.run_processing",
            new_callable=AsyncMock,
            return_value=ok_process,
        ),
        patch(
            "tg_parser.services.pipeline_service.run_export",
            new_callable=AsyncMock,
            return_value=ok_export,
        ),
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch_ok",
        ),
    ):
        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert result["sources_succeeded"] == 1
    assert result["sources_failed"] == 1
    assert "fail" in result["errors"]
    assert "FloodWait" in result["errors"]["fail"]


@pytest.mark.asyncio
async def test_incremental_topicize_triggers_on_new_docs():
    """Session 35: When new docs appear, incremental topicization is triggered."""
    source = Source(source_id="s1", channel_id="ch1", status="active", include_comments=False)

    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]

    mock_processed_repo = AsyncMock()

    doc_before: list = []
    doc_after = [MagicMock(source_ref=f"tg:ch1:post:{i}") for i in range(5)]

    call_count = 0

    async def list_by_channel_side_effect(channel_id):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return doc_before
        return doc_after

    mock_processed_repo.list_by_channel.side_effect = list_by_channel_side_effect

    from tg_parser.domain.models import IncrementalTopicizeResult

    mock_incr_result = IncrementalTopicizeResult(
        assigned_keyword=[],
        unassignable=[],
        coverage_before=77.0,
        coverage_after=78.0,
    )

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, mock_processed_repo),
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion",
            new_callable=AsyncMock,
            return_value={
                "posts_collected": 5,
                "comments_collected": 0,
                "errors": 0,
                "duration_seconds": 0.5,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_processing",
            new_callable=AsyncMock,
            return_value={
                "processed_count": 5,
                "skipped_count": 0,
                "failed_count": 0,
                "total_count": 5,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_export",
            new_callable=AsyncMock,
            return_value={"kb_entries_count": 5, "topics_count": 0, "channels_count": 1},
        ),
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch1",
        ),
        patch(
            "tg_parser.services.topicization_service.run_incremental_topicization",
            new_callable=AsyncMock,
            return_value=mock_incr_result,
        ) as mock_incr_topicize,
        patch("tg_parser.services.scheduler_service.settings") as mock_settings,
    ):
        mock_settings.scheduler_retopicize_threshold = 3
        mock_settings.scheduler_max_concurrent_sources = 1

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    mock_incr_topicize.assert_awaited_once()
    call_args = mock_incr_topicize.call_args
    assert call_args[0][0] == "ch1"
    assert len(call_args[0][1]) == 5
    assert "s1" in result["retopicized_sources"]


@pytest.mark.asyncio
async def test_incremental_topicize_skipped_when_no_new_docs():
    """Session 35: When no new docs appear, incremental topicization is not triggered."""
    source = Source(source_id="s1", channel_id="ch1", status="active", include_comments=False)

    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]

    mock_processed_repo = AsyncMock()
    existing_doc = MagicMock(source_ref="tg:ch1:post:1")
    mock_processed_repo.list_by_channel.return_value = [existing_doc]

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, mock_processed_repo),
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion",
            new_callable=AsyncMock,
            return_value={
                "posts_collected": 0,
                "comments_collected": 0,
                "errors": 0,
                "duration_seconds": 0.1,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_processing",
            new_callable=AsyncMock,
            return_value={
                "processed_count": 0,
                "skipped_count": 1,
                "failed_count": 0,
                "total_count": 1,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_export",
            new_callable=AsyncMock,
            return_value={"kb_entries_count": 0, "topics_count": 0, "channels_count": 1},
        ),
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch1",
        ),
        patch(
            "tg_parser.services.topicization_service.run_incremental_topicization",
            new_callable=AsyncMock,
        ) as mock_incr_topicize,
        patch("tg_parser.services.scheduler_service.settings") as mock_settings,
    ):
        mock_settings.scheduler_retopicize_threshold = 10
        mock_settings.scheduler_max_concurrent_sources = 1

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    mock_incr_topicize.assert_not_awaited()
    assert result["retopicized_sources"] == []


# ============================================================================
# Tests: get_scheduler_status
# ============================================================================


@pytest.mark.asyncio
async def test_get_scheduler_status():
    """Status returns source list with expected fields."""
    source = Source(
        source_id="s1",
        channel_id="ch1",
        status="active",
        include_comments=True,
        poll_interval_seconds=1800,
        last_success_at=datetime(2026, 3, 22, 10, 0, 0, tzinfo=UTC),
        fail_count=0,
    )

    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_state_repo",
            _mock_ingestion_state_repo(mock_state_repo),
        ),
        patch("tg_parser.services.scheduler_service.settings") as mock_settings,
    ):
        mock_settings.scheduler_enabled = True
        mock_settings.scheduler_default_interval = 3600
        mock_settings.scheduler_retopicize_threshold = 10

        from tg_parser.services.scheduler_service import get_scheduler_status

        status = await get_scheduler_status()

    assert status["scheduler_enabled"] is True
    assert status["default_interval_seconds"] == 3600
    assert len(status["sources"]) == 1

    src = status["sources"][0]
    assert src["source_id"] == "s1"
    assert src["status"] == "active"
    assert src["poll_interval_seconds"] == 1800
    assert src["fail_count"] == 0


# ============================================================================
# Tests: BackgroundScheduler incremental_pipeline_task
# ============================================================================


@pytest.mark.asyncio
async def test_incremental_pipeline_task_calls_service():
    """The APScheduler wrapper invokes run_incremental_for_all_sources."""
    with patch(
        "tg_parser.services.scheduler_service.run_incremental_for_all_sources",
        new_callable=AsyncMock,
        return_value={"sources_succeeded": 1, "sources_failed": 0},
    ) as mock_run:
        from tg_parser.services.scheduler_service import incremental_pipeline_task

        result = await incremental_pipeline_task()

    mock_run.assert_awaited_once()
    assert result["sources_succeeded"] == 1


# ============================================================================
# Tests: setup_default_tasks registers incremental job
# ============================================================================


def test_setup_default_tasks_registers_incremental_pipeline():
    """setup_default_tasks adds the incremental_pipeline job to the scheduler."""
    from tg_parser.services.background_scheduler import BackgroundScheduler, setup_default_tasks

    scheduler = BackgroundScheduler()
    setup_default_tasks(scheduler, incremental_pipeline_interval=300)

    task_ids = {t["id"] for t in scheduler.get_tasks()}
    assert "incremental_pipeline" in task_ids
    assert "cleanup_expired_records" in task_ids
    assert "health_check" in task_ids


# ============================================================================
# Tests: record_attempt helpers
# ============================================================================


@pytest.mark.asyncio
async def test_record_attempt_details_stored():
    """Verify that _safe_record_attempt stores details correctly."""
    mock_state_repo = AsyncMock()
    from tg_parser.services.scheduler_service import _safe_record_attempt

    exc = RuntimeError("test error")
    await _safe_record_attempt(
        mock_state_repo,
        "src1",
        success=False,
        failed_stage="pipeline",
        exc=exc,
        duration=1.5,
    )

    mock_state_repo.record_attempt.assert_awaited_once()
    kwargs = mock_state_repo.record_attempt.call_args.kwargs
    assert kwargs["source_id"] == "src1"
    assert kwargs["success"] is False
    assert kwargs["failed_stage"] == "pipeline"
    assert kwargs["error_class"] == "RuntimeError"
    assert kwargs["error_message"] == "test error"
    assert kwargs["details"]["trigger"] == "scheduled"
    assert kwargs["details"]["duration_seconds"] == 1.5


@pytest.mark.asyncio
async def test_record_attempt_truncates_at_documented_limit():
    """Regression — Sprint D.1 documented a 4096-char ``error_message`` cap;
    the helper previously dropped at 500 silently. See REVIEW_2026-04-26
    MERGED_PLAN S-001 for context."""
    mock_state_repo = AsyncMock()
    from tg_parser.services.scheduler_service import _safe_record_attempt

    long_message = "a" * 5000
    exc = RuntimeError(long_message)
    await _safe_record_attempt(
        mock_state_repo,
        "src-long",
        success=False,
        failed_stage="pipeline",
        exc=exc,
        duration=2.0,
    )

    mock_state_repo.record_attempt.assert_awaited_once()
    kwargs = mock_state_repo.record_attempt.call_args.kwargs
    persisted = kwargs["error_message"]
    assert len(persisted) == 4096
    assert persisted == long_message[:4096]


def test_truncate_error_message_default_matches_documented_contract():
    """Direct unit-level guard: helper signature ships with 4096 default
    so any future regression to 500 fails fast."""
    import inspect

    from tg_parser.services.scheduler_service import _truncate_error_message

    sig = inspect.signature(_truncate_error_message)
    assert sig.parameters["max_len"].default == 4096
    assert _truncate_error_message("x" * 10_000) == "x" * 4096


@pytest.mark.asyncio
async def test_failed_incremental_topicization_marks_attempt_failed():
    source = Source(source_id="s1", channel_id="ch1", status="active", include_comments=False)
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]
    mock_processed_repo = AsyncMock()
    doc_after = [MagicMock(source_ref="tg:ch1:post:1")]
    mock_processed_repo.list_by_channel.side_effect = [[], doc_after]

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(429, request=req, text="rate limited")

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, mock_processed_repo),
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion",
            new_callable=AsyncMock,
            return_value={"posts_collected": 1, "comments_collected": 0},
        ),
        patch(
            "tg_parser.services.pipeline_service.run_processing",
            new_callable=AsyncMock,
            return_value={
                "processed_count": 1,
                "failed_count": 0,
                "skipped_count": 0,
                "total_count": 1,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_export",
            new_callable=AsyncMock,
            return_value={"kb_entries_count": 1, "topics_count": 0, "channels_count": 1},
        ),
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch1",
        ),
        patch(
            "tg_parser.services.topicization_service.run_incremental_topicization",
            new_callable=AsyncMock,
            side_effect=httpx.HTTPStatusError("HTTP error", request=req, response=resp),
        ),
    ):
        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert result["sources_failed"] == 1
    kwargs = mock_state_repo.record_attempt.call_args.kwargs
    assert kwargs["success"] is False
    assert kwargs["error_class"] == "HTTPStatusError"
    assert kwargs["failed_stage"] == "incremental_topicization"
    assert kwargs["error_message"]


@pytest.mark.asyncio
async def test_billing_error_pauses_source_and_marks_failure():
    from tg_parser.api.metrics import ANTHROPIC_BILLING_BLOCK_TOTAL
    from tg_parser.processing.llm.errors import AnthropicBillingError

    source = Source(source_id="s1", channel_id="ch1", status="active", include_comments=False)
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]
    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_by_channel.side_effect = [[], [MagicMock(source_ref="tg:ch1:post:1")]]

    metric = ANTHROPIC_BILLING_BLOCK_TOTAL.labels(stage="incremental_topicization")
    metric_before = metric._value.get()
    t_before = datetime.now(UTC)

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, mock_processed_repo),
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion",
            new_callable=AsyncMock,
            return_value={"posts_collected": 1, "comments_collected": 0},
        ),
        patch(
            "tg_parser.services.pipeline_service.run_processing",
            new_callable=AsyncMock,
            return_value={
                "processed_count": 1,
                "failed_count": 0,
                "skipped_count": 0,
                "total_count": 1,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_export",
            new_callable=AsyncMock,
            return_value={"kb_entries_count": 1, "topics_count": 0, "channels_count": 1},
        ),
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch1",
        ),
        patch(
            "tg_parser.services.topicization_service.run_incremental_topicization",
            new_callable=AsyncMock,
            side_effect=AnthropicBillingError("credit balance exhausted"),
        ),
        patch("tg_parser.services.scheduler_service.settings") as mock_settings,
    ):
        mock_settings.scheduler_retopicize_threshold = 1
        mock_settings.scheduler_max_concurrent_sources = 1
        mock_settings.billing_block_backoff_s = 3600

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert result["sources_failed"] == 1
    mock_state_repo.upsert_source.assert_awaited_once()
    kwargs = mock_state_repo.record_attempt.call_args.kwargs
    assert kwargs["error_class"] == "AnthropicBillingError"
    assert kwargs["failed_stage"] == "incremental_topicization"

    # Pause must point to the FUTURE by ~billing_block_backoff_s.  A naive
    # `is not None` check would not catch a regression that pauses to past time
    # (i.e. effectively no pause at all).
    assert source.rate_limit_until is not None
    delta = (source.rate_limit_until - t_before).total_seconds()
    assert 3500 <= delta <= 3700, (
        f"rate_limit_until should be ~3600s in the future, got delta={delta:.0f}s"
    )

    # Observability must move in lock-step with mitigation.
    assert metric._value.get() == metric_before + 1, (
        "ANTHROPIC_BILLING_BLOCK_TOTAL{stage=incremental_topicization} not incremented"
    )


# ============================================================================
# Tests: _record_and_pause_on_billing helper (TD-05)
# ============================================================================


@pytest.mark.asyncio
async def test_record_and_pause_on_billing_noop_when_stage_errors_empty():
    """TD-05: helper is a no-op on empty stage_errors list.

    Required so callers can invoke unconditionally from a ``finally``
    block without an explicit empty-list guard.
    """
    from tg_parser.api.metrics import ANTHROPIC_BILLING_BLOCK_TOTAL
    from tg_parser.services.scheduler_service import _record_and_pause_on_billing

    source = Source(
        source_id="s_noop", channel_id="ch_noop", status="active", include_comments=False
    )
    state_repo = AsyncMock()

    metric = ANTHROPIC_BILLING_BLOCK_TOTAL.labels(stage="watchlist_check")
    metric_before = metric._value.get()

    await _record_and_pause_on_billing([], source, state_repo)

    assert source.rate_limit_until is None, "empty stage_errors must not pause"
    state_repo.upsert_source.assert_not_called()
    assert metric._value.get() == metric_before, "empty stage_errors must not record"


@pytest.mark.asyncio
async def test_record_and_pause_on_billing_noop_when_first_error_is_not_billing():
    """TD-05: helper ignores non-billing first error (no metric/pause)."""
    from tg_parser.services.scheduler_service import _record_and_pause_on_billing

    source = Source(
        source_id="s_other", channel_id="ch_other", status="active", include_comments=False
    )
    state_repo = AsyncMock()

    await _record_and_pause_on_billing(
        [("ingest", RuntimeError("boom"))],
        source,
        state_repo,
    )

    assert source.rate_limit_until is None
    state_repo.upsert_source.assert_not_called()


@pytest.mark.asyncio
async def test_record_and_pause_on_billing_records_metric_and_pauses_source():
    """TD-05: happy-path — billing as first error → metric +1 and source paused."""
    from tg_parser.api.metrics import ANTHROPIC_BILLING_BLOCK_TOTAL
    from tg_parser.processing.llm.errors import AnthropicBillingError
    from tg_parser.services.scheduler_service import _record_and_pause_on_billing

    source = Source(
        source_id="s_bill", channel_id="ch_bill", status="active", include_comments=False
    )
    state_repo = AsyncMock()

    metric = ANTHROPIC_BILLING_BLOCK_TOTAL.labels(stage="resummarize")
    metric_before = metric._value.get()
    t_before = datetime.now(UTC)

    with patch("tg_parser.services.scheduler_service.settings") as mock_settings:
        mock_settings.billing_block_backoff_s = 1800
        await _record_and_pause_on_billing(
            [("resummarize", AnthropicBillingError("credit balance is too low"))],
            source,
            state_repo,
        )

    assert source.rate_limit_until is not None
    delta = (source.rate_limit_until - t_before).total_seconds()
    assert 1700 <= delta <= 1900, f"rate_limit_until ≈ +1800s, got delta={delta:.0f}s"
    state_repo.upsert_source.assert_awaited_once_with(source)
    assert metric._value.get() == metric_before + 1


@pytest.mark.asyncio
async def test_watchlist_billing_error_propagates_and_pauses_source():
    """TD-05 / merged-plan S-007: F11 hook must escalate AnthropicBillingError.

    Pre-fix the watchlist hook had a generic ``except Exception`` that
    swallowed billing errors → ``stage_errors`` stayed empty → the
    ``_record_and_pause_on_billing`` finally block found nothing to do →
    source was not paused → next tick re-incurred the billing call.
    Mirrors :func:`test_billing_error_pauses_source_and_marks_failure`
    but exercises the **watchlist** entry point instead of
    incremental_topicization.
    """
    from tg_parser.api.metrics import ANTHROPIC_BILLING_BLOCK_TOTAL
    from tg_parser.processing.llm.errors import AnthropicBillingError

    source = Source(
        source_id="s_wl",
        channel_id="ch_wl",
        status="active",
        include_comments=False,
    )
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]
    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_by_channel.side_effect = [
        [],
        [MagicMock(source_ref="tg:ch_wl:post:1")],
    ]

    metric = ANTHROPIC_BILLING_BLOCK_TOTAL.labels(stage="watchlist_check")
    metric_before = metric._value.get()
    t_before = datetime.now(UTC)

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, mock_processed_repo),
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion",
            new_callable=AsyncMock,
            return_value={"posts_collected": 1, "comments_collected": 0},
        ),
        patch(
            "tg_parser.services.pipeline_service.run_processing",
            new_callable=AsyncMock,
            return_value={
                "processed_count": 1,
                "failed_count": 0,
                "skipped_count": 0,
                "total_count": 1,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_export",
            new_callable=AsyncMock,
            return_value={"kb_entries_count": 1, "topics_count": 0, "channels_count": 1},
        ),
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch_wl",
        ),
        patch(
            "tg_parser.services.topicization_service.run_incremental_topicization",
            new_callable=AsyncMock,
            return_value=_ok_incr_result(),
        ),
        patch(
            "tg_parser.services.embedding_service.run_topic_embedding",
            new_callable=AsyncMock,
            return_value={"updated": 0, "skipped": 0},
        ),
        patch(
            "tg_parser.services.scheduler_service.run_resummarize_for_channel",
            new_callable=AsyncMock,
            return_value={
                "candidates": 0,
                "resummarized": 0,
                "skipped": 0,
                "tokens": 0,
                "duration_s": 0.0,
            },
        ),
        patch(
            "tg_parser.services.scheduler_service.run_watchlist_check_for_channel",
            new_callable=AsyncMock,
            side_effect=AnthropicBillingError("credit balance is too low"),
        ),
        patch("tg_parser.services.scheduler_service.settings") as mock_settings,
    ):
        mock_settings.scheduler_retopicize_threshold = 1
        mock_settings.scheduler_max_concurrent_sources = 1
        mock_settings.billing_block_backoff_s = 3600

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert result["sources_failed"] == 1, (
        "billing error in F11 hook must mark the source as failed (not silently logged)"
    )
    kwargs = mock_state_repo.record_attempt.call_args.kwargs
    assert kwargs["error_class"] == "AnthropicBillingError"
    assert kwargs["failed_stage"] == "watchlist_check"

    assert source.rate_limit_until is not None, (
        "F11 billing error must trigger _pause_source_for_billing via stage_errors"
    )
    delta = (source.rate_limit_until - t_before).total_seconds()
    assert 3500 <= delta <= 3700

    assert metric._value.get() == metric_before + 1, (
        "ANTHROPIC_BILLING_BLOCK_TOTAL{stage=watchlist_check} must increment "
        "in lock-step with the source pause"
    )


@pytest.mark.asyncio
async def test_watchlist_generic_exception_does_not_pause_source():
    """TD-05 regression: F11 silent-log contract preserved for non-billing failures.

    Decision #13 says F11 watchlist failures (other than billing) must
    silent-log without polluting ``stage_errors`` so ``success`` is not
    falsified for upstream stages. The TD-05 fix adds a billing-specific
    ``except`` arm — this test guards that the existing generic-exception
    path is untouched.
    """
    source = Source(
        source_id="s_wl_other",
        channel_id="ch_wl_other",
        status="active",
        include_comments=False,
    )
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]
    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_by_channel.side_effect = [
        [],
        [MagicMock(source_ref="tg:ch_wl_other:post:1")],
    ]

    with (
        patch(
            "tg_parser.services.scheduler_service.ingestion_and_processing_repos",
            _mock_ingestion_and_processing_repos(mock_state_repo, mock_processed_repo),
        ),
        patch(
            "tg_parser.services.pipeline_service.run_ingestion",
            new_callable=AsyncMock,
            return_value={"posts_collected": 1, "comments_collected": 0},
        ),
        patch(
            "tg_parser.services.pipeline_service.run_processing",
            new_callable=AsyncMock,
            return_value={
                "processed_count": 1,
                "failed_count": 0,
                "skipped_count": 0,
                "total_count": 1,
            },
        ),
        patch(
            "tg_parser.services.pipeline_service.run_export",
            new_callable=AsyncMock,
            return_value={"kb_entries_count": 1, "topics_count": 0, "channels_count": 1},
        ),
        patch(
            "tg_parser.services.pipeline_service._get_channel_id_from_source",
            new_callable=AsyncMock,
            return_value="ch_wl_other",
        ),
        patch(
            "tg_parser.services.topicization_service.run_incremental_topicization",
            new_callable=AsyncMock,
            return_value=_ok_incr_result(),
        ),
        patch(
            "tg_parser.services.embedding_service.run_topic_embedding",
            new_callable=AsyncMock,
            return_value={"updated": 0, "skipped": 0},
        ),
        patch(
            "tg_parser.services.scheduler_service.run_resummarize_for_channel",
            new_callable=AsyncMock,
            return_value={
                "candidates": 0,
                "resummarized": 0,
                "skipped": 0,
                "tokens": 0,
                "duration_s": 0.0,
            },
        ),
        patch(
            "tg_parser.services.scheduler_service.run_watchlist_check_for_channel",
            new_callable=AsyncMock,
            side_effect=RuntimeError("F11 transient failure"),
        ),
        patch("tg_parser.services.scheduler_service.settings") as mock_settings,
    ):
        mock_settings.scheduler_retopicize_threshold = 1
        mock_settings.scheduler_max_concurrent_sources = 1
        mock_settings.billing_block_backoff_s = 3600

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources

        result = await run_incremental_for_all_sources()

    assert source.rate_limit_until is None, (
        "non-billing F11 failure must NOT trigger source pause (silent-log contract)"
    )
    assert result["sources_succeeded"] == 1, (
        "non-billing F11 failure must NOT mark source as failed — "
        "F11 is post-processing, upstream stages succeeded"
    )


# ============================================================================
# Tests: _safe_stats helper
# ============================================================================


def test_safe_stats_filters_non_serializable():
    """_safe_stats only keeps scalar values."""
    from tg_parser.services.scheduler_service import _safe_stats

    stats = {
        "ingest": {
            "posts_collected": 5,
            "comments_collected": 0,
            "errors": 0,
            "duration_seconds": 1.23,
            "_internal": [1, 2, 3],
        },
        "process": {"processed_count": 5, "failed_count": 0},
        "topicize": None,
        "export": None,
    }

    result = _safe_stats(stats)
    assert "_internal" not in result["ingest"]
    assert result["ingest"]["posts_collected"] == 5
    assert "process" in result
    assert "topicize" not in result
    assert "export" not in result
