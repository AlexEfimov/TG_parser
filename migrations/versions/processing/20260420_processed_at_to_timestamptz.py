"""convert processed_documents.processed_at VARCHAR -> TIMESTAMPTZ

Revision ID: c9d8e7f6a5b4
Revises: b8e2f7c1d9a3
Create Date: 2026-04-20

DI-10 (Sprint A.4, Session 52):

Initial migration ``f40d85317f03`` declared ``processed_at`` as
``sa.String()``.  Writers (`processed_document_repo.py`) always serialise
the column with ``strftime("%Y-%m-%dT%H:%M:%SZ")`` — second-precision
canonical UTC ISO-8601 — so the on-disk values are losslessly castable to
``TIMESTAMPTZ``.

Why migrate now:

* Symmetry with ``digest_subscriptions.last_digest_cursor`` which is
  already ``TIMESTAMPTZ``.  The current Python-side ``_to_utc()`` dance
  (``digest_service.py``) becomes a no-op when both sides are aware.
* Native SQL date arithmetic for F7 / freshness analytics
  (``WHERE processed_at > now() - interval '24 hours'``) instead of
  string-comparison workarounds.
* Removes the fragile invariant that all writers must produce **exactly**
  ``"%Y-%m-%dT%H:%M:%SZ"`` — any microsecond/offset variation today
  silently breaks lex-sort and SQL filters.
* Enables Alembic ``target_metadata`` (DI-1) drift detection for the
  column type without needing a sentinel exclusion.

The conversion is idempotent: the ``DO $$`` block only ALTERs when the
current type is still ``character varying`` / ``text``, so re-running on
an already-migrated database is a no-op.

The btree index ``processed_documents_processed_at_idx`` is preserved
automatically by PostgreSQL across ``ALTER COLUMN ... TYPE`` (rebuilt
in-place), so no explicit DROP/CREATE is needed.

The ``downgrade()`` reproduces the canonical writer format
(``YYYY-MM-DDTHH24:MI:SSZ``) so a round-trip
``upgrade -> downgrade -> upgrade`` is information-preserving.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9d8e7f6a5b4"
down_revision: str | None = "b8e2f7c1d9a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text("""
            DO $$
            BEGIN
                IF (
                    SELECT data_type FROM information_schema.columns
                    WHERE table_name = 'processed_documents'
                      AND column_name = 'processed_at'
                ) IN ('character varying', 'text') THEN
                    ALTER TABLE processed_documents
                      ALTER COLUMN processed_at TYPE TIMESTAMPTZ
                      USING processed_at::timestamptz;
                END IF;
            END
            $$;
        """)
    )


def downgrade() -> None:
    op.execute(
        sa.text("""
            DO $$
            BEGIN
                IF (
                    SELECT data_type FROM information_schema.columns
                    WHERE table_name = 'processed_documents'
                      AND column_name = 'processed_at'
                ) = 'timestamp with time zone' THEN
                    ALTER TABLE processed_documents
                      ALTER COLUMN processed_at TYPE VARCHAR
                      USING to_char(
                          processed_at AT TIME ZONE 'UTC',
                          'YYYY-MM-DD"T"HH24:MI:SS"Z"'
                      );
                END IF;
            END
            $$;
        """)
    )
