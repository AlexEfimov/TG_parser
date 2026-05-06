"""Integration regression for BUG-010 — username alias resolution (Session I, 2026-05-06).

Verifies that ``get_source_by_username`` resolves channels by their
``channel_username`` column (``WHERE channel_username = :username``), and
that ``_resolve_source`` correctly falls back from PK-lookup to username
lookup against a live PostgreSQL instance.

This addresses the CI gap identified in ``BUG_LOG.md § BUG-010 Why CI didn't
catch``: unit tests mocked ``state_repo.get_source`` to return ``Source(...)``
regardless of input, so the lookup-by-PK vs lookup-by-username mismatch was
invisible. These testcontainers tests hit real SQL.

Uses the session-scoped ``pgvector_container`` fixture from
``tests/_testcontainer_fixtures.py`` (opt-in via ``TEST_TESTCONTAINERS=1``).

Tests I-1..I-4 mirror the plan in
``docs/notes/START_PROMPT_FIX_BUG010_SOURCE_USERNAME_ALIAS_SESSION_I_2026-05-06.md``
§ 4.1.
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
    """Fresh ingestion DB at head; returns its asyncpg URL."""
    db = alembic_upgrade_for_branch(pgvector_container, "ingestion")
    return async_url_for_db(pgvector_container, db)


async def _seed_owner(session_factory: async_sessionmaker) -> str:
    """Insert a placeholder admin user; returns its UUID as text."""
    async with session_factory() as session:
        result = await session.execute(
            text(
                "INSERT INTO users (id, name, role) "
                "VALUES (gen_random_uuid(), 'bug010-test', 'admin') "
                "RETURNING id"
            )
        )
        owner_id = str(result.scalar_one())
        await session.commit()
    return owner_id


async def _seed_source(
    session_factory: async_sessionmaker,
    owner_id: str,
    *,
    source_id: str,
    channel_username: str,
) -> None:
    """Upsert a source with the given source_id and channel_username."""
    async with session_factory() as session:
        repo = SAIngestionStateRepo(session)
        await repo.upsert_source(
            Source(
                source_id=source_id,
                channel_id=source_id,
                channel_username=channel_username,
                status="active",
                include_comments=False,
                batch_size=100,
                owner_id=owner_id,
            )
        )
        await session.commit()


# ---------------------------------------------------------------------------
# I-1 — get_source_by_username resolves existing channel (happy path)
# ---------------------------------------------------------------------------


@requires_testcontainers
async def test_get_source_by_username_resolves_existing(ingestion_db_url: str):
    """I-1: BUG-010 direct regression — get_source_by_username finds the row
    seeded with channel_username='AgeManagment'."""
    engine = create_async_engine(ingestion_db_url)
    try:
        sf = async_sessionmaker(engine, expire_on_commit=False)
        owner_id = await _seed_owner(sf)
        await _seed_source(sf, owner_id, source_id="-1002111111", channel_username="AgeManagment")

        async with sf() as session:
            repo = SAIngestionStateRepo(session)
            result = await repo.get_source_by_username("AgeManagment")

        assert result is not None, "get_source_by_username should find seeded source"
        assert result.source_id == "-1002111111"
        assert result.channel_username == "AgeManagment"
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# I-2 — get_source returns None for username input (isolates PK path)
# ---------------------------------------------------------------------------


@requires_testcontainers
async def test_get_source_returns_none_for_username_input(ingestion_db_url: str):
    """I-2: get_source('AgeManagment') returns None — demonstrates the BUG-010
    root cause: PK lookup cannot find a channel by its username.
    Contrast with I-1 which uses the new get_source_by_username method."""
    engine = create_async_engine(ingestion_db_url)
    try:
        sf = async_sessionmaker(engine, expire_on_commit=False)
        owner_id = await _seed_owner(sf)
        await _seed_source(sf, owner_id, source_id="-1002222222", channel_username="AgeManagment")

        async with sf() as session:
            repo = SAIngestionStateRepo(session)
            # Old behaviour: get_source does PK lookup → None for username input
            result = await repo.get_source("AgeManagment")

        assert result is None, (
            "get_source('AgeManagment') must return None — source_id is the numeric PK, "
            "not the channel_username. This test documents BUG-010 root cause isolation."
        )
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# I-3 — _resolve_source: fallback path (username → source)
# ---------------------------------------------------------------------------


@requires_testcontainers
async def test_resolve_source_fallback_path(ingestion_db_url: str):
    """I-3: End-to-end BUG-010 regression via _resolve_source.

    PK lookup: get_source('AgeManagment') → None
    Fallback:  get_source_by_username('AgeManagment') → Source(source_id='-1002333333')
    """
    from tg_parser.bot.tools import _resolve_source

    engine = create_async_engine(ingestion_db_url)
    try:
        sf = async_sessionmaker(engine, expire_on_commit=False)
        owner_id = await _seed_owner(sf)
        await _seed_source(sf, owner_id, source_id="-1002333333", channel_username="AgeManagment")

        async with sf() as session:
            repo = SAIngestionStateRepo(session)
            result = await _resolve_source("AgeManagment", repo)

        assert result is not None, (
            "_resolve_source should find channel 'AgeManagment' via username fallback"
        )
        assert result.source_id == "-1002333333"
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# I-4 — _resolve_source: backward compat — numeric PK still works
# ---------------------------------------------------------------------------


@requires_testcontainers
async def test_resolve_source_pk_path_preserved(ingestion_db_url: str):
    """I-4: _resolve_source with numeric source_id finds channel via PK (no fallback).

    Ensures that adding username-fallback does not break admin use-cases
    that supply the raw Telegram chat ID directly.
    """
    from tg_parser.bot.tools import _resolve_source

    engine = create_async_engine(ingestion_db_url)
    try:
        sf = async_sessionmaker(engine, expire_on_commit=False)
        owner_id = await _seed_owner(sf)
        await _seed_source(sf, owner_id, source_id="-1002444444", channel_username="AgeManagment")

        async with sf() as session:
            repo = SAIngestionStateRepo(session)
            result = await _resolve_source("-1002444444", repo)

        assert result is not None, "_resolve_source should find channel by numeric source_id"
        assert result.source_id == "-1002444444"
    finally:
        await engine.dispose()
