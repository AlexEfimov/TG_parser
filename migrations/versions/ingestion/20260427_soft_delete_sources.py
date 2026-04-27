"""soft-delete for sources (BUG-002 mitigation M3)

Revision ID: d7e8f9a0b1c4
Revises: c8e9f0a1b2c3
Create Date: 2026-04-27

BUG-002 mitigation M3: replace hard-delete of channels with a
deleted_at timestamp on the `sources` row. Related raw_messages,
processed_documents, topic_cards, etc. are intentionally NOT
cascade-deleted on remove_channel anymore — see
`docs/notes/BUG_LOG.md` § BUG-002 § «Mitigation backlog».

Schema change is purely additive:

* `sources.deleted_at TIMESTAMPTZ NULL` — when set, the source is
  treated as deleted by all read paths in `IngestionStateRepo`.
* Partial index `idx_sources_active` — `WHERE deleted_at IS NULL`
  to keep the hot "list all active sources" path index-only.

This is forward-compatible: existing rows get `deleted_at = NULL`
implicitly. No backfill is performed for previously hard-deleted
channels (per HM-2 default in the hot-fix start prompt).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7e8f9a0b1c4"
down_revision: str | None = "c8e9f0a1b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("sources")]
    if "deleted_at" not in columns:
        conn.execute(
            sa.text("ALTER TABLE sources ADD COLUMN deleted_at TIMESTAMPTZ NULL")
        )

    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_sources_active "
            "ON sources(source_id) WHERE deleted_at IS NULL"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP INDEX IF EXISTS idx_sources_active"))
    op.drop_column("sources", "deleted_at")
