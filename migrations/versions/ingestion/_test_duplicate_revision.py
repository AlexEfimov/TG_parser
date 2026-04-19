"""TEMP: verify alembic guardrail catches duplicate revision id

Revision ID: deadbeef0001
Revises: b2c3d4e5f6a7
Create Date: 2026-04-19

This file intentionally creates a parallel branch in `ingestion`:
- existing chain: 89f91e768b9b -> b2c3d4e5f6a7 -> f6a1b2c3d4e5 (head)
- this fake:     b2c3d4e5f6a7 -> deadbeef0001 (head)

Result: ingestion gets 2 heads, which the alembic-guardrail CI job MUST catch.

This file is reverted by the next commit.
"""

from collections.abc import Sequence

revision: str = "deadbeef0001"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
