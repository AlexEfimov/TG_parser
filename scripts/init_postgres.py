#!/usr/bin/env python3
"""
Initialize PostgreSQL database schema for TG_parser.

Session 24: Production Ready
This script creates all required tables directly, bypassing Alembic.
Use this for fresh PostgreSQL deployments.

Usage:
    python scripts/init_postgres.py
    
    # With custom connection:
    DB_HOST=localhost DB_PORT=5432 DB_NAME=tg_parser \
    DB_USER=tg_parser_user DB_PASSWORD=secret \
    python scripts/init_postgres.py

    # Dry run (show SQL without executing):
    python scripts/init_postgres.py --dry-run
"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# SQL schema definitions (PostgreSQL compatible)
SCHEMA_SQL = """
-- ============================================================
-- INGESTION TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS sources (
    source_id VARCHAR NOT NULL PRIMARY KEY,
    channel_id VARCHAR NOT NULL,
    channel_username VARCHAR,
    status VARCHAR NOT NULL CHECK (status IN ('active', 'paused', 'error')),
    include_comments BOOLEAN NOT NULL,
    history_from VARCHAR,
    history_to VARCHAR,
    poll_interval_seconds INTEGER,
    batch_size INTEGER,
    last_post_id VARCHAR,
    backfill_completed_at VARCHAR,
    last_attempt_at VARCHAR,
    last_success_at VARCHAR,
    fail_count INTEGER NOT NULL DEFAULT 0,
    last_error VARCHAR,
    rate_limit_until VARCHAR,
    comments_unavailable BOOLEAN NOT NULL DEFAULT FALSE,
    created_at VARCHAR NOT NULL,
    updated_at VARCHAR NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(status);
CREATE INDEX IF NOT EXISTS idx_sources_channel_id ON sources(channel_id);

CREATE TABLE IF NOT EXISTS comment_cursors (
    source_id VARCHAR NOT NULL,
    thread_id VARCHAR NOT NULL,
    last_comment_id VARCHAR,
    updated_at VARCHAR NOT NULL,
    PRIMARY KEY (source_id, thread_id)
);

CREATE INDEX IF NOT EXISTS idx_comment_cursors_thread ON comment_cursors(thread_id);

CREATE TABLE IF NOT EXISTS source_attempts (
    id SERIAL PRIMARY KEY,
    source_id VARCHAR NOT NULL,
    attempt_at VARCHAR NOT NULL,
    success BOOLEAN NOT NULL,
    error_class VARCHAR,
    error_message VARCHAR,
    details_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_source_attempts_source_time ON source_attempts(source_id, attempt_at);

-- ============================================================
-- RAW STORAGE TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS raw_messages (
    source_ref VARCHAR NOT NULL PRIMARY KEY,
    id VARCHAR NOT NULL,
    message_type VARCHAR NOT NULL CHECK (message_type IN ('post', 'comment')),
    channel_id VARCHAR NOT NULL,
    date VARCHAR NOT NULL,
    text TEXT NOT NULL,
    thread_id VARCHAR,
    parent_message_id VARCHAR,
    language VARCHAR,
    raw_payload_json TEXT,
    raw_payload_truncated BOOLEAN NOT NULL DEFAULT FALSE,
    raw_payload_original_size_bytes INTEGER,
    inserted_at VARCHAR NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_raw_messages_channel_date ON raw_messages(channel_id, date);
CREATE INDEX IF NOT EXISTS idx_raw_messages_thread ON raw_messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_raw_messages_type ON raw_messages(message_type);

CREATE TABLE IF NOT EXISTS raw_conflicts (
    id SERIAL PRIMARY KEY,
    source_ref VARCHAR NOT NULL,
    observed_at VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    new_payload_json TEXT,
    new_text VARCHAR,
    new_date VARCHAR
);

CREATE INDEX IF NOT EXISTS idx_raw_conflicts_source_time ON raw_conflicts(source_ref, observed_at);

-- ============================================================
-- PROCESSING TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS processed_documents (
    source_ref VARCHAR NOT NULL PRIMARY KEY,
    id VARCHAR NOT NULL,
    source_message_id VARCHAR NOT NULL,
    channel_id VARCHAR NOT NULL,
    processed_at VARCHAR NOT NULL,
    text_clean TEXT NOT NULL,
    summary TEXT,
    topics_json TEXT,
    entities_json TEXT,
    language VARCHAR,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_processed_documents_channel ON processed_documents(channel_id);
CREATE INDEX IF NOT EXISTS idx_processed_documents_processed_at ON processed_documents(processed_at);

CREATE TABLE IF NOT EXISTS processing_failures (
    source_ref VARCHAR NOT NULL PRIMARY KEY,
    channel_id VARCHAR NOT NULL,
    attempts INTEGER NOT NULL,
    last_attempt_at VARCHAR NOT NULL,
    error_class VARCHAR,
    error_message TEXT,
    error_details_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_processing_failures_channel ON processing_failures(channel_id);

-- ============================================================
-- TOPICIZATION TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS topic_cards (
    id VARCHAR NOT NULL PRIMARY KEY,
    title VARCHAR NOT NULL,
    summary TEXT NOT NULL,
    scope_in_json TEXT NOT NULL,
    scope_out_json TEXT NOT NULL,
    type VARCHAR NOT NULL CHECK (type IN ('singleton', 'cluster')),
    anchors_json TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    updated_at VARCHAR NOT NULL,
    tags_json TEXT,
    related_topics_json TEXT,
    status VARCHAR,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_topic_cards_updated_at ON topic_cards(updated_at);

CREATE TABLE IF NOT EXISTS topic_bundles (
    topic_id VARCHAR NOT NULL,
    updated_at VARCHAR NOT NULL,
    time_from VARCHAR,
    time_to VARCHAR,
    items_json TEXT NOT NULL,
    channels_json TEXT,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_topic_bundles_topic ON topic_bundles(topic_id);

-- ============================================================
-- API TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS api_jobs (
    job_id VARCHAR NOT NULL PRIMARY KEY,
    job_type VARCHAR NOT NULL CHECK (job_type IN ('processing', 'export')),
    status VARCHAR NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    created_at VARCHAR NOT NULL,
    channel_id VARCHAR,
    client VARCHAR,
    started_at VARCHAR,
    completed_at VARCHAR,
    progress_json TEXT,
    result_json TEXT,
    error TEXT,
    file_path VARCHAR,
    download_url VARCHAR,
    export_format VARCHAR,
    webhook_url VARCHAR,
    webhook_secret VARCHAR
);

CREATE INDEX IF NOT EXISTS idx_api_jobs_status ON api_jobs(status);
CREATE INDEX IF NOT EXISTS idx_api_jobs_created_at ON api_jobs(created_at);

-- ============================================================
-- AGENT TABLES (Phase 3B)
-- ============================================================

CREATE TABLE IF NOT EXISTS agent_states (
    name VARCHAR NOT NULL PRIMARY KEY,
    agent_type VARCHAR NOT NULL,
    version VARCHAR NOT NULL DEFAULT '1.0.0',
    description TEXT,
    capabilities_json TEXT NOT NULL,
    model VARCHAR,
    provider VARCHAR,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata_json TEXT,
    total_tasks_processed INTEGER NOT NULL DEFAULT 0,
    total_errors INTEGER NOT NULL DEFAULT 0,
    avg_processing_time_ms REAL NOT NULL DEFAULT 0.0,
    last_used_at VARCHAR,
    created_at VARCHAR NOT NULL,
    updated_at VARCHAR NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_states_type ON agent_states(agent_type);
CREATE INDEX IF NOT EXISTS idx_agent_states_active ON agent_states(is_active);

CREATE TABLE IF NOT EXISTS task_history (
    id VARCHAR NOT NULL PRIMARY KEY,
    agent_name VARCHAR NOT NULL,
    task_type VARCHAR NOT NULL,
    source_ref VARCHAR,
    channel_id VARCHAR,
    input_json TEXT NOT NULL,
    output_json TEXT,
    success BOOLEAN NOT NULL DEFAULT TRUE,
    error TEXT,
    processing_time_ms INTEGER,
    created_at VARCHAR NOT NULL,
    expires_at VARCHAR
);

CREATE INDEX IF NOT EXISTS idx_task_history_agent ON task_history(agent_name);
CREATE INDEX IF NOT EXISTS idx_task_history_channel ON task_history(channel_id);
CREATE INDEX IF NOT EXISTS idx_task_history_created ON task_history(created_at);

CREATE TABLE IF NOT EXISTS agent_stats (
    agent_name VARCHAR NOT NULL,
    date VARCHAR NOT NULL,
    task_type VARCHAR NOT NULL,
    total_tasks INTEGER NOT NULL DEFAULT 0,
    successful_tasks INTEGER NOT NULL DEFAULT 0,
    failed_tasks INTEGER NOT NULL DEFAULT 0,
    total_processing_time_ms INTEGER NOT NULL DEFAULT 0,
    min_processing_time_ms INTEGER,
    max_processing_time_ms INTEGER,
    PRIMARY KEY (agent_name, date, task_type)
);

CREATE INDEX IF NOT EXISTS idx_agent_stats_agent ON agent_stats(agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_stats_date ON agent_stats(date);

CREATE TABLE IF NOT EXISTS handoff_history (
    id VARCHAR NOT NULL PRIMARY KEY,
    source_agent VARCHAR NOT NULL,
    target_agent VARCHAR NOT NULL,
    task_type VARCHAR NOT NULL,
    priority INTEGER NOT NULL DEFAULT 5,
    status VARCHAR NOT NULL CHECK (status IN ('pending', 'accepted', 'in_progress', 'completed', 'failed', 'rejected')),
    payload_json TEXT,
    context_json TEXT,
    result_json TEXT,
    error TEXT,
    processing_time_ms INTEGER,
    created_at VARCHAR NOT NULL,
    accepted_at VARCHAR,
    completed_at VARCHAR
);

CREATE INDEX IF NOT EXISTS idx_handoff_history_source ON handoff_history(source_agent);
CREATE INDEX IF NOT EXISTS idx_handoff_history_target ON handoff_history(target_agent);
CREATE INDEX IF NOT EXISTS idx_handoff_history_status ON handoff_history(status);
"""


def get_connection_params() -> dict:
    """Get PostgreSQL connection parameters from environment."""
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "database": os.getenv("DB_NAME", "tg_parser"),
        "user": os.getenv("DB_USER", "tg_parser_user"),
        "password": os.getenv("DB_PASSWORD", ""),
    }


async def init_postgres(dry_run: bool = False) -> None:
    """Initialize PostgreSQL database schema."""
    import asyncpg
    
    params = get_connection_params()
    
    print("🔄 PostgreSQL Schema Initialization")
    print("=" * 50)
    print(f"   Host: {params['host']}:{params['port']}")
    print(f"   Database: {params['database']}")
    print(f"   User: {params['user']}")
    print(f"   Dry Run: {dry_run}")
    print()
    
    if dry_run:
        print("📋 SQL to be executed:")
        print("-" * 50)
        print(SCHEMA_SQL)
        return
    
    # Connect to PostgreSQL
    print("📡 Connecting to PostgreSQL...")
    try:
        conn = await asyncpg.connect(**params)
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        print()
        print("💡 Make sure PostgreSQL is running and credentials are correct.")
        print("   You can set connection via environment variables:")
        print("   DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD")
        sys.exit(1)
    
    print("✅ Connected!")
    print()
    
    # Check current state
    tables_before = await conn.fetch("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
    """)
    print(f"📊 Current tables: {len(tables_before)}")
    
    # Execute schema
    print("🔧 Creating tables...")
    try:
        await conn.execute(SCHEMA_SQL)
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        await conn.close()
        sys.exit(1)
    
    # Check final state
    tables_after = await conn.fetch("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)
    
    new_tables = len(tables_after) - len(tables_before)
    print(f"✅ Created {new_tables} new tables")
    print()
    print(f"📊 Total tables: {len(tables_after)}")
    for t in tables_after:
        print(f"   - {t['table_name']}")
    
    await conn.close()
    print()
    print("🎉 PostgreSQL initialization complete!")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Initialize PostgreSQL database schema for TG_parser"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show SQL without executing"
    )
    args = parser.parse_args()
    
    try:
        asyncio.run(init_postgres(dry_run=args.dry_run))
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted by user")
        sys.exit(130)


if __name__ == "__main__":
    main()

