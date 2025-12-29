"""initial raw schema (Universal: SQLite + PostgreSQL)

Revision ID: 5c658f04eff0
Revises: 89f91e768b9b
Create Date: 2025-12-29 18:59:08.283906

Session 24: Rewritten using SQLAlchemy ORM for universal compatibility.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5c658f04eff0'
down_revision: Union[str, None] = None  # Independent database
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create initial raw_storage schema (universal)."""
    
    # Create raw_messages table (TR-18, TR-20)
    op.create_table(
        'raw_messages',
        sa.Column('source_ref', sa.String(), nullable=False),
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('message_type', sa.String(), nullable=False),
        sa.Column('channel_id', sa.String(), nullable=False),
        sa.Column('date', sa.String(), nullable=False),
        sa.Column('text', sa.String(), nullable=False),
        sa.Column('thread_id', sa.String(), nullable=True),
        sa.Column('parent_message_id', sa.String(), nullable=True),
        sa.Column('language', sa.String(), nullable=True),
        sa.Column('raw_payload_json', sa.Text(), nullable=True),
        sa.Column('raw_payload_truncated', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('raw_payload_original_size_bytes', sa.Integer(), nullable=True),
        sa.Column('inserted_at', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('source_ref'),
        sa.CheckConstraint("message_type IN ('post', 'comment')", name='raw_messages_type_check')
    )
    
    op.create_index('raw_messages_channel_date_idx', 'raw_messages', ['channel_id', 'date'])
    op.create_index('raw_messages_thread_idx', 'raw_messages', ['thread_id'])
    op.create_index('raw_messages_type_idx', 'raw_messages', ['message_type'])
    
    # Create raw_conflicts table (TR-8)
    op.create_table(
        'raw_conflicts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_ref', sa.String(), nullable=False),
        sa.Column('observed_at', sa.String(), nullable=False),
        sa.Column('reason', sa.String(), nullable=False),
        sa.Column('new_payload_json', sa.Text(), nullable=True),
        sa.Column('new_text', sa.String(), nullable=True),
        sa.Column('new_date', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_index('raw_conflicts_source_time_idx', 'raw_conflicts', ['source_ref', 'observed_at'])


def downgrade() -> None:
    """Drop raw_storage schema."""
    op.drop_table('raw_conflicts')
    op.drop_table('raw_messages')

