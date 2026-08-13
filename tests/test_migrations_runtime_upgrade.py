"""Runtime mirror of ``test_migrations_self_contained`` (DI-9 phase 2).

Sprint A.6 / 19.04.2026.

Spins one pgvector PG17 container per test session (see
``tests/_testcontainer_fixtures.py``) and, for each logical branch
(``ingestion`` / ``raw`` / ``processing``), creates a fresh DB and runs
``alembic upgrade head`` against it.  Then asserts that:

1. Every table declared for the branch in ``METADATA_BY_DB`` exists in
   the resulting schema (catches missed ``CREATE TABLE`` in a migration
   or ``IF NOT EXISTS`` masking silently wrong prior state).
2. The ``alembic_version_<branch>`` bookkeeping table exists.
3. Critical partial / composite indexes that AST analysis can't verify
   are present (e.g. ``topic_bundles_current_unique_idx`` / the FTS GIN
   indexes — these come in via ``op.execute(text(...))`` in later
   migrations and wouldn't show up as ``op.create_index`` calls).

What this adds on top of the CI's existing ``alembic-guardrail`` job
(``tg-parser db upgrade/downgrade/check``): a **locally-reproducible**
smoke that doesn't depend on the ``postgres-service`` side-car pattern
and runs against a container spun from the same image we use in the
``test`` job, so results are stable across developer machines / CI.

Requires ``TEST_TESTCONTAINERS=1`` and a reachable Docker daemon;
otherwise every test here is skipped.
"""

from __future__ import annotations

import pytest
from _testcontainer_fixtures import (
    alembic_upgrade_for_branch,
    requires_testcontainers,
    sync_url_for_db,
)
from sqlalchemy import create_engine, text

# ``pgvector_container`` fixture comes from ``_testcontainer_fixtures``;
# registering the module as a pytest plugin makes the fixture visible to
# this file's test functions without triggering ruff's F811 when we also
# accept it as a function parameter.
pytest_plugins = ("_testcontainer_fixtures",)

BRANCHES = ("ingestion", "raw", "processing")

# Ground truth derived from ``tg_parser.storage.sqlalchemy._metadata``:
# every ``Table(name, <BRANCH>_METADATA, ...)`` declaration plus the
# ``alembic_version_<branch>`` bookkeeping table that alembic itself
# creates on first upgrade.
EXPECTED_TABLES: dict[str, set[str]] = {
    "ingestion": {
        "sources",
        "comment_cursors",
        "source_attempts",
        "users",
        "user_auth_mappings",
        "digest_subscriptions",
        "watch_interests",
        "watch_matches",
        "workspaces",
        "workspace_sources",
        "alembic_version_ingestion",
    },
    "raw": {
        "raw_messages",
        "raw_conflicts",
        "alembic_version_raw",
    },
    "processing": {
        "processed_documents",
        "processing_failures",
        "processing_dedup_drops",
        "topic_cards",
        "topic_bundles",
        "topic_card_versions",
        "api_jobs",
        "agent_states",
        "task_history",
        "agent_stats",
        "handoff_history",
        "document_embeddings",
        "topic_links",
        "alembic_version_processing",
    },
}

# Indexes that were added by later migrations via raw SQL / partial /
# GIN, where the static guardrail wouldn't pick up drift.  Each of
# these is a real runtime requirement for a production-critical feature
# (dedup uniqueness, hybrid search FTS, vector retrieval filters).
CRITICAL_INDEXES: dict[str, set[str]] = {
    "ingestion": {
        "idx_digest_subscriptions_active_cron",  # partial, WHERE is_active
        "idx_watch_interests_active",  # partial, WHERE is_active (F11)
        "idx_watch_matches_interest_created",  # composite for cursor reads (F11)
    },
    "raw": set(),
    "processing": {
        "topic_bundles_current_unique_idx",  # partial UNIQUE
        "topic_bundles_snapshot_unique_idx",  # partial UNIQUE
        "idx_pd_search_vector",  # GIN, added in a later migration
        "idx_tc_search_vector",  # GIN, added in a later migration
        "idx_pd_channel_content_hash",  # partial composite, F5-A Phase 3
        "idx_de_entry_type",
        "idx_de_channel_ids",  # GIN on ARRAY
        "idx_topic_cards_resummarize_candidates",  # partial index, F5-C
        "idx_topic_card_versions_topic_created",  # composite DESC, F5-C
        "idx_pdd_channel_raw_hash",  # partial composite, BUG-097 (b)
    },
}


@requires_testcontainers
@pytest.mark.parametrize("branch", BRANCHES)
def test_alembic_upgrade_head_runtime(pgvector_container, branch):
    """``alembic upgrade head`` builds the full expected schema per branch."""
    db = alembic_upgrade_for_branch(pgvector_container, branch)
    engine = create_engine(sync_url_for_db(pgvector_container, db))
    try:
        with engine.connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                ).fetchall()
            }
            indexes = {
                row[0]
                for row in conn.execute(
                    text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
                ).fetchall()
            }
    finally:
        engine.dispose()

    missing_tables = EXPECTED_TABLES[branch] - tables
    assert not missing_tables, (
        f"branch {branch!r}: alembic upgrade head did not create expected "
        f"tables: {sorted(missing_tables)}\n"
        f"Got: {sorted(tables)}"
    )

    expected_indexes = CRITICAL_INDEXES.get(branch, set())
    missing_indexes = expected_indexes - indexes
    assert not missing_indexes, (
        f"branch {branch!r}: alembic upgrade head did not create critical "
        f"indexes: {sorted(missing_indexes)}\n"
        f"Got indexes on public schema: {sorted(indexes)}"
    )


@requires_testcontainers
def test_processing_pgvector_extension_enabled(pgvector_container):
    """``document_embeddings.embedding`` column is typed ``vector`` (pgvector).

    This catches the case where ``CREATE EXTENSION vector`` was accidentally
    dropped from the migration chain: without it, the ``vector(1536)``
    column type would fail to resolve at upgrade time and subsequent
    RAG queries would error at runtime instead of at migration time.
    """
    db = alembic_upgrade_for_branch(pgvector_container, "processing")
    engine = create_engine(sync_url_for_db(pgvector_container, db))
    try:
        with engine.connect() as conn:
            ext_present = conn.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            ).scalar()
            assert ext_present == 1, "pgvector extension not enabled after alembic upgrade"

            col_type = conn.execute(
                text(
                    "SELECT format_type(atttypid, atttypmod) "
                    "FROM pg_attribute "
                    "WHERE attrelid = 'document_embeddings'::regclass "
                    "AND attname = 'embedding'"
                )
            ).scalar()
    finally:
        engine.dispose()

    assert col_type and col_type.startswith("vector"), (
        f"expected document_embeddings.embedding to be pgvector 'vector(...)', got {col_type!r}"
    )
