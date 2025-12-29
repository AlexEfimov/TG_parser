"""initial_ingestion_schema (Universal: SQLite + PostgreSQL)

Revision ID: 89f91e768b9b
Revises: 
Create Date: 2025-12-29 18:58:53.265257

Session 24: Rewritten using SQLAlchemy ORM for universal compatibility.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '89f91e768b9b'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create initial ingestion_state schema (universal)."""
    
    # Create sources table (TR-15)
    op.create_table(
        'sources',
        sa.Column('source_id', sa.String(), nullable=False),
        sa.Column('channel_id', sa.String(), nullable=False),
        sa.Column('channel_username', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('include_comments', sa.Boolean(), nullable=False),
        sa.Column('history_from', sa.String(), nullable=True),
        sa.Column('history_to', sa.String(), nullable=True),
        sa.Column('poll_interval_seconds', sa.Integer(), nullable=True),
        sa.Column('batch_size', sa.Integer(), nullable=True),
        sa.Column('last_post_id', sa.String(), nullable=True),
        sa.Column('backfill_completed_at', sa.String(), nullable=True),
        sa.Column('last_attempt_at', sa.String(), nullable=True),
        sa.Column('last_success_at', sa.String(), nullable=True),
        sa.Column('fail_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_error', sa.String(), nullable=True),
        sa.Column('rate_limit_until', sa.String(), nullable=True),
        sa.Column('comments_unavailable', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('source_id'),
        sa.CheckConstraint("status IN ('active', 'paused', 'error')", name='sources_status_check')
    )
    
    op.create_index('sources_status_idx', 'sources', ['status'])
    op.create_index('sources_channel_id_idx', 'sources', ['channel_id'])
    
    # Create comment_cursors table (TR-7, TR-15)
    op.create_table(
        'comment_cursors',
        sa.Column('source_id', sa.String(), nullable=False),
        sa.Column('thread_id', sa.String(), nullable=False),
        sa.Column('last_comment_id', sa.String(), nullable=True),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('source_id', 'thread_id')
    )
    
    op.create_index('comment_cursors_thread_idx', 'comment_cursors', ['thread_id'])
    
    # Create source_attempts table (TR-11, TR-15)
    op.create_table(
        'source_attempts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_id', sa.String(), nullable=False),
        sa.Column('attempt_at', sa.String(), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('error_class', sa.String(), nullable=True),
        sa.Column('error_message', sa.String(), nullable=True),
        sa.Column('details_json', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_index('source_attempts_source_time_idx', 'source_attempts', ['source_id', 'attempt_at'])


def downgrade() -> None:
    """Drop ingestion_state schema."""
    op.drop_table('source_attempts')
    op.drop_table('comment_cursors')
    op.drop_table('sources')

