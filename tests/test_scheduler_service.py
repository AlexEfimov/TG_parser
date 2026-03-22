"""
Tests for the incremental-pipeline scheduler service (Session 30).

Tests cover:
- run_incremental_for_all_sources: iterate sources, run pipeline, record attempts
- Retopicization threshold logic
- Error isolation between sources
- get_scheduler_status
- BackgroundScheduler integration with incremental_pipeline_task
"""

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_parser.storage.ports import Source


# ============================================================================
# Helpers
# ============================================================================


def _make_mock_db():
    """Return a mock Database that has proper async session stubs.

    ingestion_state_session() and processing_storage_session() are sync
    methods in the real Database, so we use MagicMock for the db itself
    and only make init/close async.
    """
    mock_db = MagicMock()
    mock_db.init = AsyncMock()
    mock_db.close = AsyncMock()

    state_session = MagicMock()
    state_session.close = AsyncMock()
    processing_session = MagicMock()
    processing_session.close = AsyncMock()

    mock_db.ingestion_state_session.return_value = state_session
    mock_db.processing_storage_session.return_value = processing_session
    return mock_db


# ============================================================================
# Tests: run_incremental_for_all_sources
# ============================================================================


@pytest.mark.asyncio
async def test_no_active_sources_returns_zero():
    """With no active sources the function returns immediately."""
    mock_db = _make_mock_db()
    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = []

    with patch("tg_parser.services.scheduler_service.Database") as MockDB, \
         patch("tg_parser.services.scheduler_service.SQLiteIngestionStateRepo", return_value=mock_state_repo), \
         patch("tg_parser.services.scheduler_service.SQLiteProcessedDocumentRepo", return_value=AsyncMock()):

        MockDB.from_settings.return_value = mock_db

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

    pipeline_stats = {
        "ingest": {"posts_collected": 3, "comments_collected": 0},
        "process": {"processed_count": 3, "failed_count": 0},
        "topicize": None,
        "export": {"kb_entries_count": 3, "topics_count": 0},
        "total_duration_seconds": 1.0,
        "last_successful_stage": "export",
    }

    mock_db = _make_mock_db()

    with patch("tg_parser.services.scheduler_service.Database") as MockDB, \
         patch("tg_parser.services.scheduler_service.SQLiteIngestionStateRepo", return_value=mock_state_repo), \
         patch("tg_parser.services.scheduler_service.SQLiteProcessedDocumentRepo", return_value=mock_processed_repo), \
         patch("tg_parser.services.pipeline_service.run_ingestion", new_callable=AsyncMock) as mock_ingest, \
         patch("tg_parser.services.pipeline_service.run_processing", new_callable=AsyncMock) as mock_process, \
         patch("tg_parser.services.pipeline_service.run_export", new_callable=AsyncMock) as mock_export, \
         patch("tg_parser.services.pipeline_service._get_channel_id_from_source", new_callable=AsyncMock, return_value="ch1"):

        MockDB.from_settings.return_value = mock_db

        mock_ingest.return_value = {"posts_collected": 3, "comments_collected": 0, "errors": 0, "duration_seconds": 0.5}
        mock_process.return_value = {"processed_count": 3, "skipped_count": 0, "failed_count": 0, "total_count": 3}
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
    source_fail = Source(source_id="fail", channel_id="ch_fail", status="active", include_comments=False)

    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source_fail, source_ok]
    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_by_channel.return_value = []

    ok_ingest = {"posts_collected": 1, "comments_collected": 0, "errors": 0, "duration_seconds": 0.1}
    ok_process = {"processed_count": 1, "skipped_count": 0, "failed_count": 0, "total_count": 1}
    ok_export = {"kb_entries_count": 1, "topics_count": 0, "channels_count": 1}

    call_order = []

    async def mock_ingest_side_effect(**kwargs):
        source_id = kwargs.get("source_id", "")
        call_order.append(("ingest", source_id))
        if source_id == "fail":
            raise RuntimeError("Telegram FloodWait")
        return ok_ingest

    mock_db = _make_mock_db()

    with patch("tg_parser.services.scheduler_service.Database") as MockDB, \
         patch("tg_parser.services.scheduler_service.SQLiteIngestionStateRepo", return_value=mock_state_repo), \
         patch("tg_parser.services.scheduler_service.SQLiteProcessedDocumentRepo", return_value=mock_processed_repo), \
         patch("tg_parser.services.pipeline_service.run_ingestion", new_callable=AsyncMock, side_effect=mock_ingest_side_effect), \
         patch("tg_parser.services.pipeline_service.run_processing", new_callable=AsyncMock, return_value=ok_process), \
         patch("tg_parser.services.pipeline_service.run_export", new_callable=AsyncMock, return_value=ok_export), \
         patch("tg_parser.services.pipeline_service._get_channel_id_from_source", new_callable=AsyncMock, return_value="ch_ok"):

        MockDB.from_settings.return_value = mock_db

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources
        result = await run_incremental_for_all_sources()

    assert result["sources_succeeded"] == 1
    assert result["sources_failed"] == 1
    assert "fail" in result["errors"]
    assert "FloodWait" in result["errors"]["fail"]


