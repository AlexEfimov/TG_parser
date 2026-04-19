"""Cross-check: ``Table()`` declarations match alembic ``CREATE TABLE`` chain.

DI-1 follow-up (Sprint A.2, 19.04.2026)
---------------------------------------

``alembic check`` (CI guardrail wired in DI-4) catches schema drift between
``MetaData`` and a live PostgreSQL database, but only when:

- ``alembic check`` is actually run (skipped means silently green); and
- the database is fresh / unmodified by side-effects.

This test is a static, offline cousin of that runtime check.  It uses the
same AST analyzer as ``tests/test_migrations_self_contained.py`` (DI-9
phase 1) to enumerate every table created by an ``op.create_table(...)``
call or a raw ``CREATE TABLE [IF NOT EXISTS] foo`` statement inside the
migration chain, and asserts that the set of declared tables in
``tg_parser/storage/sqlalchemy/_metadata.py`` matches it exactly per
branch.

Catches two failure modes ``alembic check`` would also catch but earlier:

1. **Missing declaration** — a new migration adds a table but
   ``_metadata.py`` is not updated → ``alembic check`` would silently
   miss any drift on that table forever.
2. **Stale declaration** — ``_metadata.py`` declares a table that was
   removed from migrations → ``alembic check`` would correctly report
   drift, but this test pinpoints which branch and table to remove.
"""

from __future__ import annotations

import pytest
from test_migrations_self_contained import _parse_revisions  # type: ignore[import-not-found]

from tg_parser.storage.sqlalchemy._metadata import (
    INGESTION_METADATA,
    PROCESSING_METADATA,
    RAW_METADATA,
)

_BRANCHES = {
    "ingestion": INGESTION_METADATA,
    "raw": RAW_METADATA,
    "processing": PROCESSING_METADATA,
}


@pytest.mark.parametrize("branch,metadata", list(_BRANCHES.items()))
def test_metadata_tables_match_migration_creates(branch: str, metadata) -> None:
    declared = {t.name for t in metadata.tables.values()}

    migrated: set[str] = set()
    for rev in _parse_revisions(branch):
        migrated |= rev["creates"]

    missing_in_metadata = sorted(migrated - declared)
    extra_in_metadata = sorted(declared - migrated)

    assert not missing_in_metadata and not extra_in_metadata, (
        f"Branch {branch!r}: _metadata.py vs migration CREATE chain mismatch.\n"
        f"  declared in _metadata.py but not created by any migration: {extra_in_metadata}\n"
        f"  created by migrations but not declared in _metadata.py:    {missing_in_metadata}\n"
        "Fix: update tg_parser/storage/sqlalchemy/_metadata.py to mirror the migration chain."
    )
