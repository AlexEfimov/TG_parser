"""bootstrap document_embeddings + add entry_type/topic_id

Revision ID: a1b2c3d4e5f6
Revises: f40d85317f03
Create Date: 2026-04-15
Updated:    2026-04-19 (Dev Resurrection — added defensive bootstrap; see DI-8)

F5-A: Persistent KB + Topic RAG — extend document_embeddings for topic embeddings.

Historical note (Dev Resurrection 19.04.2026):
Originally this migration ALTER'ed document_embeddings assuming the table
already existed. In practice it only existed because init_db.py fell back
to Base.metadata.create_all()/EMBEDDING_DDL whenever alembic CLI failed
on multi-head misconfiguration. Once the CLI was fixed, this migration
started failing with NoSuchTableError on a clean DB. We now create the
table (and pgvector extension) defensively if missing, then proceed with
the original ALTERs. Both branches are idempotent and safe on existing
prod DBs that already have the table. Long-term cleanup (move bootstrap
to its own migration / drop EMBEDDING_DDL) tracked as DI-8/DI-9 in
docs/notes/FUTURE_FEATURES.md.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f40d85317f03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()

    inspector = sa.inspect(conn)

    if not inspector.has_table("document_embeddings"):
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute(
            """
            CREATE TABLE document_embeddings (
              source_ref TEXT PRIMARY KEY,
              embedding vector(1536),
              model TEXT NOT NULL,
              created_at TEXT NOT NULL,
              metadata_json TEXT
            )
            """
        )
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

    op.execute(
        "ALTER TABLE document_embeddings "
        "DROP CONSTRAINT IF EXISTS document_embeddings_source_ref_fkey"
    )

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
