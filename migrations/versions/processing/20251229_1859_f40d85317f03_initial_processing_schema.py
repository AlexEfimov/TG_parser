"""initial_processing_schema

Revision ID: f40d85317f03
Revises: 5c658f04eff0
Create Date: 2025-12-29 18:59:08.484631

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f40d85317f03'
down_revision: Union[str, None] = None  # Independent database
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create initial processing_storage schema."""
    
    # ========== Core Processing Tables ==========
    
    # Create processed_documents table (TR-22, TR-43)
    op.execute("""
        CREATE TABLE IF NOT EXISTS processed_documents (
          source_ref TEXT PRIMARY KEY,
          id TEXT NOT NULL,
          source_message_id TEXT NOT NULL,
          channel_id TEXT NOT NULL,
          processed_at TEXT NOT NULL,
          text_clean TEXT NOT NULL,
          summary TEXT,
          topics_json TEXT,
          entities_json TEXT,
          language TEXT,
          metadata_json TEXT
        )
    """)
    
    op.execute("CREATE INDEX IF NOT EXISTS processed_documents_channel_idx ON processed_documents(channel_id)")
    op.execute("CREATE INDEX IF NOT EXISTS processed_documents_processed_at_idx ON processed_documents(processed_at)")
    
    # Create processing_failures table (TR-47)
    op.execute("""
        CREATE TABLE IF NOT EXISTS processing_failures (
          source_ref TEXT PRIMARY KEY,
          channel_id TEXT NOT NULL,
          attempts INTEGER NOT NULL,
          last_attempt_at TEXT NOT NULL,
          error_class TEXT,
          error_message TEXT,
          error_details_json TEXT
        )
    """)
    
    op.execute("CREATE INDEX IF NOT EXISTS processing_failures_channel_idx ON processing_failures(channel_id)")
    op.execute("CREATE INDEX IF NOT EXISTS processing_failures_last_attempt_idx ON processing_failures(last_attempt_at)")
    
    # ========== Topicization Tables ==========
    
    # Create topic_cards table (TR-43)
    op.execute("""
        CREATE TABLE IF NOT EXISTS topic_cards (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          summary TEXT NOT NULL,
          scope_in_json TEXT NOT NULL,
          scope_out_json TEXT NOT NULL,
          type TEXT NOT NULL CHECK(type IN ('singleton', 'cluster')),
          anchors_json TEXT NOT NULL,
          sources_json TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          tags_json TEXT,
          related_topics_json TEXT,
          status TEXT,
          metadata_json TEXT
        )
    """)
    
    op.execute("CREATE INDEX IF NOT EXISTS topic_cards_updated_at_idx ON topic_cards(updated_at)")
    
    # Create topic_bundles table (TR-43)
    op.execute("""
        CREATE TABLE IF NOT EXISTS topic_bundles (
          topic_id TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          time_from TEXT,
          time_to TEXT,
          items_json TEXT NOT NULL,
          channels_json TEXT,
          metadata_json TEXT
        )
    """)
    
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS topic_bundles_current_unique_idx
        ON topic_bundles(topic_id)
        WHERE time_from IS NULL AND time_to IS NULL
    """)
    
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS topic_bundles_snapshot_unique_idx
        ON topic_bundles(topic_id, time_from, time_to)
        WHERE time_from IS NOT NULL AND time_to IS NOT NULL
    """)
    
    # ========== API Tables (Phase 2F) ==========
    
    # Create api_jobs table
    op.execute("""
        CREATE TABLE IF NOT EXISTS api_jobs (
          job_id TEXT PRIMARY KEY,
          job_type TEXT NOT NULL CHECK(job_type IN ('processing', 'export')),
          status TEXT NOT NULL CHECK(status IN ('pending', 'running', 'completed', 'failed')),
          created_at TEXT NOT NULL,
          channel_id TEXT,
          client TEXT,
          started_at TEXT,
          completed_at TEXT,
          progress_json TEXT,
          result_json TEXT,
          error TEXT,
          file_path TEXT,
          download_url TEXT,
          export_format TEXT,
          webhook_url TEXT,
          webhook_secret TEXT
        )
    """)
    
    op.execute("CREATE INDEX IF NOT EXISTS api_jobs_status_idx ON api_jobs(status)")
    op.execute("CREATE INDEX IF NOT EXISTS api_jobs_created_at_idx ON api_jobs(created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS api_jobs_job_type_idx ON api_jobs(job_type)")
    
    # ========== Agent State Persistence (Phase 3B) ==========
    
    # Create agent_states table
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_states (
          name TEXT PRIMARY KEY,
          agent_type TEXT NOT NULL,
          version TEXT NOT NULL DEFAULT '1.0.0',
          description TEXT,
          capabilities_json TEXT NOT NULL,
          model TEXT,
          provider TEXT,
          is_active INTEGER NOT NULL DEFAULT 1,
          metadata_json TEXT,
          
          total_tasks_processed INTEGER NOT NULL DEFAULT 0,
          total_errors INTEGER NOT NULL DEFAULT 0,
          avg_processing_time_ms REAL NOT NULL DEFAULT 0.0,
          last_used_at TEXT,
          
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
    """)
    
    op.execute("CREATE INDEX IF NOT EXISTS agent_states_type_idx ON agent_states(agent_type)")
    op.execute("CREATE INDEX IF NOT EXISTS agent_states_active_idx ON agent_states(is_active)")
    
    # Create task_history table
    op.execute("""
        CREATE TABLE IF NOT EXISTS task_history (
          id TEXT PRIMARY KEY,
          agent_name TEXT NOT NULL,
          task_type TEXT NOT NULL,
          
          source_ref TEXT,
          channel_id TEXT,
          
          input_json TEXT NOT NULL,
          output_json TEXT,
          
          success INTEGER NOT NULL DEFAULT 1,
          error TEXT,
          processing_time_ms INTEGER,
          
          created_at TEXT NOT NULL,
          expires_at TEXT,
          
          FOREIGN KEY (agent_name) REFERENCES agent_states(name)
        )
    """)
    
    op.execute("CREATE INDEX IF NOT EXISTS task_history_agent_idx ON task_history(agent_name)")
    op.execute("CREATE INDEX IF NOT EXISTS task_history_channel_idx ON task_history(channel_id)")
    op.execute("CREATE INDEX IF NOT EXISTS task_history_created_idx ON task_history(created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS task_history_expires_idx ON task_history(expires_at)")
    op.execute("CREATE INDEX IF NOT EXISTS task_history_source_ref_idx ON task_history(source_ref)")
    
    # Create agent_stats table
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_stats (
          agent_name TEXT NOT NULL,
          date TEXT NOT NULL,
          task_type TEXT NOT NULL,
          
          total_tasks INTEGER NOT NULL DEFAULT 0,
          successful_tasks INTEGER NOT NULL DEFAULT 0,
          failed_tasks INTEGER NOT NULL DEFAULT 0,
          total_processing_time_ms INTEGER NOT NULL DEFAULT 0,
          min_processing_time_ms INTEGER,
          max_processing_time_ms INTEGER,
          
          PRIMARY KEY (agent_name, date, task_type)
        )
    """)
    
    op.execute("CREATE INDEX IF NOT EXISTS agent_stats_agent_idx ON agent_stats(agent_name)")
    op.execute("CREATE INDEX IF NOT EXISTS agent_stats_date_idx ON agent_stats(date DESC)")
    
    # Create handoff_history table
    op.execute("""
        CREATE TABLE IF NOT EXISTS handoff_history (
          id TEXT PRIMARY KEY,
          source_agent TEXT NOT NULL,
          target_agent TEXT NOT NULL,
          task_type TEXT NOT NULL,
          priority INTEGER NOT NULL DEFAULT 5,
          
          status TEXT NOT NULL CHECK(status IN ('pending', 'accepted', 'in_progress', 'completed', 'failed', 'rejected')),
          
          payload_json TEXT,
          context_json TEXT,
          result_json TEXT,
          error TEXT,
          
          processing_time_ms INTEGER,
          created_at TEXT NOT NULL,
          accepted_at TEXT,
          completed_at TEXT
        )
    """)
    
    op.execute("CREATE INDEX IF NOT EXISTS handoff_history_source_idx ON handoff_history(source_agent)")
    op.execute("CREATE INDEX IF NOT EXISTS handoff_history_target_idx ON handoff_history(target_agent)")
    op.execute("CREATE INDEX IF NOT EXISTS handoff_history_status_idx ON handoff_history(status)")
    op.execute("CREATE INDEX IF NOT EXISTS handoff_history_created_idx ON handoff_history(created_at DESC)")


def downgrade() -> None:
    """Drop processing_storage schema."""
    # Agent tables
    op.execute("DROP TABLE IF EXISTS handoff_history")
    op.execute("DROP TABLE IF EXISTS agent_stats")
    op.execute("DROP TABLE IF EXISTS task_history")
    op.execute("DROP TABLE IF EXISTS agent_states")
    
    # API tables
    op.execute("DROP TABLE IF EXISTS api_jobs")
    
    # Topicization tables
    op.execute("DROP TABLE IF EXISTS topic_bundles")
    op.execute("DROP TABLE IF EXISTS topic_cards")
    
    # Processing tables
    op.execute("DROP TABLE IF EXISTS processing_failures")
    op.execute("DROP TABLE IF EXISTS processed_documents")

