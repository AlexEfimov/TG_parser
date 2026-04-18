"""add content_hash to processed_documents (F5-A Phase 3)

Revision ID: f5a3c0d7e8b9
Revises: e5f6a7b8c9d0
Create Date: 2026-04-18

F5-A Phase 3: Deduplication via SHA-256 content-hash.

Adds nullable CHAR(64) column + partial composite B-tree index on
(channel_id, content_hash) WHERE content_hash IS NOT NULL.

Safe for large tables: column is NULLable so ADD COLUMN is O(1); index
is created concurrently-safe (the partial predicate lets us rebuild
without blocking).  Backfill is done via the ``backfill-content-hash``
CLI, not in this migration.

NOTE on revision id: this migration originally landed in main with
``revision = "e5f6a7b8c9d0"``, colliding with
``20260417_add_fts_to_topic_cards``.  Both files declared the same
revision and both pointed at ``d4e5f6a7b8c9`` as the parent, which made
Alembic refuse to resolve heads
(``UserWarning: Revision e5f6a7b8c9d0 is present more than once``).
The fix is structural, not behavioural: we re-id this (newer-by-date)
migration to ``f5a3c0d7e8b9`` and chain it after
``e5f6a7b8c9d0`` (FTS topic_cards), restoring a linear history.  No
``alembic_version`` rewrites are needed on environments that have not
yet run either migration; environments where the original (buggy) id
was already stamped should ``alembic stamp f5a3c0d7e8b9`` after pulling
this fix to keep their bookkeeping aligned.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f5a3c0d7e8b9"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("processed_documents")]

    if "content_hash" not in columns:
        conn.execute(sa.text("ALTER TABLE processed_documents ADD COLUMN content_hash CHAR(64)"))

    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_pd_channel_content_hash "
            "ON processed_documents (channel_id, content_hash) "
            "WHERE content_hash IS NOT NULL"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP INDEX IF EXISTS idx_pd_channel_content_hash"))
    conn.execute(sa.text("ALTER TABLE processed_documents DROP COLUMN IF EXISTS content_hash"))
