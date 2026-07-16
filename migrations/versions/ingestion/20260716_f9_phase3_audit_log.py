"""F9 Phase 3 — immutable audit_log MVP (ingestion)

Revision ID: c0d1e2f3a4b5
Revises: b9c8d7e6f5a4
Create Date: 2026-07-16

Append-only audit trail for security-relevant mutations and auth rejects.
App writes INSERT only; retention forever (MVP). No read API in this revision.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c0d1e2f3a4b5"
down_revision: str | None = "b9c8d7e6f5a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            action TEXT NOT NULL,
            resource_type TEXT,
            resource_id TEXT,
            outcome TEXT NOT NULL,
            meta JSONB,
            CONSTRAINT ck_audit_log_outcome CHECK (
                outcome IN ('success', 'failure', 'denied')
            )
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_log_action_created ON audit_log(action, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_log_actor_created "
        "ON audit_log(actor_user_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_audit_log_actor_created")
    op.execute("DROP INDEX IF EXISTS idx_audit_log_action_created")
    op.execute("DROP INDEX IF EXISTS idx_audit_log_created_at")
    op.execute("DROP TABLE IF EXISTS audit_log")
