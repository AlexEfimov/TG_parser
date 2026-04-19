"""SQLAlchemy ``Table()`` declarations for alembic ``target_metadata`` (DI-1).

Three independent ``MetaData()`` instances — one per logical database
(``ingestion`` / ``raw`` / ``processing``).  Used by ``migrations/env.py``
to feed ``alembic check`` and ``alembic revision --autogenerate``.

Ground-truth note (DI-1, Sprint A.2)
------------------------------------
Migrations under ``migrations/versions/{ingestion,raw,processing}/`` are
the canonical source of truth for production schema.  These declarations
mirror the *result* of running ``alembic upgrade head`` on every branch
(``op.create_table`` plus subsequent ``op.add_column`` /
``op.create_index`` plus the raw-SQL ``sa.text("CREATE TABLE …")``
statements used by some later migrations).  Whenever a migration changes,
update these declarations to match.

We intentionally do **not** pass ``naming_convention=...`` to ``MetaData``
because the existing migrations have never used a naming convention; adding
one here would synthesise drift on every existing index / constraint at
the first ``alembic check`` run.  See DI-1 / DI-3 in
``docs/notes/FUTURE_FEATURES.md`` for the follow-up story.
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import REAL, TIMESTAMP, TSVECTOR, UUID
from sqlalchemy.types import CHAR

INGESTION_METADATA = MetaData()
RAW_METADATA = MetaData()
PROCESSING_METADATA = MetaData()


# ============================================================================
# Ingestion branch (head: f6a1b2c3d4e5)
# ============================================================================

# sources — initial 89f91e768b9b + owner_id added in b2c3d4e5f6a7
Table(
    "sources",
    INGESTION_METADATA,
    Column("source_id", String(), nullable=False),
    Column("channel_id", String(), nullable=False),
    Column("channel_username", String(), nullable=True),
    Column("status", String(), nullable=False),
    Column("include_comments", Boolean(), nullable=False),
    Column("history_from", String(), nullable=True),
    Column("history_to", String(), nullable=True),
    Column("poll_interval_seconds", Integer(), nullable=True),
    Column("batch_size", Integer(), nullable=True),
    Column("last_post_id", String(), nullable=True),
    Column("backfill_completed_at", String(), nullable=True),
    Column("last_attempt_at", String(), nullable=True),
    Column("last_success_at", String(), nullable=True),
    Column("fail_count", Integer(), nullable=False, server_default="0"),
    Column("last_error", String(), nullable=True),
    Column("rate_limit_until", String(), nullable=True),
    Column("comments_unavailable", Boolean(), nullable=False, server_default="0"),
    Column("created_at", String(), nullable=False),
    Column("updated_at", String(), nullable=False),
    Column("owner_id", UUID(as_uuid=True), nullable=True),
    PrimaryKeyConstraint("source_id"),
    CheckConstraint("status IN ('active', 'paused', 'error')", name="sources_status_check"),
    ForeignKeyConstraint(["owner_id"], ["users.id"], name="sources_owner_id_fkey"),
    Index("sources_status_idx", "status"),
    Index("sources_channel_id_idx", "channel_id"),
    Index("idx_sources_owner", "owner_id"),
)

Table(
    "comment_cursors",
    INGESTION_METADATA,
    Column("source_id", String(), nullable=False),
    Column("thread_id", String(), nullable=False),
    Column("last_comment_id", String(), nullable=True),
    Column("updated_at", String(), nullable=False),
    PrimaryKeyConstraint("source_id", "thread_id"),
    Index("comment_cursors_thread_idx", "thread_id"),
)

Table(
    "source_attempts",
    INGESTION_METADATA,
    Column("id", Integer(), nullable=False),
    Column("source_id", String(), nullable=False),
    Column("attempt_at", String(), nullable=False),
    Column("success", Boolean(), nullable=False),
    Column("error_class", String(), nullable=True),
    Column("error_message", String(), nullable=True),
    Column("details_json", String(), nullable=True),
    PrimaryKeyConstraint("id"),
    Index("source_attempts_source_time_idx", "source_id", "attempt_at"),
)

# users — created via raw SQL in b2c3d4e5f6a7
Table(
    "users",
    INGESTION_METADATA,
    Column("id", UUID(as_uuid=True), nullable=False, server_default=text("gen_random_uuid()")),
    Column("name", Text(), nullable=False),
    Column("role", Text(), nullable=False, server_default=text("'user'::text")),
    Column("max_channels", Integer(), nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), server_default=text("now()"), nullable=True),
    Column("updated_at", TIMESTAMP(timezone=True), server_default=text("now()"), nullable=True),
    PrimaryKeyConstraint("id", name="users_pkey"),
    CheckConstraint("role IN ('admin', 'user')", name="users_role_check"),
)

# user_auth_mappings — created via raw SQL in b2c3d4e5f6a7
Table(
    "user_auth_mappings",
    INGESTION_METADATA,
    Column("id", UUID(as_uuid=True), nullable=False, server_default=text("gen_random_uuid()")),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("auth_type", Text(), nullable=False),
    Column("auth_identifier", Text(), nullable=False),
    Column("client_name", Text(), nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), server_default=text("now()"), nullable=True),
    PrimaryKeyConstraint("id", name="user_auth_mappings_pkey"),
    ForeignKeyConstraint(
        ["user_id"],
        ["users.id"],
        ondelete="CASCADE",
        name="user_auth_mappings_user_id_fkey",
    ),
    UniqueConstraint(
        "auth_type",
        "auth_identifier",
        name="user_auth_mappings_auth_type_auth_identifier_key",
    ),
    CheckConstraint(
        "auth_type IN ('api_key', 'telegram', 'mcp_token')",
        name="user_auth_mappings_auth_type_check",
    ),
    Index("idx_uam_lookup", "auth_type", "auth_identifier"),
)

# digest_subscriptions — created via raw SQL in f6a1b2c3d4e5
Table(
    "digest_subscriptions",
    INGESTION_METADATA,
    Column("id", UUID(as_uuid=True), nullable=False, server_default=text("gen_random_uuid()")),
    Column("owner_id", UUID(as_uuid=True), nullable=False),
    Column("chat_id", BigInteger(), nullable=False),
    Column("name", String(length=200), nullable=False),
    Column("channel_ids", ARRAY(Text()), nullable=False),
    Column(
        "cron_expression",
        String(length=100),
        nullable=False,
        server_default=text("'0 9 * * *'::character varying"),
    ),
    Column(
        "timezone",
        String(length=50),
        nullable=False,
        server_default=text("'UTC'::character varying"),
    ),
    Column(
        "format",
        String(length=20),
        nullable=False,
        server_default=text("'summary'::character varying"),
    ),
    Column(
        "language",
        String(length=10),
        nullable=False,
        server_default=text("'ru'::character varying"),
    ),
    Column("is_active", Boolean(), nullable=False, server_default=text("true")),
    Column("last_sent_at", TIMESTAMP(timezone=True), nullable=True),
    Column("last_digest_cursor", TIMESTAMP(timezone=True), nullable=True),
    Column(
        "created_at",
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    Column(
        "updated_at",
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    PrimaryKeyConstraint("id", name="digest_subscriptions_pkey"),
    ForeignKeyConstraint(
        ["owner_id"],
        ["users.id"],
        ondelete="CASCADE",
        name="digest_subscriptions_owner_id_fkey",
    ),
    CheckConstraint(
        "array_length(channel_ids, 1) >= 1",
        name="digest_subscriptions_channel_ids_nonempty",
    ),
    Index("idx_digest_subscriptions_owner_active", "owner_id", "is_active"),
    Index(
        "idx_digest_subscriptions_active_cron",
        "is_active",
        postgresql_where=text("is_active = true"),
    ),
)


# ============================================================================
# Raw branch (head: 5c658f04eff0)
# ============================================================================

Table(
    "raw_messages",
    RAW_METADATA,
    Column("source_ref", String(), nullable=False),
    Column("id", String(), nullable=False),
    Column("message_type", String(), nullable=False),
    Column("channel_id", String(), nullable=False),
    Column("date", String(), nullable=False),
    Column("text", String(), nullable=False),
    Column("thread_id", String(), nullable=True),
    Column("parent_message_id", String(), nullable=True),
    Column("language", String(), nullable=True),
    Column("raw_payload_json", Text(), nullable=True),
    Column("raw_payload_truncated", Boolean(), nullable=False, server_default="0"),
    Column("raw_payload_original_size_bytes", Integer(), nullable=True),
    Column("inserted_at", String(), nullable=False),
    PrimaryKeyConstraint("source_ref"),
    CheckConstraint("message_type IN ('post', 'comment')", name="raw_messages_type_check"),
    Index("raw_messages_channel_date_idx", "channel_id", "date"),
    Index("raw_messages_thread_idx", "thread_id"),
    Index("raw_messages_type_idx", "message_type"),
)

Table(
    "raw_conflicts",
    RAW_METADATA,
    Column("id", Integer(), nullable=False),
    Column("source_ref", String(), nullable=False),
    Column("observed_at", String(), nullable=False),
    Column("reason", String(), nullable=False),
    Column("new_payload_json", Text(), nullable=True),
    Column("new_text", String(), nullable=True),
    Column("new_date", String(), nullable=True),
    PrimaryKeyConstraint("id"),
    Index("raw_conflicts_source_time_idx", "source_ref", "observed_at"),
)


# ============================================================================
# Processing branch (head: b8e2f7c1d9a3)
# ============================================================================

# processed_documents — initial f40d85317f03 + search_vector (d4e5f6a7b8c9)
# + content_hash (f5a3c0d7e8b9)
_PD_SEARCH_VECTOR_EXPR = (
    "setweight(to_tsvector('simple'::regconfig, COALESCE(summary, ''::text)), 'A'::\"char\") "
    "|| setweight(to_tsvector('russian'::regconfig, COALESCE(text_clean, ''::text)), 'B'::\"char\") "
    "|| setweight(to_tsvector('english'::regconfig, COALESCE(text_clean, ''::text)), 'B'::\"char\")"
)

Table(
    "processed_documents",
    PROCESSING_METADATA,
    Column("source_ref", String(), nullable=False),
    Column("id", String(), nullable=False),
    Column("source_message_id", String(), nullable=False),
    Column("channel_id", String(), nullable=False),
    # processed_at intentionally remains String(); DI-10 will decide
    # whether to migrate to TIMESTAMPTZ.
    Column("processed_at", String(), nullable=False),
    Column("text_clean", Text(), nullable=False),
    Column("summary", Text(), nullable=True),
    Column("topics_json", Text(), nullable=True),
    Column("entities_json", Text(), nullable=True),
    Column("language", String(), nullable=True),
    Column("metadata_json", Text(), nullable=True),
    Column(
        "search_vector",
        TSVECTOR(),
        Computed(_PD_SEARCH_VECTOR_EXPR, persisted=True),
        nullable=True,
    ),
    Column("content_hash", CHAR(length=64), nullable=True),
    PrimaryKeyConstraint("source_ref"),
    Index("processed_documents_channel_idx", "channel_id"),
    Index("processed_documents_processed_at_idx", "processed_at"),
    Index("idx_pd_search_vector", "search_vector", postgresql_using="gin"),
    Index(
        "idx_pd_channel_content_hash",
        "channel_id",
        "content_hash",
        postgresql_where=text("content_hash IS NOT NULL"),
    ),
)

Table(
    "processing_failures",
    PROCESSING_METADATA,
    Column("source_ref", String(), nullable=False),
    Column("channel_id", String(), nullable=False),
    Column("attempts", Integer(), nullable=False),
    Column("last_attempt_at", String(), nullable=False),
    Column("error_class", String(), nullable=True),
    Column("error_message", Text(), nullable=True),
    Column("error_details_json", Text(), nullable=True),
    PrimaryKeyConstraint("source_ref"),
    Index("processing_failures_channel_idx", "channel_id"),
    Index("processing_failures_last_attempt_idx", "last_attempt_at"),
)

# topic_cards — initial f40d85317f03 + search_vector (e5f6a7b8c9d0)
_TC_SEARCH_VECTOR_EXPR = (
    "setweight(to_tsvector('simple'::regconfig, COALESCE(title, ''::text)), 'A'::\"char\") "
    "|| setweight(to_tsvector('russian'::regconfig, "
    "((COALESCE(summary, ''::text) || ' '::text) || COALESCE(scope_in_json, ''::text))), 'B'::\"char\") "
    "|| setweight(to_tsvector('english'::regconfig, "
    "((COALESCE(summary, ''::text) || ' '::text) || COALESCE(scope_in_json, ''::text))), 'B'::\"char\")"
)

Table(
    "topic_cards",
    PROCESSING_METADATA,
    Column("id", String(), nullable=False),
    Column("title", String(), nullable=False),
    Column("summary", Text(), nullable=False),
    Column("scope_in_json", Text(), nullable=False),
    Column("scope_out_json", Text(), nullable=False),
    Column("type", String(), nullable=False),
    Column("anchors_json", Text(), nullable=False),
    Column("sources_json", Text(), nullable=False),
    Column("updated_at", String(), nullable=False),
    Column("tags_json", Text(), nullable=True),
    Column("related_topics_json", Text(), nullable=True),
    Column("status", String(), nullable=True),
    Column("metadata_json", Text(), nullable=True),
    Column(
        "search_vector",
        TSVECTOR(),
        Computed(_TC_SEARCH_VECTOR_EXPR, persisted=True),
        nullable=True,
    ),
    PrimaryKeyConstraint("id"),
    CheckConstraint("type IN ('singleton', 'cluster')", name="topic_cards_type_check"),
    Index("topic_cards_updated_at_idx", "updated_at"),
    Index("idx_tc_search_vector", "search_vector", postgresql_using="gin"),
)

# topic_bundles — initial f40d85317f03 + partial unique indexes from b8e2f7c1d9a3
# Note: the non-unique snapshot_idx is the original (intentionally retained
# alongside the partial unique indexes added in DI-8 follow-up).
Table(
    "topic_bundles",
    PROCESSING_METADATA,
    Column("topic_id", String(), nullable=False),
    Column("updated_at", String(), nullable=False),
    Column("time_from", String(), nullable=True),
    Column("time_to", String(), nullable=True),
    Column("items_json", Text(), nullable=False),
    Column("channels_json", Text(), nullable=True),
    Column("metadata_json", Text(), nullable=True),
    Index("topic_bundles_topic_idx", "topic_id"),
    Index("topic_bundles_snapshot_idx", "topic_id", "time_from", "time_to"),
    Index(
        "topic_bundles_current_unique_idx",
        "topic_id",
        unique=True,
        postgresql_where=text("time_from IS NULL AND time_to IS NULL"),
    ),
    Index(
        "topic_bundles_snapshot_unique_idx",
        "topic_id",
        "time_from",
        "time_to",
        unique=True,
        postgresql_where=text("time_from IS NOT NULL AND time_to IS NOT NULL"),
    ),
)

Table(
    "api_jobs",
    PROCESSING_METADATA,
    Column("job_id", String(), nullable=False),
    Column("job_type", String(), nullable=False),
    Column("status", String(), nullable=False),
    Column("created_at", String(), nullable=False),
    Column("channel_id", String(), nullable=True),
    Column("client", String(), nullable=True),
    Column("started_at", String(), nullable=True),
    Column("completed_at", String(), nullable=True),
    Column("progress_json", Text(), nullable=True),
    Column("result_json", Text(), nullable=True),
    Column("error", Text(), nullable=True),
    Column("file_path", String(), nullable=True),
    Column("download_url", String(), nullable=True),
    Column("export_format", String(), nullable=True),
    Column("webhook_url", String(), nullable=True),
    Column("webhook_secret", String(), nullable=True),
    PrimaryKeyConstraint("job_id"),
    CheckConstraint("job_type IN ('processing', 'export')", name="api_jobs_type_check"),
    CheckConstraint(
        "status IN ('pending', 'running', 'completed', 'failed')",
        name="api_jobs_status_check",
    ),
    Index("api_jobs_status_idx", "status"),
    Index("api_jobs_created_at_idx", "created_at"),
    Index("api_jobs_job_type_idx", "job_type"),
)

Table(
    "agent_states",
    PROCESSING_METADATA,
    Column("name", String(), nullable=False),
    Column("agent_type", String(), nullable=False),
    Column("version", String(), nullable=False, server_default="1.0.0"),
    Column("description", Text(), nullable=True),
    Column("capabilities_json", Text(), nullable=False),
    Column("model", String(), nullable=True),
    Column("provider", String(), nullable=True),
    Column("is_active", Boolean(), nullable=False, server_default="1"),
    Column("metadata_json", Text(), nullable=True),
    Column("total_tasks_processed", Integer(), nullable=False, server_default="0"),
    Column("total_errors", Integer(), nullable=False, server_default="0"),
    Column("avg_processing_time_ms", Float(), nullable=False, server_default="0.0"),
    Column("last_used_at", String(), nullable=True),
    Column("created_at", String(), nullable=False),
    Column("updated_at", String(), nullable=False),
    PrimaryKeyConstraint("name"),
    Index("agent_states_type_idx", "agent_type"),
    Index("agent_states_active_idx", "is_active"),
)

Table(
    "task_history",
    PROCESSING_METADATA,
    Column("id", String(), nullable=False),
    Column("agent_name", String(), nullable=False),
    Column("task_type", String(), nullable=False),
    Column("source_ref", String(), nullable=True),
    Column("channel_id", String(), nullable=True),
    Column("input_json", Text(), nullable=False),
    Column("output_json", Text(), nullable=True),
    Column("success", Boolean(), nullable=False, server_default="1"),
    Column("error", Text(), nullable=True),
    Column("processing_time_ms", Integer(), nullable=True),
    Column("created_at", String(), nullable=False),
    Column("expires_at", String(), nullable=True),
    PrimaryKeyConstraint("id"),
    ForeignKeyConstraint(
        ["agent_name"],
        ["agent_states.name"],
        name="task_history_agent_name_fkey",
    ),
    Index("task_history_agent_idx", "agent_name"),
    Index("task_history_channel_idx", "channel_id"),
    Index("task_history_created_idx", "created_at"),
    Index("task_history_expires_idx", "expires_at"),
    Index("task_history_source_ref_idx", "source_ref"),
)

Table(
    "agent_stats",
    PROCESSING_METADATA,
    Column("agent_name", String(), nullable=False),
    Column("date", String(), nullable=False),
    Column("task_type", String(), nullable=False),
    Column("total_tasks", Integer(), nullable=False, server_default="0"),
    Column("successful_tasks", Integer(), nullable=False, server_default="0"),
    Column("failed_tasks", Integer(), nullable=False, server_default="0"),
    Column("total_processing_time_ms", Integer(), nullable=False, server_default="0"),
    Column("min_processing_time_ms", Integer(), nullable=True),
    Column("max_processing_time_ms", Integer(), nullable=True),
    PrimaryKeyConstraint("agent_name", "date", "task_type"),
    Index("agent_stats_agent_idx", "agent_name"),
    Index("agent_stats_date_idx", "date"),
)

Table(
    "handoff_history",
    PROCESSING_METADATA,
    Column("id", String(), nullable=False),
    Column("source_agent", String(), nullable=False),
    Column("target_agent", String(), nullable=False),
    Column("task_type", String(), nullable=False),
    Column("priority", Integer(), nullable=False, server_default="5"),
    Column("status", String(), nullable=False),
    Column("payload_json", Text(), nullable=True),
    Column("context_json", Text(), nullable=True),
    Column("result_json", Text(), nullable=True),
    Column("error", Text(), nullable=True),
    Column("processing_time_ms", Integer(), nullable=True),
    Column("created_at", String(), nullable=False),
    Column("accepted_at", String(), nullable=True),
    Column("completed_at", String(), nullable=True),
    PrimaryKeyConstraint("id"),
    CheckConstraint(
        "status IN ('pending', 'accepted', 'in_progress', 'completed', 'failed', 'rejected')",
        name="handoff_history_status_check",
    ),
    Index("handoff_history_source_idx", "source_agent"),
    Index("handoff_history_target_idx", "target_agent"),
    Index("handoff_history_status_idx", "status"),
    Index("handoff_history_created_idx", "created_at"),
)

# document_embeddings — defensive bootstrap in a1b2c3d4e5f6 + channel_ids in c3d4e5f6a7b8
Table(
    "document_embeddings",
    PROCESSING_METADATA,
    Column("source_ref", Text(), nullable=False),
    Column("embedding", Vector(1536), nullable=True),
    Column("model", Text(), nullable=False),
    Column("created_at", Text(), nullable=False),
    Column("metadata_json", Text(), nullable=True),
    Column("entry_type", Text(), nullable=False, server_default=text("'message'::text")),
    Column("topic_id", Text(), nullable=True),
    Column("channel_ids", ARRAY(Text()), nullable=True, server_default=text("'{}'::text[]")),
    PrimaryKeyConstraint("source_ref", name="document_embeddings_pkey"),
    Index("idx_de_entry_type", "entry_type"),
    Index("idx_de_channel_ids", "channel_ids", postgresql_using="gin"),
)

# topic_links — bootstrap in b8e2f7c1d9a3 (DI-8 audit)
Table(
    "topic_links",
    PROCESSING_METADATA,
    Column("topic_id_a", Text(), nullable=False),
    Column("topic_id_b", Text(), nullable=False),
    Column("similarity_score", REAL(), nullable=False),
    Column("shared_keywords_json", Text(), nullable=True),
    Column("created_at", Text(), nullable=False),
    PrimaryKeyConstraint("topic_id_a", "topic_id_b", name="topic_links_pkey"),
    Index("topic_links_a_idx", "topic_id_a"),
    Index("topic_links_b_idx", "topic_id_b"),
    Index("topic_links_score_idx", text("similarity_score DESC")),
)


# ============================================================================
# Lookup helper for migrations/env.py
# ============================================================================

METADATA_BY_DB: dict[str, MetaData] = {
    "ingestion": INGESTION_METADATA,
    "raw": RAW_METADATA,
    "processing": PROCESSING_METADATA,
}
