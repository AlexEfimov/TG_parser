"""BUG-054 / ADR 0015 — watchlist threshold provenance (threshold_source)

Revision ID: b9c8d7e6f5a4
Revises: a8b7c6d5e4f3
Create Date: 2026-06-13

Adds a nullable ``threshold_source`` VARCHAR column to ``watch_interests``
with a CHECK constraint restricting it to ``('auto', 'manual', 'legacy')``
(NULL still allowed — expand phase of an expand/contract migration; tighten to
NOT NULL later). Pre-existing rows backfill to ``'legacy'`` because provenance
was never recorded before BUG-054; runtime treats ``legacy`` like ``manual``
(advisory-only) while keeping it distinguishable for future reclassification.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9c8d7e6f5a4"
down_revision: str | None = "a8b7c6d5e4f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK_NAME = "watch_interests_threshold_source_known"


def upgrade() -> None:
    op.add_column(
        "watch_interests",
        sa.Column("threshold_source", sa.String(), nullable=True),
    )
    op.create_check_constraint(
        _CHECK_NAME,
        "watch_interests",
        "threshold_source IS NULL OR threshold_source IN ('auto', 'manual', 'legacy')",
    )
    op.execute(
        sa.text(
            "UPDATE watch_interests SET threshold_source = 'legacy' WHERE threshold_source IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_constraint(_CHECK_NAME, "watch_interests", type_="check")
    op.drop_column("watch_interests", "threshold_source")
