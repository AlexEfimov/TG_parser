"""
DDL для processing storage (PostgreSQL).

Реализует схему из docs/architecture.md.
"""

import structlog

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

logger = structlog.get_logger(__name__)

PROCESSING_STORAGE_DDL = """
-- Таблица processed documents (TR-22, TR-43)
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
);

CREATE INDEX IF NOT EXISTS processed_documents_channel_idx ON processed_documents(channel_id);
CREATE INDEX IF NOT EXISTS processed_documents_processed_at_idx ON processed_documents(processed_at);

-- Журнал неудачной обработки per-message (TR-47)
CREATE TABLE IF NOT EXISTS processing_failures (
  source_ref TEXT PRIMARY KEY,
  channel_id TEXT NOT NULL,
  attempts INTEGER NOT NULL,
  last_attempt_at TEXT NOT NULL,
  error_class TEXT,
  error_message TEXT,
  error_details_json TEXT
);

CREATE INDEX IF NOT EXISTS processing_failures_channel_idx ON processing_failures(channel_id);
CREATE INDEX IF NOT EXISTS processing_failures_last_attempt_idx ON processing_failures(last_attempt_at);

-- Таблица topic cards (TR-43)
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
);

CREATE INDEX IF NOT EXISTS topic_cards_updated_at_idx ON topic_cards(updated_at);

-- Таблица topic bundles (TR-43)
CREATE TABLE IF NOT EXISTS topic_bundles (
  topic_id TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  time_from TEXT,
  time_to TEXT,
  items_json TEXT NOT NULL,
  channels_json TEXT,
  metadata_json TEXT
);

-- MVP: одна актуальная подборка на тему (без time_range)
-- Partial unique index для NULL values
CREATE UNIQUE INDEX IF NOT EXISTS topic_bundles_current_unique_idx
ON topic_bundles(topic_id)
WHERE time_from IS NULL AND time_to IS NULL;

-- Для снапшотов с time_range (будущее)
CREATE UNIQUE INDEX IF NOT EXISTS topic_bundles_snapshot_unique_idx
ON topic_bundles(topic_id, time_from, time_to)
WHERE time_from IS NOT NULL AND time_to IS NOT NULL;

-- API Jobs (Phase 2F - Persistent Job Storage)
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
);

CREATE INDEX IF NOT EXISTS api_jobs_status_idx ON api_jobs(status);
CREATE INDEX IF NOT EXISTS api_jobs_created_at_idx ON api_jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS api_jobs_job_type_idx ON api_jobs(job_type);

-- ============================================================================
-- Agent State Persistence (Phase 3B)
-- ============================================================================

-- Agent states (metadata, statistics, lifecycle)
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
  
  -- Statistics (restored on startup)
  total_tasks_processed INTEGER NOT NULL DEFAULT 0,
  total_errors INTEGER NOT NULL DEFAULT 0,
  avg_processing_time_ms REAL NOT NULL DEFAULT 0.0,
  last_used_at TEXT,
  
  -- Timestamps
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS agent_states_type_idx ON agent_states(agent_type);
CREATE INDEX IF NOT EXISTS agent_states_active_idx ON agent_states(is_active);

-- Task execution history (full input/output with TTL)
CREATE TABLE IF NOT EXISTS task_history (
  id TEXT PRIMARY KEY,
  agent_name TEXT NOT NULL,
  task_type TEXT NOT NULL,
  
  -- Context
  source_ref TEXT,
  channel_id TEXT,
  
  -- Full data (JSON)
  input_json TEXT NOT NULL,
  output_json TEXT,
  
  -- Result
  success INTEGER NOT NULL DEFAULT 1,
  error TEXT,
  processing_time_ms INTEGER,
  
  -- Timestamps and retention
  created_at TEXT NOT NULL,
  expires_at TEXT,
  
  FOREIGN KEY (agent_name) REFERENCES agent_states(name)
);

CREATE INDEX IF NOT EXISTS task_history_agent_idx ON task_history(agent_name);
CREATE INDEX IF NOT EXISTS task_history_channel_idx ON task_history(channel_id);
CREATE INDEX IF NOT EXISTS task_history_created_idx ON task_history(created_at DESC);
CREATE INDEX IF NOT EXISTS task_history_expires_idx ON task_history(expires_at);
CREATE INDEX IF NOT EXISTS task_history_source_ref_idx ON task_history(source_ref);

-- Aggregated agent statistics by day (persists after cleanup)
CREATE TABLE IF NOT EXISTS agent_stats (
  agent_name TEXT NOT NULL,
  date TEXT NOT NULL,
  task_type TEXT NOT NULL,
  
  -- Daily aggregates
  total_tasks INTEGER NOT NULL DEFAULT 0,
  successful_tasks INTEGER NOT NULL DEFAULT 0,
  failed_tasks INTEGER NOT NULL DEFAULT 0,
  total_processing_time_ms INTEGER NOT NULL DEFAULT 0,
  min_processing_time_ms INTEGER,
  max_processing_time_ms INTEGER,
  
  PRIMARY KEY (agent_name, date, task_type)
);

CREATE INDEX IF NOT EXISTS agent_stats_agent_idx ON agent_stats(agent_name);
CREATE INDEX IF NOT EXISTS agent_stats_date_idx ON agent_stats(date DESC);

-- Handoff history between agents
CREATE TABLE IF NOT EXISTS handoff_history (
  id TEXT PRIMARY KEY,
  source_agent TEXT NOT NULL,
  target_agent TEXT NOT NULL,
  task_type TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 5,
  
  -- Status tracking
  status TEXT NOT NULL CHECK(status IN ('pending', 'accepted', 'in_progress', 'completed', 'failed', 'rejected')),
  
  -- Data (JSON)
  payload_json TEXT,
  context_json TEXT,
  result_json TEXT,
  error TEXT,
  
  -- Timing
  processing_time_ms INTEGER,
  created_at TEXT NOT NULL,
  accepted_at TEXT,
  completed_at TEXT
);

CREATE INDEX IF NOT EXISTS handoff_history_source_idx ON handoff_history(source_agent);
CREATE INDEX IF NOT EXISTS handoff_history_target_idx ON handoff_history(target_agent);
CREATE INDEX IF NOT EXISTS handoff_history_status_idx ON handoff_history(status);
CREATE INDEX IF NOT EXISTS handoff_history_created_idx ON handoff_history(created_at DESC);

-- Cross-channel topic links (Cross-dev 3)
CREATE TABLE IF NOT EXISTS topic_links (
  topic_id_a TEXT NOT NULL,
  topic_id_b TEXT NOT NULL,
  similarity_score REAL NOT NULL,
  shared_keywords_json TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (topic_id_a, topic_id_b)
);

CREATE INDEX IF NOT EXISTS topic_links_a_idx ON topic_links(topic_id_a);
CREATE INDEX IF NOT EXISTS topic_links_b_idx ON topic_links(topic_id_b);
CREATE INDEX IF NOT EXISTS topic_links_score_idx ON topic_links(similarity_score DESC);

"""

