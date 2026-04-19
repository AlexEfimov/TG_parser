"""bootstrap topic_links + topic_bundles partial unique indexes

Revision ID: b8e2f7c1d9a3
Revises: f5a3c0d7e8b9
Create Date: 2026-04-19

DI-8 audit follow-up (Sprint A, Session 50):

The Dev Resurrection audit (19 апреля 2026) revealed two objects that
``init_processing_storage_schema()`` (PROCESSING_STORAGE_DDL +
EMBEDDING_DDL) creates but **no alembic migration** does.  On a fresh
database initialised through ``tg-parser db upgrade --db processing``
alone (i.e. without the legacy DDL fallback), these are latent runtime
bugs:

1. ``topic_links`` (cross-channel topic similarity, Cross-dev 3) — the
   table simply does not exist after ``alembic upgrade head``.  Any call
   into ``SATopicLinkRepo`` (used by ``topic_linking_service`` during
   cross-channel topicization) raises ``UndefinedTableError``.

2. ``topic_bundles_current_unique_idx`` /
   ``topic_bundles_snapshot_unique_idx`` — partial unique indexes
   declared in ``processing_storage.py`` but never migrated.
   ``SATopicBundleRepo.upsert`` for snapshot rows uses
   ``INSERT ... ON CONFLICT(topic_id, time_from, time_to) WHERE ... DO UPDATE``
   which PostgreSQL rejects without a matching unique index
   (``no unique or exclusion constraint matching the ON CONFLICT
   specification``).  The ``current`` (NULL time_range) path uses
   DELETE+INSERT and does not strictly require the index, but we
   add both partials so the schema matches the documented invariant
   (``docs/DATA_ARCHITECTURE.md`` §242–243,
   ``docs/architecture.md`` §478) and a future MERGE/upsert refactor
   stays safe.

This migration is idempotent (``CREATE TABLE IF NOT EXISTS`` /
``CREATE UNIQUE INDEX IF NOT EXISTS``) so it is safe on production
databases that already ran the DDL fallback at any point in the past.

See ``docs/notes/FUTURE_FEATURES.md`` DI-8 entry for the full audit
matrix, and DI-9 for the systemic ``test_migrations_self_contained``
guard that should prevent this class of bug in the future.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8e2f7c1d9a3"
down_revision: str | None = "f5a3c0d7e8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text("""
            CREATE TABLE IF NOT EXISTS topic_links (
              topic_id_a TEXT NOT NULL,
              topic_id_b TEXT NOT NULL,
              similarity_score REAL NOT NULL,
              shared_keywords_json TEXT,
              created_at TEXT NOT NULL,
              PRIMARY KEY (topic_id_a, topic_id_b)
            )
        """)
    )

    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS topic_links_a_idx ON topic_links(topic_id_a)"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS topic_links_b_idx ON topic_links(topic_id_b)"))
    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS topic_links_score_idx ON topic_links(similarity_score DESC)"
        )
    )

    conn.execute(
        sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS topic_bundles_current_unique_idx "
            "ON topic_bundles(topic_id) "
            "WHERE time_from IS NULL AND time_to IS NULL"
        )
    )
    conn.execute(
        sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS topic_bundles_snapshot_unique_idx "
            "ON topic_bundles(topic_id, time_from, time_to) "
            "WHERE time_from IS NOT NULL AND time_to IS NOT NULL"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("DROP INDEX IF EXISTS topic_bundles_snapshot_unique_idx"))
    conn.execute(sa.text("DROP INDEX IF EXISTS topic_bundles_current_unique_idx"))

    conn.execute(sa.text("DROP INDEX IF EXISTS topic_links_score_idx"))
    conn.execute(sa.text("DROP INDEX IF EXISTS topic_links_b_idx"))
    conn.execute(sa.text("DROP INDEX IF EXISTS topic_links_a_idx"))
    conn.execute(sa.text("DROP TABLE IF EXISTS topic_links"))
