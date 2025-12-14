"""
DDL для processing_storage.sqlite.

Реализует схему из docs/architecture.md, раздел "processing_storage.sqlite".
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

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
"""


async def init_processing_storage_schema(engine: AsyncEngine) -> None:
    """
    Создать таблицы для processing_storage.sqlite.

    Args:
        engine: AsyncEngine для processing_storage.sqlite
    """
    async with engine.begin() as conn:
        for statement in PROCESSING_STORAGE_DDL.split(";"):
            statement = statement.strip()
            if statement:
                await conn.execute(text(statement))
