"""add digest_subscriptions table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-18

F6 Scheduled Digests: per-user subscriptions for cron-driven digests.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a1b2c3d4e5"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text("""
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
        )
    """)
    )

    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_digest_subscriptions_owner_active "
            "ON digest_subscriptions(owner_id, is_active)"
        )
    )

    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_digest_subscriptions_active_cron "
            "ON digest_subscriptions(is_active) WHERE is_active = TRUE"
        )
    )


def downgrade() -> None:
    op.drop_index(
        "idx_digest_subscriptions_active_cron",
        table_name="digest_subscriptions",
    )
    op.drop_index(
        "idx_digest_subscriptions_owner_active",
        table_name="digest_subscriptions",
    )
    op.drop_table("digest_subscriptions")
