"""
Add performance indexes for concurrent access.

Revision ID: 20251229_2100_raw_indexes
Revises: 5c658f04eff0
Create Date: 2025-12-29 21:00:00

Session 24: Multi-user support - добавление индексов для оптимизации
concurrent access к raw_messages.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251229_2100_raw_indexes"
down_revision: Union[str, None] = "5c658f04eff0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add performance indexes."""
    # Index on source_ref for fast lookups by source
    op.create_index(
        "idx_raw_source_ref",
        "raw_messages",
        ["source_ref"],
        unique=False,
    )
    
    # Index on channel_id for fast lookups by channel
    op.create_index(
        "idx_raw_channel_id",
        "raw_messages",
        ["channel_id"],
        unique=False,
    )
    
    # Composite index on (source_ref, channel_id) for combined queries
    op.create_index(
        "idx_raw_source_channel",
        "raw_messages",
        ["source_ref", "channel_id"],
        unique=False,
    )
    
    # Index on date for time-based queries
    op.create_index(
        "idx_raw_date",
        "raw_messages",
        ["date"],
        unique=False,
    )


def downgrade() -> None:
    """Remove performance indexes."""
    op.drop_index("idx_raw_date", table_name="raw_messages")
    op.drop_index("idx_raw_source_channel", table_name="raw_messages")
    op.drop_index("idx_raw_channel_id", table_name="raw_messages")
    op.drop_index("idx_raw_source_ref", table_name="raw_messages")

