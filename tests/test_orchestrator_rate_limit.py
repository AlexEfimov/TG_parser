"""BUG-014B: orchestrator rate_limit_until comparison regression."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_parser.ingestion.orchestrator import IngestionOrchestrator, RetryableError
from tg_parser.storage.ports import Source
from tg_parser.storage.sqlalchemy.ingestion_state_repo import SAIngestionStateRepo


def _make_orchestrator(source: Source) -> IngestionOrchestrator:
    mock_settings = MagicMock()
    mock_settings.ingestion_max_attempts_per_run = 3
    mock_state_repo = AsyncMock()
    mock_state_repo.get_source.return_value = source
    return IngestionOrchestrator(
        telegram_client=AsyncMock(),
        state_repo=mock_state_repo,
        raw_repo=AsyncMock(),
        settings=mock_settings,
    )


@pytest.mark.asyncio
async def test_bug014b_orchestrator_rate_limited_source_raises_retryable_not_typeerror():
    """Post-Option-B: tz-aware rate_limit_until (as from _row_to_source) → RetryableError."""
    aware_future = datetime(2099, 6, 1, 12, 0, 0, tzinfo=UTC)
    source = Source(
        source_id="kdl_ru",
        channel_id="kdl_ru",
        status="active",
        include_comments=False,
        rate_limit_until=aware_future,
    )

    with pytest.raises(RetryableError, match="rate-limited"):
        await _make_orchestrator(source).ingest_source(source_id="kdl_ru", mode="incremental")


@pytest.mark.asyncio
async def test_bug014b_orchestrator_naive_rate_limit_until_raises_typeerror():
    """Orchestrator does not coerce; naive Source bypassing storage still hits BUG-014B signature."""
    naive_future = datetime(2099, 6, 1, 12, 0, 0)
    assert naive_future.tzinfo is None

    source = Source(
        source_id="kdl_ru",
        channel_id="kdl_ru",
        status="active",
        include_comments=False,
        rate_limit_until=naive_future,
    )

    with pytest.raises(TypeError, match="offset-naive and offset-aware"):
        await _make_orchestrator(source).ingest_source(source_id="kdl_ru", mode="incremental")


@pytest.mark.asyncio
async def test_bug014b_orchestrator_accepts_repo_coerced_rate_limit_until():
    """End-to-end contract: _row_to_source output must pass orchestrator gate (line ~110)."""
    row = MagicMock()
    row.source_id = "kdl_ru"
    row.channel_id = "kdl_ru"
    row.channel_username = None
    row.status = "active"
    row.include_comments = False
    row.poll_interval_seconds = 3600
    row.batch_size = 100
    row.last_post_id = None
    row.fail_count = 0
    row.last_error = None
    row.comments_unavailable = False
    row.owner_id = None
    row.deleted_at = None
    for f in (
        "history_from",
        "history_to",
        "backfill_completed_at",
        "last_attempt_at",
        "last_success_at",
    ):
        setattr(row, f, None)
    row.rate_limit_until = "2099-06-01T12:00:00Z"
    row.created_at = "2026-05-15T16:02:04Z"
    row.updated_at = "2026-05-15T16:02:04Z"

    source = SAIngestionStateRepo(session=AsyncMock())._row_to_source(row)

    with pytest.raises(RetryableError, match="rate-limited"):
        await _make_orchestrator(source).ingest_source(source_id="kdl_ru", mode="incremental")
