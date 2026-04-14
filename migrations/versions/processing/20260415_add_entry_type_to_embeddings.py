"""add entry_type and topic_id to document_embeddings

Revision ID: a1b2c3d4e5f6
Revises: f40d85317f03
Create Date: 2026-04-15

F5-A: Persistent KB + Topic RAG — extend document_embeddings for topic embeddings.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f40d85317f03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("document_embeddings")]

    if "entry_type" not in columns:
        op.add_column(
            "document_embeddings",
            sa.Column("entry_type", sa.Text(), nullable=False, server_default="message"),
        )

    if "topic_id" not in columns:
        op.add_column(
            "document_embeddings",
            sa.Column("topic_id", sa.Text(), nullable=True),
        )

    try:
        op.drop_constraint(
            "document_embeddings_source_ref_fkey",
            "document_embeddings",
            type_="foreignkey",
        )
    except Exception:
        pass

    op.create_index(
        "idx_de_entry_type",
        "document_embeddings",
        ["entry_type"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("idx_de_entry_type", table_name="document_embeddings")
    op.drop_column("document_embeddings", "topic_id")
    op.drop_column("document_embeddings", "entry_type")
