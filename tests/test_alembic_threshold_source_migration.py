"""Runtime smoke for the BUG-054 / ADR 0015 threshold_source migration.

Mirrors ``tests/test_alembic_subscription_target_migration.py`` (testcontainer
PG). Covers the ingestion-branch revision ``b9c8d7e6f5a4``:

- Upgrade adds the nullable ``threshold_source`` column + CHECK constraint.
- Pre-existing rows backfill to ``threshold_source='legacy'``.
- Re-running ``alembic upgrade head`` is idempotent (no-op).
- The CHECK rejects an out-of-domain value (and accepts the three legal ones
  plus NULL).
- Downgrade drops the column + constraint and re-upgrade restores them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _testcontainer_fixtures import (
    alembic_upgrade_for_branch,
    create_database,
    requires_testcontainers,
    sync_url_for_db,
)
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

pytest_plugins = ("_testcontainer_fixtures",)


_REPO_ROOT = Path(__file__).resolve().parents[1]
_PRE_REVISION = "a8b7c6d5e4f3"
_REVISION = "b9c8d7e6f5a4"


def _ingestion_alembic_config(container, db: str) -> Config:
    """Build an Alembic config bound to the per-test ingestion DB."""
    cfg = Config(str(_REPO_ROOT / "migrations" / "alembic_ingestion.ini"))
    cfg.set_main_option(
        "sqlalchemy.url",
        sync_url_for_db(container, db).replace("postgresql://", "postgresql+asyncpg://", 1),
    )
    cfg.set_main_option("db_name", "ingestion")
    return cfg


def _seed_interest_at_pre_revision(engine) -> None:
    """Insert a watch_interest row at the revision *before* threshold_source.

    The seeded row predates the column, so after the upgrade it must pick up
    the ``'legacy'`` backfill value. Uses the default admin user seeded by the
    ``add_users_and_ownership`` migration (mirrors the subscription_target
    migration smoke).
    """
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO watch_interests "
                "(user_id, target_kind, chat_id, title, channel_ids, threshold) "
                "SELECT id, 'chat', 12345, 'pre-existing', ARRAY['durov'], 0.6 "
                "FROM users LIMIT 1"
            )
        )


@requires_testcontainers
def test_threshold_source_migration_backfills_legacy(pgvector_container) -> None:
    """A row created before the migration backfills to ``threshold_source='legacy'``."""
    db = "alembic_ingestion"
    create_database(pgvector_container, db)
    cfg = _ingestion_alembic_config(pgvector_container, db)

    # Stop one revision short so the seeded row predates threshold_source.
    command.upgrade(cfg, _PRE_REVISION)
    engine = create_engine(sync_url_for_db(pgvector_container, db))
    try:
        _seed_interest_at_pre_revision(engine)
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")

    engine = create_engine(sync_url_for_db(pgvector_container, db))
    try:
        with engine.begin() as conn:
            rows = conn.execute(text("SELECT threshold_source FROM watch_interests")).fetchall()
            assert rows, "seeded row must survive the migration"
            assert all(str(r.threshold_source) == "legacy" for r in rows), (
                "all pre-existing rows must backfill to 'legacy'"
            )
    finally:
        engine.dispose()


@requires_testcontainers
def test_threshold_source_column_is_nullable(pgvector_container) -> None:
    """The column is added NULLABLE (expand phase — not NOT NULL yet)."""
    db = alembic_upgrade_for_branch(pgvector_container, "ingestion")
    engine = create_engine(sync_url_for_db(pgvector_container, db))
    try:
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT data_type, is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'watch_interests' "
                    "AND column_name = 'threshold_source'"
                )
            ).fetchone()
            assert row is not None, "threshold_source column must exist"
            assert row.is_nullable == "YES"
    finally:
        engine.dispose()


@requires_testcontainers
def test_threshold_source_check_constraint_rejects_bad_values(pgvector_container) -> None:
    """The CHECK accepts auto/manual/legacy/NULL and rejects anything else."""
    db = alembic_upgrade_for_branch(pgvector_container, "ingestion")
    engine = create_engine(sync_url_for_db(pgvector_container, db))
    try:
        with engine.begin() as conn:
            owner_id = conn.execute(text("SELECT id FROM users LIMIT 1")).scalar()
            assert owner_id is not None, "default admin user must be seeded"

        # Legal values (incl. NULL) all insert cleanly.
        for value in ("auto", "manual", "legacy", None):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO watch_interests "
                        "(user_id, target_kind, chat_id, title, channel_ids, "
                        "threshold, threshold_source) "
                        "VALUES (:uid, 'chat', 1, :title, ARRAY['durov'], 0.6, :ts)"
                    ),
                    {"uid": owner_id, "title": f"ok-{value}", "ts": value},
                )

        # An out-of-domain value is rejected by the CHECK.
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO watch_interests "
                        "(user_id, target_kind, chat_id, title, channel_ids, "
                        "threshold, threshold_source) "
                        "VALUES (:uid, 'chat', 1, 'bad', ARRAY['durov'], 0.6, 'bogus')"
                    ),
                    {"uid": owner_id},
                )
    finally:
        engine.dispose()


@requires_testcontainers
def test_threshold_source_migration_is_idempotent(pgvector_container) -> None:
    """Re-running alembic upgrade head must be a no-op (already at head)."""
    db = alembic_upgrade_for_branch(pgvector_container, "ingestion")
    cfg = _ingestion_alembic_config(pgvector_container, db)

    command.upgrade(cfg, "head")

    engine = create_engine(sync_url_for_db(pgvector_container, db))
    try:
        with engine.begin() as conn:
            present = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'watch_interests' "
                    "AND column_name = 'threshold_source'"
                )
            ).scalar()
            assert present == 1
    finally:
        engine.dispose()


@requires_testcontainers
def test_threshold_source_migration_downgrade_and_reupgrade(pgvector_container) -> None:
    """Downgrade drops the column + CHECK; re-upgrade restores them."""
    db = alembic_upgrade_for_branch(pgvector_container, "ingestion")
    cfg = _ingestion_alembic_config(pgvector_container, db)

    command.downgrade(cfg, _PRE_REVISION)

    engine = create_engine(sync_url_for_db(pgvector_container, db))
    try:
        with engine.begin() as conn:
            cols = {
                row.column_name
                for row in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'watch_interests'"
                    )
                )
            }
            assert "threshold_source" not in cols
            constraints = {
                row.conname
                for row in conn.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conname = 'watch_interests_threshold_source_known'"
                    )
                )
            }
            assert constraints == set()
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")
    engine = create_engine(sync_url_for_db(pgvector_container, db))
    try:
        with engine.begin() as conn:
            present = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'watch_interests' "
                    "AND column_name = 'threshold_source'"
                )
            ).scalar()
            assert present == 1
    finally:
        engine.dispose()
