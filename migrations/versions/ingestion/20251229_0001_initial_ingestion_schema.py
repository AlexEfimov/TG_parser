"""Initial ingestion schema

Revision ID: 0001_ingestion
Revises: 
Create Date: 2025-12-29

Creates initial schema for ingestion_state.sqlite:
- sources table (TR-15)
- comment_cursors table (TR-7, TR-15)
- source_attempts table (TR-11, TR-15)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0001_ingestion'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create initial ingestion_state schema."""
    
    # Create sources table (TR-15)
    op.execute("""
        CREATE TABLE IF NOT EXISTS sources (
          source_id TEXT PRIMARY KEY,
          channel_id TEXT NOT NULL,
          channel_username TEXT,
          status TEXT NOT NULL CHECK(status IN ('active', 'paused', 'error')),
          include_comments INTEGER NOT NULL CHECK(include_comments IN (0, 1)),
          history_from TEXT,
          history_to TEXT,
          poll_interval_seconds INTEGER,
          batch_size INTEGER,
          last_post_id TEXT,
          backfill_completed_at TEXT,
          last_attempt_at TEXT,
          last_success_at TEXT,
          fail_count INTEGER NOT NULL DEFAULT 0,
          last_error TEXT,
          rate_limit_until TEXT,
          comments_unavailable INTEGER NOT NULL DEFAULT 0 CHECK(comments_unavailable IN (0, 1)),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
    """)
    
    # Create indexes
    op.execute("""
        CREATE INDEX IF NOT EXISTS sources_status_idx ON sources(status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS sources_channel_id_idx ON sources(channel_id)
    """)
    
    # Create comment_cursors table (TR-7, TR-15)
    op.execute("""
        CREATE TABLE IF NOT EXISTS comment_cursors (
          source_id TEXT NOT NULL,
          thread_id TEXT NOT NULL,
          last_comment_id TEXT,
          updated_at TEXT NOT NULL,
          PRIMARY KEY (source_id, thread_id)
        )
    """)
    
    # Create index
    op.execute("""
        CREATE INDEX IF NOT EXISTS comment_cursors_thread_idx ON comment_cursors(thread_id)
    """)
    
    # Create source_attempts table (TR-11, TR-15)
    op.execute("""
        CREATE TABLE IF NOT EXISTS source_attempts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_id TEXT NOT NULL,
          attempt_at TEXT NOT NULL,
          success INTEGER NOT NULL CHECK(success IN (0, 1)),
          error_class TEXT,
          error_message TEXT,
          details_json TEXT
        )
    """)
    
    # Create index
    op.execute("""
        CREATE INDEX IF NOT EXISTS source_attempts_source_time_idx
        ON source_attempts(source_id, attempt_at)
    """)


def downgrade() -> None:
    """Drop ingestion_state schema."""
    op.execute("DROP TABLE IF EXISTS source_attempts")
    op.execute("DROP TABLE IF EXISTS comment_cursors")
    op.execute("DROP TABLE IF EXISTS sources")