@pytest.mark.asyncio
async def test_retopicize_threshold_triggers():
    """When new docs exceed the threshold, retopicization is triggered."""
    source = Source(source_id="s1", channel_id="ch1", status="active", include_comments=False)

    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]

    mock_processed_repo = AsyncMock()
    docs_before: list = []
    docs_after = [MagicMock() for _ in range(5)]

    call_count = 0

    async def list_by_channel_side_effect(channel_id):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return docs_before
        return docs_after

    mock_processed_repo.list_by_channel.side_effect = list_by_channel_side_effect

    mock_db = _make_mock_db()

    with patch("tg_parser.services.scheduler_service.Database") as MockDB, \
         patch("tg_parser.services.scheduler_service.SQLiteIngestionStateRepo", return_value=mock_state_repo), \
         patch("tg_parser.services.scheduler_service.SQLiteProcessedDocumentRepo", return_value=mock_processed_repo), \
         patch("tg_parser.services.pipeline_service.run_ingestion", new_callable=AsyncMock, return_value={"posts_collected": 5, "comments_collected": 0, "errors": 0, "duration_seconds": 0.5}), \
         patch("tg_parser.services.pipeline_service.run_processing", new_callable=AsyncMock, return_value={"processed_count": 5, "skipped_count": 0, "failed_count": 0, "total_count": 5}), \
         patch("tg_parser.services.pipeline_service.run_export", new_callable=AsyncMock, return_value={"kb_entries_count": 5, "topics_count": 0, "channels_count": 1}), \
         patch("tg_parser.services.pipeline_service._get_channel_id_from_source", new_callable=AsyncMock, return_value="ch1"), \
         patch("tg_parser.services.scheduler_service._retopicize_source", new_callable=AsyncMock) as mock_retopicize, \
         patch("tg_parser.services.scheduler_service.settings") as mock_settings:

        mock_settings.scheduler_retopicize_threshold = 3

        MockDB.from_settings.return_value = mock_db

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources
        result = await run_incremental_for_all_sources()

    mock_retopicize.assert_awaited_once_with("ch1")
    assert "s1" in result["retopicized_sources"]


@pytest.mark.asyncio
async def test_retopicize_below_threshold_skipped():
    """When new docs are below the threshold, retopicization is skipped."""
    source = Source(source_id="s1", channel_id="ch1", status="active", include_comments=False)

    mock_state_repo = AsyncMock()
    mock_state_repo.list_sources.return_value = [source]

    mock_processed_repo = AsyncMock()
    mock_processed_repo.list_by_channel.return_value = [MagicMock()]

    mock_db = _make_mock_db()

    with patch("tg_parser.services.scheduler_service.Database") as MockDB, \
         patch("tg_parser.services.scheduler_service.SQLiteIngestionStateRepo", return_value=mock_state_repo), \
         patch("tg_parser.services.scheduler_service.SQLiteProcessedDocumentRepo", return_value=mock_processed_repo), \
         patch("tg_parser.services.pipeline_service.run_ingestion", new_callable=AsyncMock, return_value={"posts_collected": 0, "comments_collected": 0, "errors": 0, "duration_seconds": 0.1}), \
         patch("tg_parser.services.pipeline_service.run_processing", new_callable=AsyncMock, return_value={"processed_count": 0, "skipped_count": 1, "failed_count": 0, "total_count": 1}), \
         patch("tg_parser.services.pipeline_service.run_export", new_callable=AsyncMock, return_value={"kb_entries_count": 0, "topics_count": 0, "channels_count": 1}), \
         patch("tg_parser.services.pipeline_service._get_channel_id_from_source", new_callable=AsyncMock, return_value="ch1"), \
         patch("tg_parser.services.scheduler_service._retopicize_source", new_callable=AsyncMock) as mock_retopicize, \
         patch("tg_parser.services.scheduler_service.settings") as mock_settings:

        mock_settings.scheduler_retopicize_threshold = 10

        MockDB.from_settings.return_value = mock_db

        from tg_parser.services.scheduler_service import run_incremental_for_all_sources
        result = await run_incremental_for_all_sources()

    mock_retopicize.assert_not_awaited()
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

    mock_db = _make_mock_db()

    with patch("tg_parser.services.scheduler_service.Database") as MockDB, \
         patch("tg_parser.services.scheduler_service.SQLiteIngestionStateRepo", return_value=mock_state_repo), \
         patch("tg_parser.services.scheduler_service.settings") as mock_settings:

        mock_settings.scheduler_enabled = True
        mock_settings.scheduler_default_interval = 3600
        mock_settings.scheduler_retopicize_threshold = 10

        MockDB.from_settings.return_value = mock_db

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
        from tg_parser.api.scheduler import incremental_pipeline_task

        result = await incremental_pipeline_task()

    mock_run.assert_awaited_once()
    assert result["sources_succeeded"] == 1


# ============================================================================
# Tests: setup_default_tasks registers incremental job
# ============================================================================


def test_setup_default_tasks_registers_incremental_pipeline():
    """setup_default_tasks adds the incremental_pipeline job to the scheduler."""
    from tg_parser.api.scheduler import BackgroundScheduler, setup_default_tasks

    scheduler = BackgroundScheduler()
    setup_default_tasks(scheduler, incremental_pipeline_interval=300)

    task_ids = {t["id"] for t in scheduler.get_tasks()}
    assert "incremental_pipeline" in task_ids
    assert "cleanup_expired_records" in task_ids
    assert "health_check" in task_ids


# ============================================================================
# Tests: record_attempt with details
# ============================================================================


@pytest.mark.asyncio
async def test_record_attempt_details_stored():
    """Verify that _safe_record_failure stores details correctly."""
    mock_state_repo = AsyncMock()
    from tg_parser.services.scheduler_service import _safe_record_failure

    exc = RuntimeError("test error")
    await _safe_record_failure(mock_state_repo, "src1", exc, 1.5)

    mock_state_repo.record_attempt.assert_awaited_once()
    kwargs = mock_state_repo.record_attempt.call_args.kwargs
    assert kwargs["source_id"] == "src1"
    assert kwargs["success"] is False
    assert kwargs["error_class"] == "RuntimeError"
    assert kwargs["error_message"] == "test error"
    assert kwargs["details"]["trigger"] == "scheduled"
    assert kwargs["details"]["duration_seconds"] == 1.5


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
