"""BUG-014B: storage-boundary tz-aware coerce in SAIngestionStateRepo._row_to_source."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_parser.storage.sqlalchemy.ingestion_state_repo import SAIngestionStateRepo

_NAIVE_ISO_UTC = "2026-05-15T16:02:04Z"
_EXPECTED_NAIVE_WALL = datetime(2026, 5, 15, 16, 2, 4)


def _make_row(**overrides):
    row = MagicMock()
    row.source_id = "test_channel"
    row.channel_id = "test_channel"
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
        "rate_limit_until",
        "created_at",
        "updated_at",
    ):
        setattr(row, f, _NAIVE_ISO_UTC)
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


@pytest.mark.parametrize(
    "field_name",
    [
        "history_from",
        "history_to",
        "backfill_completed_at",
        "last_attempt_at",
        "last_success_at",
        "rate_limit_until",
        "created_at",
        "updated_at",
    ],
    ids=[
        "history_from",
        "history_to",
        "backfill_completed_at",
        "last_attempt_at",
        "last_success_at",
        "rate_limit_until",
        "created_at",
        "updated_at",
    ],
)
def test_bug014b_row_to_source_coerces_all_naive_datetime_fields_to_aware(field_name):
    """For each naive datetime field, _row_to_source returns tz-aware UTC."""
    row = _make_row()
    source = SAIngestionStateRepo(session=AsyncMock())._row_to_source(row)

    value = getattr(source, field_name)
    assert value is not None, f"{field_name} must not be None"
    assert value.tzinfo == UTC, (
        f"{field_name} must be tz-aware UTC after _row_to_source (BUG-014B), got {value.tzinfo!r}"
    )
    assert value.replace(tzinfo=None) == _EXPECTED_NAIVE_WALL, (
        f"{field_name} wall-clock must match parsed ISO string (no tz shift)"
    )


_NULLABLE_DATETIME_FIELDS = (
    "history_from",
    "history_to",
    "backfill_completed_at",
    "last_attempt_at",
    "last_success_at",
    "rate_limit_until",
)


def test_bug014b_row_to_source_nullable_datetime_fields_stay_none():
    """Coerce wrap must preserve None for every optional datetime column."""
    row = _make_row(**dict.fromkeys(_NULLABLE_DATETIME_FIELDS, None))
    source = SAIngestionStateRepo(session=AsyncMock())._row_to_source(row)

    for field_name in _NULLABLE_DATETIME_FIELDS:
        assert getattr(source, field_name) is None, f"{field_name} must stay None"
    assert source.created_at.tzinfo == UTC
    assert source.updated_at.tzinfo == UTC


def test_bug014b_row_to_source_rate_limit_until_comparable_with_now_utc():
    """Regression signature for orchestrator.py:110 — aware-vs-aware compare must not TypeError."""
    row = _make_row(rate_limit_until="2099-06-01T12:00:00Z")
    source = SAIngestionStateRepo(session=AsyncMock())._row_to_source(row)

    assert source.rate_limit_until is not None
    assert source.rate_limit_until.tzinfo == UTC
    # Exact comparison used by IngestionOrchestrator.ingest_source (line ~110).
    assert source.rate_limit_until > datetime.now(UTC)
