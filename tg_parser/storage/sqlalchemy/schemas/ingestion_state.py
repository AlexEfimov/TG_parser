"""
DDL для ingestion state storage (PostgreSQL).

Реализует схему из docs/architecture.md.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

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
  id SERIAL PRIMARY KEY,
  source_id TEXT NOT NULL,
  attempt_at TEXT NOT NULL,
  success INTEGER NOT NULL CHECK(success IN (0, 1)),
  error_class TEXT,
  error_message TEXT,
  details_json TEXT
);

CREATE INDEX IF NOT EXISTS source_attempts_source_time_idx
ON source_attempts(source_id, attempt_at);

-- Users (F4 Multi-Tenancy)
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    max_channels INTEGER DEFAULT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_auth_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    auth_type TEXT NOT NULL CHECK (auth_type IN ('api_key', 'telegram', 'mcp_token')),
    auth_identifier TEXT NOT NULL,
    client_name TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(auth_type, auth_identifier)
);
CREATE INDEX IF NOT EXISTS idx_uam_lookup ON user_auth_mappings(auth_type, auth_identifier);

ALTER TABLE sources ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id);
CREATE INDEX IF NOT EXISTS idx_sources_owner ON sources(owner_id);

-- Scheduled Digests (F6)
CREATE TABLE IF NOT EXISTS digest_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chat_id BIGINT NOT NULL,
    name VARCHAR(200) NOT NULL,
    channel_ids TEXT[] NOT NULL,
    cron_expression VARCHAR(100) NOT NULL DEFAULT '0 9 * * *',
    timezone VARCHAR(50) NOT NULL DEFAULT 'UTC',
    format VARCHAR(20) NOT NULL DEFAULT 'summary',
    language VARCHAR(10) NOT NULL DEFAULT 'ru',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_sent_at TIMESTAMPTZ,
    last_digest_cursor TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT digest_subscriptions_channel_ids_nonempty
        CHECK (array_length(channel_ids, 1) >= 1)
);
CREATE INDEX IF NOT EXISTS idx_digest_subscriptions_owner_active
    ON digest_subscriptions(owner_id, is_active);
CREATE INDEX IF NOT EXISTS idx_digest_subscriptions_active_cron
    ON digest_subscriptions(is_active) WHERE is_active = TRUE;
"""


async def init_ingestion_state_schema(engine: AsyncEngine) -> None:
    """
    Создать таблицы для ingestion state storage.

    Args:
        engine: AsyncEngine for ingestion state database
    """
    async with engine.begin() as conn:
        for statement in INGESTION_STATE_DDL.split(";"):
            statement = statement.strip()
            if statement:
                await conn.execute(text(statement))
