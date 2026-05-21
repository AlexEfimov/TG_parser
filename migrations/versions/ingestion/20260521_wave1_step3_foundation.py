"""Wave 1 step 3 — Surface Parity foundation (ENH-9 + BUG-022)

Revision ID: f1a2b3c4d5e6
Revises: e9f0a1b2c3d5
Create Date: 2026-05-21

Wave 1 step 3 / commit 1/4 — service-layer foundation for the
Surface Parity sprint. Three additive changes against the ingestion
domain — no read-path regression:

1. ``watch_interests.workspace_id UUID NULL`` FK → ``workspaces.id``
   ``ON DELETE SET NULL`` (ENH-9: optional workspace association;
   interest survives workspace deletion per ADR 0008 Q3-A).
2. ``digest_subscriptions.workspace_id UUID NULL`` FK → ``workspaces.id``
   ``ON DELETE SET NULL`` (ENH-9, same semantics).
3. ``UNIQUE (user_id, title)`` on ``watch_interests`` +
   ``UNIQUE (owner_id, name)`` on ``digest_subscriptions`` —
   natural-key idempotency boundary that closes BUG-022 at the DB
   layer. Service-layer upsert (commit 1/4 ``WatchlistService.subscribe``
   / ``DigestService.subscribe``) catches the ``IntegrityError`` and
   retries as UPDATE so race-condition concurrent inserts collapse
   into a single row.
4. ``idempotency_keys`` table (skeleton — used by HTTP middleware in
   commit 4/4). PK on ``key TEXT``, FK on ``user_id``, ``request_hash``
   + ``response_body JSONB`` for safe replay, 24h TTL via cleanup job
   (commit 4/4). Indexes on ``created_at`` (cleanup sweep) and
   ``user_id`` (per-tenant scoping).

Self-defensive pre-flight (Option A from sprint prompt §3 Q-OPEN-5):
before ADD CONSTRAINT UNIQUE on both tables, ``upgrade()`` runs SELECT
queries to detect ``(user_id, title)`` and ``(owner_id, name)``
duplicate groups. If any are found, ``upgrade()`` raises
``RuntimeError`` with a pointer to
``docs/runbooks/wave1_step3_idempotency_dedupe.md`` so the operator
deduplicates by hand before re-running. R-3 from sprint risk register
downgraded High → Low by this guard.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "e9f0a1b2c3d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_RUNBOOK_REF = "docs/runbooks/wave1_step3_idempotency_dedupe.md"


def _assert_no_duplicates(conn: sa.engine.Connection) -> None:
    """Self-defensive pre-flight before ADD CONSTRAINT UNIQUE.

    The new UNIQUE constraints apply to ALL rows (active or
    soft-deleted) because re-subscribing with the same label should
    resurrect the existing row at the service layer — we cannot allow
    two physical rows even if one is ``is_active = FALSE``. The check
    therefore runs without an ``is_active`` filter.
    """
    wi_dups = conn.execute(
        sa.text(
            "SELECT user_id, title, COUNT(*) AS n "
            "FROM watch_interests "
            "GROUP BY user_id, title "
            "HAVING COUNT(*) > 1"
        )
    ).fetchall()
    if wi_dups:
        raise RuntimeError(
            f"Migration aborted: {len(wi_dups)} duplicate (user_id, title) "
            f"group(s) found in watch_interests. Pre-existing duplicates "
            f"would violate the new UNIQUE constraint introduced by this "
            f"migration (BUG-022 natural-key idempotency). Dedupe by hand "
            f"per {_RUNBOOK_REF} before re-running `alembic upgrade head`."
        )

    ds_dups = conn.execute(
        sa.text(
            "SELECT owner_id, name, COUNT(*) AS n "
            "FROM digest_subscriptions "
            "GROUP BY owner_id, name "
            "HAVING COUNT(*) > 1"
        )
    ).fetchall()
    if ds_dups:
        raise RuntimeError(
            f"Migration aborted: {len(ds_dups)} duplicate (owner_id, name) "
            f"group(s) found in digest_subscriptions. Pre-existing duplicates "
            f"would violate the new UNIQUE constraint introduced by this "
            f"migration (BUG-022 natural-key idempotency). Dedupe by hand "
            f"per {_RUNBOOK_REF} before re-running `alembic upgrade head`."
        )


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Self-defensive dedupe pre-flight (R-3 downgrade High → Low).
    _assert_no_duplicates(conn)

    # 2. ENH-9: workspace_id FK on both subscription tables.
    conn.execute(
        sa.text(
            "ALTER TABLE watch_interests "
            "ADD COLUMN IF NOT EXISTS workspace_id UUID NULL "
            "REFERENCES workspaces(id) ON DELETE SET NULL"
        )
    )
    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_watch_interests_workspace_id "
            "ON watch_interests(workspace_id) WHERE workspace_id IS NOT NULL"
        )
    )

    conn.execute(
        sa.text(
            "ALTER TABLE digest_subscriptions "
            "ADD COLUMN IF NOT EXISTS workspace_id UUID NULL "
            "REFERENCES workspaces(id) ON DELETE SET NULL"
        )
    )
    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_digest_subscriptions_workspace_id "
            "ON digest_subscriptions(workspace_id) WHERE workspace_id IS NOT NULL"
        )
    )

    # 3. BUG-022: natural-key UNIQUE constraints. Raw SQL (mirrors the
    # codebase convention from 20260513_add_workspaces.py — keep
    # constraint creation outside the alembic op.* surface so the
    # static-analysis guardrail in tests/test_migrations_self_contained.py
    # treats the constraint name correctly rather than mis-classifying
    # it as an ALTER target).
    conn.execute(
        sa.text(
            "ALTER TABLE watch_interests "
            "ADD CONSTRAINT uq_watch_interests_user_title UNIQUE (user_id, title)"
        )
    )
    conn.execute(
        sa.text(
            "ALTER TABLE digest_subscriptions "
            "ADD CONSTRAINT uq_digest_subscriptions_owner_name UNIQUE (owner_id, name)"
        )
    )

    # 4. idempotency_keys skeleton (commit 4/4 wires HTTP middleware).
    conn.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS idempotency_keys (
                key TEXT PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                request_hash TEXT NOT NULL,
                response_body JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_idempotency_keys_created_at "
            "ON idempotency_keys(created_at)"
        )
    )
    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_idempotency_keys_user_id ON idempotency_keys(user_id)"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("DROP INDEX IF EXISTS idx_idempotency_keys_user_id"))
    conn.execute(sa.text("DROP INDEX IF EXISTS idx_idempotency_keys_created_at"))
    conn.execute(sa.text("DROP TABLE IF EXISTS idempotency_keys"))

    conn.execute(
        sa.text(
            "ALTER TABLE digest_subscriptions "
            "DROP CONSTRAINT IF EXISTS uq_digest_subscriptions_owner_name"
        )
    )
    conn.execute(
        sa.text(
            "ALTER TABLE watch_interests DROP CONSTRAINT IF EXISTS uq_watch_interests_user_title"
        )
    )

    conn.execute(sa.text("DROP INDEX IF EXISTS idx_digest_subscriptions_workspace_id"))
    conn.execute(sa.text("ALTER TABLE digest_subscriptions DROP COLUMN IF EXISTS workspace_id"))

    conn.execute(sa.text("DROP INDEX IF EXISTS idx_watch_interests_workspace_id"))
    conn.execute(sa.text("ALTER TABLE watch_interests DROP COLUMN IF EXISTS workspace_id"))
