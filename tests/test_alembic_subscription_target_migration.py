"""Runtime smoke for ADR 0008 subscription_target migration (testcontainer PG).

Covers Phase 1 of the Wave 1 step 4 quality gate:
- Upgrade adds ``target_kind`` ENUM + ``channel_id`` to both tables.
- Default value backfills existing rows to ``target_kind='chat'``.
- Re-running ``alembic upgrade head`` is idempotent (no-op).
- ENUM exposes exactly the two declared values in ``pg_enum``.
- Downgrade reverses the change when no channel rows exist; it must
  refuse to drop the column when channel rows are present (otherwise we
  silently lose targeting metadata).
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


def _ingestion_alembic_config(container, db: str) -> Config:
    """Build an Alembic config bound to the per-test ingestion DB."""
    cfg = Config(str(_REPO_ROOT / "migrations" / "alembic_ingestion.ini"))
    cfg.set_main_option(
        "sqlalchemy.url",
        sync_url_for_db(container, db).replace("postgresql://", "postgresql+asyncpg://", 1),
    )
    cfg.set_main_option("db_name", "ingestion")
    return cfg


@requires_testcontainers
def test_subscription_target_migration_backfills_chat_kind(pgvector_container) -> None:
    """Pre-existing rows backfill to ``target_kind='chat'``; the transient
    server default is then removed so new inserts must set it explicitly.

    The migration adds ``target_kind`` with a *temporary* ``server_default='chat'``
    so existing rows backfill, then drops the default
    (``op.alter_column(..., server_default=None)``).  To exercise the backfill we
    seed a row at the revision *before* the migration (when ``target_kind`` does
    not yet exist), upgrade, and assert the row picked up ``'chat'``.  A second
    insert that omits ``target_kind`` must now raise, proving the default was
    correctly removed rather than left in place.
    """
    db = "alembic_ingestion"
    create_database(pgvector_container, db)
    cfg = _ingestion_alembic_config(pgvector_container, db)

    # Stop one revision short so the seeded row predates the target_kind column.
    command.upgrade(cfg, "f1a2b3c4d5e6")
    engine = create_engine(sync_url_for_db(pgvector_container, db))
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO digest_subscriptions "
                    "(owner_id, chat_id, name, channel_ids) "
                    "SELECT id, 12345, 'pre-existing', ARRAY['durov'] "
                    "FROM users LIMIT 1"
                )
            )
    finally:
        engine.dispose()

    # Run the polymorphic-target migration (adds target_kind, backfills, then
    # drops the server default).
    command.upgrade(cfg, "head")

    engine = create_engine(sync_url_for_db(pgvector_container, db))
    try:
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT target_kind, channel_id FROM digest_subscriptions "
                    "WHERE name = 'pre-existing'"
                )
            ).fetchone()
            assert row is not None, "seeded pre-existing row must survive the migration"
            assert str(row.target_kind) == "chat"
            assert row.channel_id is None

        # Default was dropped after backfill: a new insert omitting target_kind
        # must fail rather than silently defaulting to 'chat'.
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO digest_subscriptions "
                        "(owner_id, chat_id, name, channel_ids) "
                        "SELECT id, 67890, 'post-default-removed', ARRAY['durov'] "
                        "FROM users LIMIT 1"
                    )
                )
    finally:
        engine.dispose()


@requires_testcontainers
def test_subscription_target_migration_adds_columns_to_watch_interests(
    pgvector_container,
) -> None:
    """Symmetric column add on watch_interests (regression: easy to forget one table)."""
    db = alembic_upgrade_for_branch(pgvector_container, "ingestion")
    engine = create_engine(sync_url_for_db(pgvector_container, db))
    try:
        with engine.begin() as conn:
            cols = {
                row.column_name: (row.data_type, row.is_nullable)
                for row in conn.execute(
                    text(
                        "SELECT column_name, data_type, is_nullable "
                        "FROM information_schema.columns "
                        "WHERE table_name = 'watch_interests'"
                    )
                )
            }
            assert "target_kind" in cols
            assert cols["target_kind"][1] == "NO"
            assert "channel_id" in cols
            assert cols["channel_id"][1] == "YES"
            assert cols["chat_id"][1] == "YES"
    finally:
        engine.dispose()


@requires_testcontainers
def test_subscription_target_enum_values_in_pg_type(pgvector_container) -> None:
    """ENUM exposes exactly the two declared values; rejects 'webhook' (anti-scope)."""
    db = alembic_upgrade_for_branch(pgvector_container, "ingestion")
    engine = create_engine(sync_url_for_db(pgvector_container, db))
    try:
        with engine.begin() as conn:
            values = {
                row.enumlabel
                for row in conn.execute(
                    text(
                        "SELECT enumlabel FROM pg_enum e "
                        "JOIN pg_type t ON e.enumtypid = t.oid "
                        "WHERE t.typname = 'target_kind'"
                    )
                )
            }
            assert values == {"chat", "channel"}
    finally:
        engine.dispose()


@requires_testcontainers
def test_subscription_target_migration_is_idempotent(pgvector_container) -> None:
    """Re-running alembic upgrade head must be a no-op (already at head)."""
    db = alembic_upgrade_for_branch(pgvector_container, "ingestion")
    cfg = _ingestion_alembic_config(pgvector_container, db)

    command.upgrade(cfg, "head")

    engine = create_engine(sync_url_for_db(pgvector_container, db))
    try:
        with engine.begin() as conn:
            values = {
                row.enumlabel
                for row in conn.execute(
                    text(
                        "SELECT enumlabel FROM pg_enum e "
                        "JOIN pg_type t ON e.enumtypid = t.oid "
                        "WHERE t.typname = 'target_kind'"
                    )
                )
            }
            assert values == {"chat", "channel"}
    finally:
        engine.dispose()


@requires_testcontainers
def test_subscription_target_migration_downgrade_when_no_channel_rows(
    pgvector_container,
) -> None:
    """Downgrade succeeds when chat_id is set everywhere and re-upgrade restores."""
    db = alembic_upgrade_for_branch(pgvector_container, "ingestion")
    cfg = _ingestion_alembic_config(pgvector_container, db)

    command.downgrade(cfg, "f1a2b3c4d5e6")

    engine = create_engine(sync_url_for_db(pgvector_container, db))
    try:
        with engine.begin() as conn:
            cols = {
                row.column_name
                for row in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'digest_subscriptions'"
                    )
                )
            }
            assert "target_kind" not in cols
            assert "channel_id" not in cols

            chat_nullable = conn.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'digest_subscriptions' AND column_name = 'chat_id'"
                )
            ).scalar()
            assert chat_nullable == "NO"
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")


@requires_testcontainers
def test_subscription_target_migration_downgrade_blocks_when_channel_rows_present(
    pgvector_container,
) -> None:
    """Downgrade must refuse to lose data when channel-targeted rows exist."""
    db = alembic_upgrade_for_branch(pgvector_container, "ingestion")
    engine = create_engine(sync_url_for_db(pgvector_container, db))
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO digest_subscriptions "
                    "(owner_id, target_kind, chat_id, channel_id, name, channel_ids) "
                    "SELECT id, 'channel', NULL, '@dl', 'channel-mig', ARRAY['durov'] "
                    "FROM users LIMIT 1"
                )
            )
    finally:
        engine.dispose()

    cfg = _ingestion_alembic_config(pgvector_container, db)
    with pytest.raises(RuntimeError, match="NULL chat_id"):
        command.downgrade(cfg, "f1a2b3c4d5e6")
