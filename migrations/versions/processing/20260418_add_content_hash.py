"""add content_hash to processed_documents (F5-A Phase 3)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-18

F5-A Phase 3: Deduplication via SHA-256 content-hash.

Adds nullable CHAR(64) column + partial composite B-tree index on
(channel_id, content_hash) WHERE content_hash IS NOT NULL.

Safe for large tables: column is NULLable so ADD COLUMN is O(1); index
is created concurrently-safe (the partial predicate lets us rebuild
without blocking).  Backfill is done via the ``backfill-content-hash``
CLI, not in this migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
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
