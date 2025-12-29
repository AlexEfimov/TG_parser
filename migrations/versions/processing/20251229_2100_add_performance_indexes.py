"""
Add performance indexes for concurrent access.

Revision ID: 20251229_2100_processing_indexes
Revises: f40d85317f03
Create Date: 2025-12-29 21:00:00

Session 24: Multi-user support - добавление индексов для оптимизации
concurrent access к processing_storage (documents, topics, agents).
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251229_2100_processing_indexes"
down_revision: Union[str, None] = "f40d85317f03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add performance indexes."""
    # === Processed Documents Indexes ===
    
    # Index on source_ref for fast lookups by source
    op.create_index(
        "idx_processed_source_ref",
        "processed_documents",
        ["source_ref"],
        unique=False,
    )
    
    # Index on channel_id for fast lookups by channel
    op.create_index(
        "idx_processed_channel_id",
        "processed_documents",
        ["channel_id"],
        unique=False,
    )
    
    # === Topics Indexes ===
    
    # Index on channel_id for fast lookups by channel
    op.create_index(
        "idx_topics_channel_id",
        "topics",
        ["channel_id"],
        unique=False,
    )
    
    # === Agent Registry Indexes (Phase 3B) ===
    
    # Index on agent_type for filtering by type
    op.create_index(
        "idx_agents_type",
        "agent_registry",
        ["agent_type"],
        unique=False,
    )
    
    # Index on is_active for filtering active agents
    op.create_index(
        "idx_agents_active",
        "agent_registry",
        ["is_active"],
        unique=False,
    )
    
    # Composite index on (agent_type, is_active) for combined queries
    op.create_index(
        "idx_agents_type_active",
        "agent_registry",
        ["agent_type", "is_active"],
        unique=False,
    )


def downgrade() -> None:
    """Remove performance indexes."""
    # Agent registry indexes
    op.drop_index("idx_agents_type_active", table_name="agent_registry")
    op.drop_index("idx_agents_active", table_name="agent_registry")
    op.drop_index("idx_agents_type", table_name="agent_registry")
    
    # Topics indexes
    op.drop_index("idx_topics_channel_id", table_name="topics")
    
    # Processed documents indexes
    op.drop_index("idx_processed_channel_id", table_name="processed_documents")
    op.drop_index("idx_processed_source_ref", table_name="processed_documents")

