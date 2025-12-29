"""initial_raw_schema

Revision ID: 5c658f04eff0
Revises: 89f91e768b9b
Create Date: 2025-12-29 18:59:08.283906

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
    """Create initial raw_storage schema."""
    
    # Create raw_messages table (TR-18, TR-20)
    op.execute("""
        CREATE TABLE IF NOT EXISTS raw_messages (
          source_ref TEXT PRIMARY KEY,
          id TEXT NOT NULL,
          message_type TEXT NOT NULL CHECK(message_type IN ('post', 'comment')),
          channel_id TEXT NOT NULL,
          date TEXT NOT NULL,
          text TEXT NOT NULL,
          thread_id TEXT,
          parent_message_id TEXT,
          language TEXT,
          raw_payload_json TEXT,
          raw_payload_truncated INTEGER NOT NULL DEFAULT 0 CHECK(raw_payload_truncated IN (0, 1)),
          raw_payload_original_size_bytes INTEGER,
          inserted_at TEXT NOT NULL
        )
    """)
    
    op.execute("CREATE INDEX IF NOT EXISTS raw_messages_channel_date_idx ON raw_messages(channel_id, date)")
    op.execute("CREATE INDEX IF NOT EXISTS raw_messages_thread_idx ON raw_messages(thread_id)")
    op.execute("CREATE INDEX IF NOT EXISTS raw_messages_type_idx ON raw_messages(message_type)")
    
    # Create raw_conflicts table (TR-8)
    op.execute("""
        CREATE TABLE IF NOT EXISTS raw_conflicts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_ref TEXT NOT NULL,
          observed_at TEXT NOT NULL,
          reason TEXT NOT NULL,
          new_payload_json TEXT,
          new_text TEXT,
          new_date TEXT
        )
    """)
    
    op.execute("""
        CREATE INDEX IF NOT EXISTS raw_conflicts_source_time_idx
        ON raw_conflicts(source_ref, observed_at)
    """)


def downgrade() -> None:
    """Drop raw_storage schema."""
    op.execute("DROP TABLE IF EXISTS raw_conflicts")
    op.execute("DROP TABLE IF EXISTS raw_messages")

