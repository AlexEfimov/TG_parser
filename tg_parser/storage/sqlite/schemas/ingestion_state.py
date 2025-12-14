"""
DDL для ingestion_state.sqlite.

Реализует схему из docs/architecture.md, раздел "ingestion_state.sqlite".
"""

from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy import text


INGESTION_STATE_DDL = """
-- Таблица источников (TR-15)
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
);

CREATE INDEX IF NOT EXISTS sources_status_idx ON sources(status);
CREATE INDEX IF NOT EXISTS sources_channel_id_idx ON sources(channel_id);

-- Per-post курсоры комментариев (TR-7, TR-15)
CREATE TABLE IF NOT EXISTS comment_cursors (
  source_id TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  last_comment_id TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (source_id, thread_id)
);

CREATE INDEX IF NOT EXISTS comment_cursors_thread_idx ON comment_cursors(thread_id);

-- История попыток/ошибок (TR-11, TR-15)
CREATE TABLE IF NOT EXISTS source_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT NOT NULL,
  attempt_at TEXT NOT NULL,
  success INTEGER NOT NULL CHECK(success IN (0, 1)),
  error_class TEXT,
  error_message TEXT,
  details_json TEXT
);

CREATE INDEX IF NOT EXISTS source_attempts_source_time_idx
ON source_attempts(source_id, attempt_at);
"""


async def init_ingestion_state_schema(engine: AsyncEngine) -> None:
    """
    Создать таблицы для ingestion_state.sqlite.
    
    Args:
        engine: AsyncEngine для ingestion_state.sqlite
    """
    async with engine.begin() as conn:
        # Выполняем все DDL-команды
        for statement in INGESTION_STATE_DDL.split(";"):
            statement = statement.strip()
            if statement:
                await conn.execute(text(statement))
