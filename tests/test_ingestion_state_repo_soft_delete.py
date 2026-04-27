"""Integration regression for BUG-002 mitigation M3 (`SAIngestionStateRepo`).

Sprint Hot-fix B+ post-merge — the unit tests in
``tests/test_mcp_management.py`` and ``tests/test_bot_tools_v12.py`` mock
``state_repo.delete_source`` so the actual SQL never runs, which let a
real driver-level bug ship: the original implementation reused a single
``:now`` named parameter for both ``deleted_at`` and ``updated_at``, and
asyncpg raised ``AmbiguousParameterError: inconsistent types deduced for
parameter $1`` at runtime when both columns asked for that placeholder.
This file exercises the SQL against a live pgvector PG17 container and
covers the full M3 cycle so the same class of regression cannot pass
CI silently again.

Uses the session-scoped ``pgvector_container`` fixture from
``tests/_testcontainer_fixtures.py`` (opt-in via ``TEST_TESTCONTAINERS=1``)
so the default pytest run on a Docker-less host stays fast.
"""

from __future__ import annotations

import pytest
from _testcontainer_fixtures import (
    alembic_upgrade_for_branch,
    async_url_for_db,
    requires_testcontainers,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tg_parser.storage.ports import Source
from tg_parser.storage.sqlalchemy.ingestion_state_repo import SAIngestionStateRepo

pytest_plugins = ("_testcontainer_fixtures",)


@pytest.fixture
def ingestion_db_url(pgvector_container) -> str:
    """Fresh ingestion DB at head; returns its asyncpg URL.

    Kept synchronous on purpose: ``alembic_upgrade_for_branch`` boots an
    async engine inside ``env.py`` via ``asyncio.run(...)``, so it cannot
    run inside a pytest-asyncio test loop (would raise ``asyncio.run()
    cannot be called from a running event loop``).  Fixture stays sync
    so the upgrade happens before the test's loop is even created;
    the async test then builds its own engine against the URL.
    """
    db = alembic_upgrade_for_branch(pgvector_container, "ingestion")
    return async_url_for_db(pgvector_container, db)


async def _seed_owner(session_factory: async_sessionmaker) -> str:
    """Insert a placeholder admin user; returns its UUID as text.

    ``sources.owner_id`` is a NOT NULL FK to ``users.id`` so we cannot
    skip this step.  We pick admin role purely to stay clear of the
    ``users_role_check`` CHECK constraint; it has no other effect.
    """
    async with session_factory() as session:
        result = await session.execute(
            text(
                "INSERT INTO users (id, name, role) "
                "VALUES (gen_random_uuid(), 'm3-test', 'admin') "
                "RETURNING id"
            )
        )
        owner_id = str(result.scalar_one())
        await session.commit()
    return owner_id


@requires_testcontainers
async def test_delete_source_soft_deletes_then_resurrects(ingestion_db_url: str):
    """Full M3 contract: upsert → delete → filtered → find_deleted → resurrect.

    Asserts the four observable invariants of M3:

    1. ``delete_source`` returns ``True`` on first call (rowcount == 1).
    2. After delete, ``get_source`` returns ``None`` (default filter
       hides soft-deleted) but ``find_deleted_source`` /
       ``get_source(include_deleted=True)`` return the row with a
       non-null ``deleted_at``.
    3. Re-``upsert_source`` (the channel reanimation path triggered by
       ``add_channel`` after a soft-delete) resets ``deleted_at`` back
       to ``NULL`` so the channel becomes visible again.
    4. A second ``delete_source`` on an already-deleted row is
       idempotent (returns ``False``).
    """
    engine = create_async_engine(ingestion_db_url)
    try:
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        owner_id = await _seed_owner(sessionmaker)
        sid = "m3_smoke_chan"
        await _run_cycle(sessionmaker, owner_id, sid)
    finally:
        await engine.dispose()


async def _run_cycle(sessionmaker: async_sessionmaker, owner_id: str, sid: str) -> None:
    async with sessionmaker() as session:
        repo = SAIngestionStateRepo(session)
        await repo.upsert_source(
            Source(
                source_id=sid,
                channel_id=sid,
                status="active",
                include_comments=False,
                batch_size=100,
                owner_id=owner_id,
            )
        )
        fresh = await repo.get_source(sid)
        assert fresh is not None
        assert fresh.deleted_at is None

    async with sessionmaker() as session:
        repo = SAIngestionStateRepo(session)
        assert await repo.delete_source(sid) is True

    async with sessionmaker() as session:
        repo = SAIngestionStateRepo(session)
        assert await repo.get_source(sid) is None
        deleted = await repo.find_deleted_source(sid)
        assert deleted is not None
        assert deleted.deleted_at is not None
        with_flag = await repo.get_source(sid, include_deleted=True)
        assert with_flag is not None
        assert with_flag.deleted_at is not None
        assert await repo.delete_source(sid) is False

    async with sessionmaker() as session:
        repo = SAIngestionStateRepo(session)
        await repo.upsert_source(
            Source(
                source_id=sid,
                channel_id=sid,
                status="active",
                include_comments=False,
                batch_size=100,
                owner_id=owner_id,
            )
        )
        revived = await repo.get_source(sid)
        assert revived is not None
        assert revived.deleted_at is None
        assert await repo.find_deleted_source(sid) is None
