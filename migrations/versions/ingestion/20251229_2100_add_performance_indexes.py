"""
Add performance indexes for concurrent access.

Revision ID: 20251229_2100_ingestion_indexes
Revises: 89f91e768b9b
Create Date: 2025-12-29 21:00:00

Session 24: Multi-user support - добавление индексов для оптимизации
concurrent access к ingestion_state.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251229_2100_ingestion_indexes"
down_revision: Union[str, None] = "89f91e768b9b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add performance indexes."""
    # Index on source_id for fast lookups
    op.create_index(
        "idx_ingestion_source_id",
        "ingestion_state",
        ["source_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove performance indexes."""
    op.drop_index("idx_ingestion_source_id", table_name="ingestion_state")

