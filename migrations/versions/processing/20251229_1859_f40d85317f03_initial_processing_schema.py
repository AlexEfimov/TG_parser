"""initial processing schema (Universal: SQLite + PostgreSQL)

Revision ID: f40d85317f03
Revises: 
Create Date: 2025-12-29 18:59:08.484631

Session 24: Rewritten using SQLAlchemy ORM for universal compatibility.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f40d85317f03'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create initial processing_storage schema (universal)."""
    
    # ========== Core Processing Tables ==========
    
    # Create processed_documents table (TR-22, TR-43)
    op.create_table(
        'processed_documents',
        sa.Column('source_ref', sa.String(), nullable=False),
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('source_message_id', sa.String(), nullable=False),
        sa.Column('channel_id', sa.String(), nullable=False),
        sa.Column('processed_at', sa.String(), nullable=False),
        sa.Column('text_clean', sa.Text(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('topics_json', sa.Text(), nullable=True),
        sa.Column('entities_json', sa.Text(), nullable=True),
        sa.Column('language', sa.String(), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('source_ref')
    )
    
    op.create_index('processed_documents_channel_idx', 'processed_documents', ['channel_id'])
    op.create_index('processed_documents_processed_at_idx', 'processed_documents', ['processed_at'])
    
    # Create processing_failures table (TR-47)
    op.create_table(
        'processing_failures',
        sa.Column('source_ref', sa.String(), nullable=False),
        sa.Column('channel_id', sa.String(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('last_attempt_at', sa.String(), nullable=False),
        sa.Column('error_class', sa.String(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_details_json', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('source_ref')
    )
    
    op.create_index('processing_failures_channel_idx', 'processing_failures', ['channel_id'])
    op.create_index('processing_failures_last_attempt_idx', 'processing_failures', ['last_attempt_at'])
    
    # ========== Topicization Tables ==========
    
    # Create topic_cards table (TR-43)
    op.create_table(
        'topic_cards',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('scope_in_json', sa.Text(), nullable=False),
        sa.Column('scope_out_json', sa.Text(), nullable=False),
        sa.Column('type', sa.String(), nullable=False),
        sa.Column('anchors_json', sa.Text(), nullable=False),
        sa.Column('sources_json', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.Column('tags_json', sa.Text(), nullable=True),
        sa.Column('related_topics_json', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("type IN ('singleton', 'cluster')", name='topic_cards_type_check')
    )
    
    op.create_index('topic_cards_updated_at_idx', 'topic_cards', ['updated_at'])
    
    # Create topic_bundles table (TR-43)
    # Note: Partial indexes with WHERE clause are database-specific
    # For universal approach, we create regular indexes
    op.create_table(
        'topic_bundles',
        sa.Column('topic_id', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.Column('time_from', sa.String(), nullable=True),
        sa.Column('time_to', sa.String(), nullable=True),
        sa.Column('items_json', sa.Text(), nullable=False),
        sa.Column('channels_json', sa.Text(), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True)
    )
    
    # Create regular indexes (works in both SQLite and PostgreSQL)
    op.create_index('topic_bundles_topic_idx', 'topic_bundles', ['topic_id'])
    op.create_index('topic_bundles_snapshot_idx', 'topic_bundles', ['topic_id', 'time_from', 'time_to'])
    
    # ========== API Tables (Phase 2F) ==========
    
    # Create api_jobs table
    op.create_table(
        'api_jobs',
        sa.Column('job_id', sa.String(), nullable=False),
        sa.Column('job_type', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('channel_id', sa.String(), nullable=True),
        sa.Column('client', sa.String(), nullable=True),
        sa.Column('started_at', sa.String(), nullable=True),
        sa.Column('completed_at', sa.String(), nullable=True),
        sa.Column('progress_json', sa.Text(), nullable=True),
        sa.Column('result_json', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('file_path', sa.String(), nullable=True),
        sa.Column('download_url', sa.String(), nullable=True),
        sa.Column('export_format', sa.String(), nullable=True),
        sa.Column('webhook_url', sa.String(), nullable=True),
        sa.Column('webhook_secret', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('job_id'),
        sa.CheckConstraint("job_type IN ('processing', 'export')", name='api_jobs_type_check'),
        sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name='api_jobs_status_check')
    )
    
    op.create_index('api_jobs_status_idx', 'api_jobs', ['status'])
    op.create_index('api_jobs_created_at_idx', 'api_jobs', ['created_at'])
    op.create_index('api_jobs_job_type_idx', 'api_jobs', ['job_type'])
    
    # ========== Agent State Persistence (Phase 3B) ==========
    
    # Create agent_states table
    op.create_table(
        'agent_states',
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('agent_type', sa.String(), nullable=False),
        sa.Column('version', sa.String(), nullable=False, server_default='1.0.0'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('capabilities_json', sa.Text(), nullable=False),
        sa.Column('model', sa.String(), nullable=True),
        sa.Column('provider', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('total_tasks_processed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_errors', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('avg_processing_time_ms', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('last_used_at', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('name')
    )
    
    op.create_index('agent_states_type_idx', 'agent_states', ['agent_type'])
    op.create_index('agent_states_active_idx', 'agent_states', ['is_active'])
    
    # Create task_history table
    op.create_table(
        'task_history',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('agent_name', sa.String(), nullable=False),
        sa.Column('task_type', sa.String(), nullable=False),
        sa.Column('source_ref', sa.String(), nullable=True),
        sa.Column('channel_id', sa.String(), nullable=True),
        sa.Column('input_json', sa.Text(), nullable=False),
        sa.Column('output_json', sa.Text(), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('processing_time_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('expires_at', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['agent_name'], ['agent_states.name'])
    )
    
    op.create_index('task_history_agent_idx', 'task_history', ['agent_name'])
    op.create_index('task_history_channel_idx', 'task_history', ['channel_id'])
    op.create_index('task_history_created_idx', 'task_history', ['created_at'])
    op.create_index('task_history_expires_idx', 'task_history', ['expires_at'])
    op.create_index('task_history_source_ref_idx', 'task_history', ['source_ref'])
    
    # Create agent_stats table
    op.create_table(
        'agent_stats',
        sa.Column('agent_name', sa.String(), nullable=False),
        sa.Column('date', sa.String(), nullable=False),
        sa.Column('task_type', sa.String(), nullable=False),
        sa.Column('total_tasks', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('successful_tasks', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_tasks', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_processing_time_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('min_processing_time_ms', sa.Integer(), nullable=True),
        sa.Column('max_processing_time_ms', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('agent_name', 'date', 'task_type')
    )
    
    op.create_index('agent_stats_agent_idx', 'agent_stats', ['agent_name'])
    op.create_index('agent_stats_date_idx', 'agent_stats', ['date'])
    
    # Create handoff_history table
    op.create_table(
        'handoff_history',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('source_agent', sa.String(), nullable=False),
        sa.Column('target_agent', sa.String(), nullable=False),
        sa.Column('task_type', sa.String(), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=True),
        sa.Column('context_json', sa.Text(), nullable=True),
        sa.Column('result_json', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('processing_time_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('accepted_at', sa.String(), nullable=True),
        sa.Column('completed_at', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'in_progress', 'completed', 'failed', 'rejected')",
            name='handoff_history_status_check'
        )
    )
    
    op.create_index('handoff_history_source_idx', 'handoff_history', ['source_agent'])
    op.create_index('handoff_history_target_idx', 'handoff_history', ['target_agent'])
    op.create_index('handoff_history_status_idx', 'handoff_history', ['status'])
    op.create_index('handoff_history_created_idx', 'handoff_history', ['created_at'])


def downgrade() -> None:
    """Drop processing_storage schema."""
    # Agent tables
    op.drop_table('handoff_history')
    op.drop_table('agent_stats')
    op.drop_table('task_history')
    op.drop_table('agent_states')
    
    # API tables
    op.drop_table('api_jobs')
    
    # Topicization tables
    op.drop_table('topic_bundles')
    op.drop_table('topic_cards')
    
    # Processing tables
    op.drop_table('processing_failures')
    op.drop_table('processed_documents')

