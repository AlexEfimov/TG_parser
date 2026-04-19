"""
PostgreSQL DDL smoke tests.

Replaces the old SQLite/Alembic migration tests (Session 22).
Verifies that init_*_schema() functions create the expected tables
on a live PostgreSQL test database.
"""

from sqlalchemy import text

from tg_parser.storage.sqlalchemy.schemas.ingestion_state import init_ingestion_state_schema
from tg_parser.storage.sqlalchemy.schemas.processing_storage import init_processing_storage_schema
from tg_parser.storage.sqlalchemy.schemas.raw_storage import init_raw_storage_schema


async def _get_tables(engine) -> set[str]:
    """Query pg_tables for user tables in the public schema."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        return {row[0] for row in result.fetchall()}


async def test_init_ingestion_state_schema(test_db):
    """init_ingestion_state_schema creates sources, comment_cursors, source_attempts."""
    engine = test_db.ingestion_state_engine

    await init_ingestion_state_schema(engine)

    tables = await _get_tables(engine)
    expected = {"sources", "comment_cursors", "source_attempts"}
    assert expected.issubset(tables), f"Missing tables: {expected - tables}"


async def test_init_raw_storage_schema(test_db):
    """init_raw_storage_schema creates raw_messages and raw_conflicts."""
    engine = test_db.raw_storage_engine

    await init_raw_storage_schema(engine)

    tables = await _get_tables(engine)
    expected = {"raw_messages", "raw_conflicts"}
    assert expected.issubset(tables), f"Missing tables: {expected - tables}"


async def test_init_processing_storage_schema(test_db):
    """init_processing_storage_schema creates all processing and agent tables."""
    engine = test_db.processing_storage_engine

    await init_processing_storage_schema(engine)

    tables = await _get_tables(engine)
    expected = {
        "processed_documents",
        "processing_failures",
        "topic_cards",
        "topic_bundles",
        "api_jobs",
        "agent_states",
        "task_history",
        "agent_stats",
        "handoff_history",
        "topic_links",
    }
    assert expected.issubset(tables), f"Missing tables: {expected - tables}"

    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'topic_bundles' AND indexname IN ("
                "'topic_bundles_current_unique_idx', 'topic_bundles_snapshot_unique_idx')"
            )
        )
        idx_names = {row[0] for row in result.fetchall()}
        assert idx_names == {
            "topic_bundles_current_unique_idx",
            "topic_bundles_snapshot_unique_idx",
        }, (
            "topic_bundles partial unique indexes missing — "
            "ON CONFLICT(topic_id, time_from, time_to) in topic_bundle_repo will fail. "
            "See DI-8 audit follow-up migration b8e2f7c1d9a3."
        )

    # F5-A Phase 3: content_hash column must be wired in via _ensure_content_hash_column.
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'processed_documents' "
                "AND column_name = 'content_hash'"
            )
        )
        assert result.fetchone() is not None, (
            "content_hash column missing after init_processing_storage_schema "
            "— did you forget to wire _ensure_content_hash_column()?"
        )
