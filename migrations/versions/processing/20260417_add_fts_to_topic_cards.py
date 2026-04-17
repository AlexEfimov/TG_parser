"""add FTS search_vector + GIN index to topic_cards

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-17

F5-A Phase 1: Hybrid search (FTS + pgvector).  Adds a STORED
tsvector column over (title A / summary + scope_in_json B) using
simple + russian + english text-search configurations, plus a GIN
index for fast @@ lookups.

WARNING: ``ADD COLUMN ... GENERATED ... STORED`` triggers a table rewrite
on PostgreSQL.  For production databases > 1M rows apply during a
maintenance window.
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
    columns = [c["name"] for c in inspector.get_columns("topic_cards")]

    if "search_vector" not in columns:
        conn.execute(
            sa.text(
                "ALTER TABLE topic_cards ADD COLUMN search_vector tsvector "
                "GENERATED ALWAYS AS ("
                "setweight(to_tsvector('simple',  coalesce(title, '')), 'A') || "
                "setweight(to_tsvector('russian', coalesce(summary, '') || ' ' || coalesce(scope_in_json, '')), 'B') || "
                "setweight(to_tsvector('english', coalesce(summary, '') || ' ' || coalesce(scope_in_json, '')), 'B')"
                ") STORED"
            )
        )

    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_tc_search_vector "
            "ON topic_cards USING GIN(search_vector)"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP INDEX IF EXISTS idx_tc_search_vector"))
    conn.execute(sa.text("ALTER TABLE topic_cards DROP COLUMN IF EXISTS search_vector"))
