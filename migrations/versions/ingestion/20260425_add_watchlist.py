"""add watchlist (F11)

Revision ID: c8e9f0a1b2c3
Revises: ac6a4414ac58
Create Date: 2026-04-25

F11 Topic Watchlist: persistent user-defined interests and the
hybrid keyword+semantic match log that backs notifications.

The pgvector extension is ensured idempotently. In the current
topology (single `tg_parser` DB with per-domain `alembic_version_*`
tables) the extension is already installed via the processing
domain; the CREATE EXTENSION here is a safe-guard for clean-init.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8e9f0a1b2c3"
down_revision: str | None = "ac6a4414ac58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    conn.execute(
        sa.text("""
        CREATE TABLE IF NOT EXISTS watch_interests (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            chat_id BIGINT NOT NULL,
            title VARCHAR(300) NOT NULL,
            description TEXT,
            keywords TEXT[] NOT NULL DEFAULT '{}'::text[],
            exclude_keywords TEXT[] NOT NULL DEFAULT '{}'::text[],
            channel_ids TEXT[] NOT NULL,
            threshold DOUBLE PRECISION NOT NULL DEFAULT 0.6,
            notify_mode VARCHAR(20) NOT NULL DEFAULT 'instant',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            embedding vector(1536),
            last_checked_at TIMESTAMPTZ,
            last_match_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT watch_interests_threshold_range
                CHECK (threshold >= 0.0 AND threshold <= 1.0),
            CONSTRAINT watch_interests_channels_nonempty
                CHECK (array_length(channel_ids, 1) >= 1),
            CONSTRAINT watch_interests_notify_mode_known
                CHECK (notify_mode IN ('instant', 'batch', 'silent'))
        )
    """)
    )

    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_watch_interests_user_id ON watch_interests(user_id)"
        )
    )

    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_watch_interests_active "
            "ON watch_interests(is_active) WHERE is_active = TRUE"
        )
    )

    conn.execute(
        sa.text("""
        CREATE TABLE IF NOT EXISTS watch_matches (
            id BIGSERIAL PRIMARY KEY,
            interest_id UUID NOT NULL
                REFERENCES watch_interests(id) ON DELETE CASCADE,
            source_ref VARCHAR(200) NOT NULL,
            channel_id VARCHAR(200) NOT NULL,
            keyword_score DOUBLE PRECISION NOT NULL,
            semantic_score DOUBLE PRECISION NOT NULL,
            combined_score DOUBLE PRECISION NOT NULL,
            notified BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_watch_matches_interest_source
                UNIQUE (interest_id, source_ref)
        )
    """)
    )

    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_watch_matches_interest_created "
            "ON watch_matches(interest_id, created_at)"
        )
    )


def downgrade() -> None:
    op.drop_index(
        "idx_watch_matches_interest_created",
        table_name="watch_matches",
    )
    op.drop_table("watch_matches")
    op.drop_index(
        "idx_watch_interests_active",
        table_name="watch_interests",
    )
    op.drop_index(
        "idx_watch_interests_user_id",
        table_name="watch_interests",
    )
    op.drop_table("watch_interests")
    # pgvector extension is intentionally NOT dropped: it is shared
    # with the processing domain (document_embeddings) and other
    # potential future F-features.
