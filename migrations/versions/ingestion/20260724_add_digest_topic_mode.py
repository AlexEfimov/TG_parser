"""F5-C #15 item #3 — F6 topic-digest subscription addendum (ADR-0019)

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-07-24

Additive schema-add for topic-scoped digests: two columns on
``digest_subscriptions``.

* ``mode`` VARCHAR NOT NULL DEFAULT 'channel' — subscription discriminator.
  ``'channel'`` = existing raw-document F6 digest (bit-for-bit, every legacy
  row backfills to this default → no regression). ``'topic'`` = evolving
  topic-summary-delta digest (content = ``diff_topic_summaries`` per changed
  topic).
* ``topic_ids`` TEXT[] (nullable) — explicit topic ids for ``mode='topic'``.
  NULL for channel-mode rows.

Chained off the current **ingestion** head (``c0d1e2f3a4b5``); migrations are
split into ``ingestion/`` + ``processing/`` branches so ``alembic heads``
returns multiple heads — the ``20260418_add_digest_subscriptions.py`` file is
only a structural precedent, not the down_revision target. Additive /
nullable / defaulted ⇒ safe upgrade; downgrade drops both columns.
Both directions are idempotent (``IF [NOT] EXISTS`` guards).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: str | None = "c0d1e2f3a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "ALTER TABLE digest_subscriptions "
            "ADD COLUMN IF NOT EXISTS mode VARCHAR NOT NULL DEFAULT 'channel'"
        )
    )
    conn.execute(
        sa.text("ALTER TABLE digest_subscriptions ADD COLUMN IF NOT EXISTS topic_ids TEXT[]")
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE digest_subscriptions DROP COLUMN IF EXISTS topic_ids"))
    conn.execute(sa.text("ALTER TABLE digest_subscriptions DROP COLUMN IF EXISTS mode"))
