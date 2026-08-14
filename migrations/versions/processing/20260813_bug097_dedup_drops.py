"""add processing_dedup_drops (BUG-097 b — dropped duplicates stop being re-paid)

Revision ID: e7f8a9b0c1d2
Revises: a4b5c6d7e8f9
Create Date: 2026-08-13

A duplicate detected AFTER the LLM call is discarded WITHOUT writing a
``processed_documents`` row. Work is selected with
``NOT EXISTS (processed_documents)`` (``raw_message_repo.list_unprocessed_by_
channel``, BUG-069 / B2), so the next tick sees the same message as unprocessed
and pays for the same summary again — indefinitely. Prod, 41 h window: 1 108
documents and 1 495 164 tokens on attempts that ended in a drop (≈99 % of the
processing stage) against 10 documents and 20 416 tokens of real work; in the
log window every one of 27 unique documents appeared on all three ticks and none
appeared only once.

This table records the drop so the selection window can anti-join it, exactly as
it already anti-joins ``processing_failures`` (BUG-069 Option A). Shape follows
that sibling: ``source_ref`` PK (one row per dropped message, idempotent
re-record), ``channel_id`` indexed for per-channel reads.

Why not simply store the dropped document instead: the scheduler computes
``new_doc_refs`` as a bare before/after diff of ``processed_documents`` with no
provenance filter, so a document row would feed the duplicate into topicization
Phase 2 (a real LLM call) and into ``watchlist_service.check_interests``, whose
match uniqueness is ``(interest_id, source_ref)`` — the user would get a second
alert for text they were already alerted about. The marker keeps the drop out of
that path entirely.

``canonical_source_ref`` is the document the message collapsed into — the same
mapping ``metadata['dedup_of']`` carries on a pre-LLM mirror row. NOT a foreign
key: the canonical row may be deleted by a channel purge or re-topicization
while the drop remains a true statement about the past, and a cascade would
silently re-open the cost loop.

``raw_content_hash`` is the hash of the RAW text, nullable because media-only and
empty messages have none by construction (``_compute_raw_hash`` returns ``None``);
those never cost an LLM call anyway. Stored so a LATER message carrying the same
raw text can be recognised before the LLM call, and indexed for that lookup.

No backfill: the 27 documents currently in the loop are marked by the first tick
after deploy (that tick pays for them one last time), which is also the signal
the fix works — ``deduplicated_count`` peaks once and then reads zero on a stable
channel.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: str | None = "a4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "processing_dedup_drops",
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("canonical_source_ref", sa.Text(), nullable=False),
        sa.Column("raw_content_hash", sa.CHAR(64), nullable=True),
        sa.Column(
            "dropped_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("source_ref", name="processing_dedup_drops_pkey"),
    )
    op.create_index(
        "processing_dedup_drops_channel_idx",
        "processing_dedup_drops",
        ["channel_id"],
    )
    op.create_index(
        "idx_pdd_channel_raw_hash",
        "processing_dedup_drops",
        ["channel_id", "raw_content_hash"],
        postgresql_where=sa.text("raw_content_hash IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_pdd_channel_raw_hash", table_name="processing_dedup_drops")
    op.drop_index("processing_dedup_drops_channel_idx", table_name="processing_dedup_drops")
    op.drop_table("processing_dedup_drops")
