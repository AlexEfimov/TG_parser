"""Tests for the hourly Idempotency-Key cleanup tick (Wave 1 step 3 commit 4/4).

Exercises :func:`tg_parser.services.scheduler_service.cleanup_stale_idempotency_keys`
end-to-end against the real ingestion DB. The 24-hour TTL is bypassed by
inserting rows with explicit ``created_at`` timestamps (no
``freezegun`` / ``time_machine`` dependency — both are absent from
``pyproject.toml`` and forbidden by AGENTS.md).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from tg_parser.api.metrics import IDEMPOTENCY_KEYS_TABLE_SIZE
from tg_parser.services.scheduler_service import cleanup_stale_idempotency_keys
from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
async def _idem_cleanup_db(test_db):
    """Wipe the idempotency table + users for a clean slate."""
    session = test_db.ingestion_state_session()
    try:
        await session.execute(text("DELETE FROM idempotency_keys"))
        await session.execute(text("DELETE FROM user_auth_mappings"))
        await session.execute(text("UPDATE sources SET owner_id = NULL"))
        await session.execute(text("DELETE FROM users"))
        await session.commit()
    finally:
        await session.close()
    return test_db


@pytest.fixture
async def user_repo(_idem_cleanup_db):
    session = _idem_cleanup_db.ingestion_state_session()
    try:
        yield SAUserRepo(session)
    finally:
        await session.close()


async def _insert_key(
    db,
    *,
    key: str,
    user_id: str,
    created_at: datetime,
) -> None:
    """Insert a row with an explicit ``created_at`` so we can simulate age."""
    session = db.ingestion_state_session()
    try:
        await session.execute(
            text(
                "INSERT INTO idempotency_keys "
                "(key, user_id, request_hash, response_body, created_at) "
                "VALUES (:key, :user_id, :hash, CAST(:body AS jsonb), :created_at)"
            ),
            {
                "key": key,
                "user_id": user_id,
                "hash": "deadbeef",
                "body": '{"status": 201, "body": {"ok": true}}',
                "created_at": created_at,
            },
        )
        await session.commit()
    finally:
        await session.close()


async def _count_keys(db) -> int:
    session = db.ingestion_state_session()
    try:
        row = (await session.execute(text("SELECT COUNT(*) FROM idempotency_keys"))).fetchone()
        return int(row[0])
    finally:
        await session.close()


# ── Tests ───────────────────────────────────────────────────────────────────


@pg_only
async def test_cleanup_deletes_keys_older_than_24h(user_repo, _idem_cleanup_db):
    """Rows older than 24h are deleted; fresh rows survive."""
    owner = await user_repo.create_user("alice_cleanup")
    now = datetime.now(UTC)
    stale_ts = now - timedelta(hours=25)
    fresh_ts = now - timedelta(minutes=10)

    for n in range(5):
        await _insert_key(
            _idem_cleanup_db,
            key=f"stale-{n}",
            user_id=owner.id,
            created_at=stale_ts,
        )
    for n in range(3):
        await _insert_key(
            _idem_cleanup_db,
            key=f"fresh-{n}",
            user_id=owner.id,
            created_at=fresh_ts,
        )

    result = await cleanup_stale_idempotency_keys()
    assert result["deleted"] == 5
    assert result["table_size"] == 3
    assert await _count_keys(_idem_cleanup_db) == 3


@pg_only
async def test_cleanup_emits_table_size_gauge(user_repo, _idem_cleanup_db):
    """The gauge tracks the post-cleanup row count."""
    owner = await user_repo.create_user("alice_gauge")
    now = datetime.now(UTC)
    fresh_ts = now - timedelta(minutes=5)

    for n in range(7):
        await _insert_key(
            _idem_cleanup_db,
            key=f"gauge-{n}",
            user_id=owner.id,
            created_at=fresh_ts,
        )

    await cleanup_stale_idempotency_keys()

    # Read directly from the gauge — internal Prometheus client API.
    sample_value = IDEMPOTENCY_KEYS_TABLE_SIZE._value.get()  # noqa: SLF001
    assert sample_value == 7


@pg_only
async def test_cleanup_with_empty_table_is_noop(_idem_cleanup_db):
    """Cleanup against an empty table returns 0 deleted + 0 size, no errors."""
    result = await cleanup_stale_idempotency_keys()
    assert result == {"deleted": 0, "table_size": 0}
    assert IDEMPOTENCY_KEYS_TABLE_SIZE._value.get() == 0  # noqa: SLF001