EMBEDDING_DDL = """
CREATE TABLE IF NOT EXISTS document_embeddings (
  source_ref TEXT PRIMARY KEY,
  embedding vector(1536),
  model TEXT NOT NULL,
  created_at TEXT NOT NULL,
  metadata_json TEXT,
  entry_type TEXT NOT NULL DEFAULT 'message',
  topic_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_de_entry_type ON document_embeddings(entry_type);
"""

EMBEDDING_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS document_embeddings_vector_idx
ON document_embeddings USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100)
"""


async def _ensure_pgvector(engine: AsyncEngine) -> bool:
    """Try to enable pgvector extension. Returns True if available."""
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        return True
    except (ProgrammingError, OperationalError):
        return False


async def _ensure_embedding_columns(engine: AsyncEngine) -> None:
    """Add entry_type/topic_id columns if missing (idempotent for existing DBs)."""
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'document_embeddings'"
            ))
            existing = {row[0] for row in result.fetchall()}

            if "entry_type" not in existing:
                await conn.execute(text(
                    "ALTER TABLE document_embeddings "
                    "ADD COLUMN entry_type TEXT NOT NULL DEFAULT 'message'"
                ))
            if "topic_id" not in existing:
                await conn.execute(text(
                    "ALTER TABLE document_embeddings ADD COLUMN topic_id TEXT"
                ))

            try:
                await conn.execute(text(
                    "ALTER TABLE document_embeddings "
                    "DROP CONSTRAINT IF EXISTS document_embeddings_source_ref_fkey"
                ))
            except Exception:
                pass

            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_de_entry_type "
                "ON document_embeddings(entry_type)"
            ))
    except (ProgrammingError, OperationalError):
        pass


async def init_processing_storage_schema(engine: AsyncEngine) -> None:
    """
    Создать таблицы для processing storage.

    Args:
        engine: AsyncEngine for processing storage database
    """
    async with engine.begin() as conn:
        for statement in PROCESSING_STORAGE_DDL.split(";"):
            statement = statement.strip()
            if statement:
                await conn.execute(text(statement))

    # pgvector DDL in a separate transaction — non-fatal if unavailable
    pgvector_ok = await _ensure_pgvector(engine)
    if pgvector_ok:
        try:
            async with engine.begin() as conn:
                for stmt in EMBEDDING_DDL.split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        await conn.execute(text(stmt))
        except (ProgrammingError, OperationalError) as e:
            logger.debug("pgvector embedding DDL skipped: %s", e)

        await _ensure_embedding_columns(engine)


async def init_embedding_index(engine: AsyncEngine) -> None:
    """Create IVFFlat index on document_embeddings (requires rows to exist)."""
    async with engine.begin() as conn:
        try:
            await conn.execute(text(EMBEDDING_INDEX_DDL))
        except (ProgrammingError, OperationalError) as e:
            logger.debug("pgvector embedding index creation skipped: %s", e)
