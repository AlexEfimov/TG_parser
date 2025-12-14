"""
DDL для raw_storage.sqlite.

Реализует схему из docs/architecture.md, раздел "raw_storage.sqlite".
"""

from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy import text


RAW_STORAGE_DDL = """
-- Таблица raw-сообщений (TR-18, TR-20)
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
);

CREATE INDEX IF NOT EXISTS raw_messages_channel_date_idx ON raw_messages(channel_id, date);
CREATE INDEX IF NOT EXISTS raw_messages_thread_idx ON raw_messages(thread_id);
CREATE INDEX IF NOT EXISTS raw_messages_type_idx ON raw_messages(message_type);

-- Журнал коллизий/наблюдений при повторном ingestion (TR-8)
CREATE TABLE IF NOT EXISTS raw_conflicts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_ref TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  reason TEXT NOT NULL,
  new_payload_json TEXT,
  new_text TEXT,
  new_date TEXT
);

CREATE INDEX IF NOT EXISTS raw_conflicts_source_time_idx
ON raw_conflicts(source_ref, observed_at);
"""


async def init_raw_storage_schema(engine: AsyncEngine) -> None:
    """
    Создать таблицы для raw_storage.sqlite.
    
    Args:
        engine: AsyncEngine для raw_storage.sqlite
    """
    async with engine.begin() as conn:
        for statement in RAW_STORAGE_DDL.split(";"):
            statement = statement.strip()
            if statement:
                await conn.execute(text(statement))
