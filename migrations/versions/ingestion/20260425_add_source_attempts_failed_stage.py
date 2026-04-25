"""add failed_stage to source_attempts

Revision ID: a1d1_topic_failed_stage
Revises: f6a1b2c3d4e5
Create Date: 2026-04-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1d1_topic_failed_stage"
down_revision: str | None = "f6a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("source_attempts")]
    if "failed_stage" not in columns:
        conn.execute(sa.text("ALTER TABLE source_attempts ADD COLUMN failed_stage VARCHAR"))


def downgrade() -> None:
    op.drop_column("source_attempts", "failed_stage")
