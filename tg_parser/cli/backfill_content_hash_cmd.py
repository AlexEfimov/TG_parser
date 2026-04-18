"""F5-A Phase 3: backfill ``content_hash`` for existing processed_documents.

Idempotent — safe to re-run. Skips rows that already have ``content_hash``
set. Uses cursor-style pagination (``WHERE content_hash IS NULL LIMIT N``
in a loop) because the null-set shrinks as we write — ``OFFSET`` would
skip rows between iterations.

Usage:

    tg_parser backfill-content-hash [--channel-id ID] [--batch-size 500] [--dry-run]
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import structlog
from sqlalchemy import text

from tg_parser.config import settings
from tg_parser.domain.hashing import compute_content_hash

logger = structlog.get_logger(__name__)


@dataclass
class BackfillStats:
    total_scanned: int = 0
    total_hashed: int = 0
    total_skipped_empty_text: int = 0
    elapsed_sec: float = 0.0


async def run_backfill_content_hash(
    channel_id: str | None = None,
    batch_size: int = 500,
    dry_run: bool = False,
) -> BackfillStats:
    """Compute and persist ``content_hash`` for rows where it is NULL.

    Returns a ``BackfillStats`` summary. Does NOT delete duplicates —
    that is out of scope for Phase 3 (see F5A_PERSISTENT_KB_PLAN §3.5).
    """
    from tg_parser.storage.sqlalchemy import Database

    db = Database.from_settings(settings)
    await db.init()
    engine = db.processing_storage_engine
    stats = BackfillStats()
    started = time.perf_counter()

    # dry-run uses source_ref cursor (WHERE content_hash IS NULL stays the
    # same set since we don't write), otherwise the loop would be infinite.
    last_source_ref: str | None = None

    try:
        while True:
            where_clauses = ["content_hash IS NULL"]
            params: dict[str, object] = {"batch_size": batch_size}
            if channel_id is not None:
                where_clauses.append("channel_id = :channel_id")
                params["channel_id"] = channel_id
            if dry_run and last_source_ref is not None:
                where_clauses.append("source_ref > :last_source_ref")
                params["last_source_ref"] = last_source_ref

            where_sql = " AND ".join(where_clauses)
            select_sql = text(
                f"SELECT source_ref, channel_id, text_clean "
                f"FROM processed_documents "
                f"WHERE {where_sql} "
                f"ORDER BY source_ref ASC "
                f"LIMIT :batch_size"
            )

            async with engine.connect() as conn:
                result = await conn.execute(select_sql, params)
                rows = result.fetchall()

            if not rows:
                break

            updates: list[dict[str, str]] = []
            for row in rows:
                stats.total_scanned += 1
                if not row.text_clean or not row.text_clean.strip():
                    stats.total_skipped_empty_text += 1
                    if dry_run:
                        last_source_ref = row.source_ref
                    continue
                h = compute_content_hash(
                    row.text_clean,
                    strip_url_query=settings.dedup_strip_url_query,
                )
                updates.append({"source_ref": row.source_ref, "content_hash": h})
                if dry_run:
                    last_source_ref = row.source_ref

            if dry_run:
                stats.total_hashed += len(updates)
            elif updates:
                update_sql = text(
                    "UPDATE processed_documents SET content_hash = :content_hash "
                    "WHERE source_ref = :source_ref"
                )
                async with engine.begin() as conn:
                    for upd in updates:
                        await conn.execute(update_sql, upd)
                stats.total_hashed += len(updates)

            logger.info(
                "backfill_batch_complete",
                batch_size=len(rows),
                hashed=len(updates),
                skipped_empty=sum(1 for r in rows if not r.text_clean or not r.text_clean.strip()),
                dry_run=dry_run,
                channel_id=channel_id,
            )
    finally:
        await db.close()

    stats.elapsed_sec = round(time.perf_counter() - started, 3)
    return stats
