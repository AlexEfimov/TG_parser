"""add FTS search_vector + GIN index to processed_documents

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-17

F5-A Phase 1: Hybrid search (FTS + pgvector).  Adds a STORED
tsvector column over (summary A / text_clean B) using simple + russian +
english text-search configurations, plus a GIN index for fast @@ lookups.

WARNING: ``ADD COLUMN ... GENERATED ... STORED`` triggers a table rewrite
on PostgreSQL.  For production databases > 1M rows apply during a
maintenance window.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("processed_documents")]

    if "search_vector" not in columns:
        conn.execute(sa.text(
            "ALTER TABLE processed_documents ADD COLUMN search_vector tsvector "
            "GENERATED ALWAYS AS ("
            "setweight(to_tsvector('simple',  coalesce(summary, '')),    'A') || "
            "setweight(to_tsvector('russian', coalesce(text_clean, '')), 'B') || "
            "setweight(to_tsvector('english', coalesce(text_clean, '')), 'B')"
            ") STORED"
        ))

    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_pd_search_vector "
        "ON processed_documents USING GIN(search_vector)"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP INDEX IF EXISTS idx_pd_search_vector"))
    conn.execute(sa.text(
        "ALTER TABLE processed_documents DROP COLUMN IF EXISTS search_vector"
    ))
