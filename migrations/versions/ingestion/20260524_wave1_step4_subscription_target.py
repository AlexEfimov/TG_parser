"""Wave 1 step 4 — ADR 0008 polymorphic subscription target (chat | channel)

Revision ID: a8b7c6d5e4f3
Revises: f1a2b3c4d5e6
Create Date: 2026-05-24

Adds ``target_kind`` Postgres ENUM (``chat``, ``channel``) and nullable
``channel_id`` to ``digest_subscriptions`` and ``watch_interests``.
Existing rows backfill to ``target_kind='chat'``. ``chat_id`` becomes
nullable so ``kind=channel`` rows can omit a delivery chat (fallback
notification uses owner ``chat_id`` when present — see ADR 0008 OQ#3).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8b7c6d5e4f3"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TARGET_KIND = sa.Enum("chat", "channel", name="target_kind")


def upgrade() -> None:
    conn = op.get_bind()
    _TARGET_KIND.create(conn, checkfirst=True)

    for table in ("digest_subscriptions", "watch_interests"):
        op.add_column(
            table,
            sa.Column(
                "target_kind",
                _TARGET_KIND,
                nullable=False,
                server_default="chat",
            ),
        )
        op.add_column(table, sa.Column("channel_id", sa.String(), nullable=True))
        op.alter_column(table, "chat_id", existing_type=sa.BigInteger(), nullable=True)

    conn.execute(sa.text("UPDATE digest_subscriptions SET target_kind = 'chat'"))
    conn.execute(sa.text("UPDATE watch_interests SET target_kind = 'chat'"))

    for table in ("digest_subscriptions", "watch_interests"):
        op.alter_column(table, "target_kind", server_default=None)


def downgrade() -> None:
    conn = op.get_bind()
    for table in ("digest_subscriptions", "watch_interests"):
        null_chat = conn.execute(
            sa.text(f"SELECT COUNT(*) FROM {table} WHERE chat_id IS NULL")
        ).scalar()
        if null_chat and int(null_chat) > 0:
            raise RuntimeError(
                f"Migration downgrade aborted: {table} has {null_chat} row(s) with "
                "NULL chat_id (channel targets). Remove or migrate those rows first."
            )

    for table in ("digest_subscriptions", "watch_interests"):
        op.drop_column(table, "channel_id")
        op.drop_column(table, "target_kind")
        op.alter_column(table, "chat_id", existing_type=sa.BigInteger(), nullable=False)

    _TARGET_KIND.drop(conn, checkfirst=True)
