"""add topic card versions + resummarize counters (F5-C)

Revision ID: a4b5c6d7e8f9
Revises: c9d8e7f6a5b4
Create Date: 2026-04-26

F5-C Evolving Topic Summaries:

- New table ``topic_card_versions`` (append-only audit log) — every
  successful re-summarize writes a row capturing the **previous** summary
  + scope_in / scope_out, the bundle item count at the time, and the LLM
  metadata (provider / model / prompt version).  ``UNIQUE(topic_id,
  version_no)`` plus FK CASCADE on delete are intentional: deleting a
  topic should drop its history, but two scheduler ticks racing on the
  same topic must collide loudly (advisory lock is the first defence;
  UNIQUE is the second).
- Three new columns on ``topic_cards``:
    * ``last_summarized_at TIMESTAMPTZ NULL`` — wall-clock of the last
      successful re-summarize (NULL means "never", but bootstrap below
      seeds the existing rows from ``updated_at`` so audit views read
      sensibly out of the box).
    * ``summary_version INTEGER NOT NULL DEFAULT 1`` — per-topic
      monotonic counter, ``+= 1`` on each successful commit_resummary.
    * ``new_items_since_last_summary INTEGER NOT NULL DEFAULT 0`` — the
      F5-C trigger.  ``_update_bundles_for_assignments`` bumps it once
      per added item; ``ResummarizationService`` resets it to 0 inside
      ``commit_resummary`` so the cycle starts again.
- Partial index ``idx_topic_cards_resummarize_candidates``:
    only ``WHERE new_items_since_last_summary > 0`` so the per-tick
    candidate scan is O(active topics), not O(all topics).  Most topics
    sit at 0 the vast majority of the time.
- Data-bootstrap for existing rows:
    * ``last_summarized_at = updated_at::timestamptz`` for rows whose
      ``updated_at`` matches the canonical ``YYYY-MM-DDTHH:MM:SSZ`` shape
      that ``topic_card_repo.upsert`` writes (regex uses POSIX classes so
      the migration is portable across stricter Postgres regex modes).
    * Fallback ``last_summarized_at = NOW()`` for any straggler whose
      format slipped past the regex.

The first scheduler tick after deploy will NOT trigger a thundering herd
of re-summaries because the trigger watches ``new_items_since_last_summary``,
which is 0 for every existing row.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4b5c6d7e8f9"
down_revision: str | None = "c9d8e7f6a5b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "topic_cards",
        sa.Column("last_summarized_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "topic_cards",
        sa.Column(
            "summary_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "topic_cards",
        sa.Column(
            "new_items_since_last_summary",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    op.create_index(
        "idx_topic_cards_resummarize_candidates",
        "topic_cards",
        ["new_items_since_last_summary"],
        postgresql_where=sa.text("new_items_since_last_summary > 0"),
    )

    op.execute(
        sa.text(r"""
            UPDATE topic_cards
            SET last_summarized_at = updated_at::timestamptz
            WHERE last_summarized_at IS NULL
              AND updated_at IS NOT NULL
              AND updated_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'
        """)
    )
    op.execute(
        sa.text("""
            UPDATE topic_cards
            SET last_summarized_at = NOW()
            WHERE last_summarized_at IS NULL
        """)
    )

    op.create_table(
        "topic_card_versions",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False),
            primary_key=True,
        ),
        sa.Column(
            "topic_id",
            sa.Text(),
            sa.ForeignKey("topic_cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("scope_in_json", sa.Text(), nullable=False),
        sa.Column("scope_out_json", sa.Text(), nullable=False),
        sa.Column("supporting_items_count_at_time", sa.Integer(), nullable=False),
        sa.Column("llm_provider", sa.String(50), nullable=True),
        sa.Column("llm_model", sa.String(200), nullable=True),
        sa.Column("prompt_version", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("topic_id", "version_no", name="uq_topic_card_versions_topic_version"),
    )
    op.create_index(
        "idx_topic_card_versions_topic_created",
        "topic_card_versions",
        ["topic_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_topic_card_versions_topic_created",
        table_name="topic_card_versions",
    )
    op.drop_table("topic_card_versions")
    op.drop_index(
        "idx_topic_cards_resummarize_candidates",
        table_name="topic_cards",
    )
    op.drop_column("topic_cards", "new_items_since_last_summary")
    op.drop_column("topic_cards", "summary_version")
    op.drop_column("topic_cards", "last_summarized_at")
