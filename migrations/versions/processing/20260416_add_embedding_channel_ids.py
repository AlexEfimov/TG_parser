"""add channel_ids to document_embeddings + backfill

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-04-16

F4 Multi-Tenancy Phase 1: Per-embedding channel ownership for scoped search.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("document_embeddings")]

    if "channel_ids" not in columns:
        op.add_column(
            "document_embeddings",
            sa.Column("channel_ids", sa.ARRAY(sa.Text()), server_default="{}"),
        )

    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_de_channel_ids "
        "ON document_embeddings USING GIN(channel_ids)"
    ))

    # -- Backfill message embeddings from processed_documents ---------------
    conn.execute(sa.text("""
        UPDATE document_embeddings de
        SET channel_ids = ARRAY[pd.channel_id]
        FROM processed_documents pd
        WHERE de.source_ref = pd.source_ref
          AND de.entry_type = 'message'
          AND (de.channel_ids IS NULL OR de.channel_ids = '{}')
    """))

    # -- Backfill topic embeddings from topic_cards.sources_json ------------
    result = conn.execute(sa.text("""
        SELECT de.source_ref, tc.sources_json
        FROM document_embeddings de
        JOIN topic_cards tc ON de.topic_id = tc.id
        WHERE de.entry_type = 'topic'
          AND (de.channel_ids IS NULL OR de.channel_ids = '{}')
    """))
    import json
    for row in result.fetchall():
        try:
            sources = json.loads(row.sources_json) if row.sources_json else []
        except (json.JSONDecodeError, TypeError):
            sources = []
        if sources:
            conn.execute(
                sa.text(
                    "UPDATE document_embeddings SET channel_ids = :cids WHERE source_ref = :sr"
                ),
                {"cids": sources, "sr": row.source_ref},
            )


def downgrade() -> None:
    op.drop_index("idx_de_channel_ids", table_name="document_embeddings")
    op.drop_column("document_embeddings", "channel_ids")
