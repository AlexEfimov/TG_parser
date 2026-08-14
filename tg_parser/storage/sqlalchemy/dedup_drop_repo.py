"""
SQLAlchemy реализация DedupDropRepo.

BUG-097 (b): журнал документов, отброшенных post-LLM дедупом, — чтобы отброшенный
документ не выбирался снова на каждом тике.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tg_parser.storage.ports import DedupDrop, DedupDropRepo


class SADedupDropRepo(DedupDropRepo):
    """
    SQLAlchemy реализация DedupDropRepo.

    Хранилище: PostgreSQL (таблица processing_dedup_drops)
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def record_drops(self, drops: list[DedupDrop], *, commit: bool = True) -> int:
        """Record dedup drops, one row per dropped ``source_ref``.

        ``ON CONFLICT DO UPDATE`` rather than ``DO NOTHING``: a ref can be
        dropped again after a ``force`` reprocess collapsed it onto a different
        canonical document, and the newer mapping is the useful one. Idempotent
        either way — the PK is ``source_ref``, so a repeat never adds a row.
        """
        if not drops:
            return 0

        query = text("""
            INSERT INTO processing_dedup_drops (
                source_ref, channel_id, canonical_source_ref,
                raw_content_hash, dropped_at
            )
            VALUES (
                :source_ref, :channel_id, :canonical_source_ref,
                :raw_content_hash, NOW()
            )
            ON CONFLICT(source_ref) DO UPDATE SET
                channel_id = excluded.channel_id,
                canonical_source_ref = excluded.canonical_source_ref,
                raw_content_hash = excluded.raw_content_hash,
                dropped_at = excluded.dropped_at
        """)

        await self.session.execute(
            query,
            [
                {
                    "source_ref": d.source_ref,
                    "channel_id": d.channel_id,
                    "canonical_source_ref": d.canonical_source_ref,
                    "raw_content_hash": d.raw_content_hash,
                }
                for d in drops
            ],
        )
        if commit:
            await self.session.commit()
        return len(drops)

    async def list_dropped_refs(self, source_refs: list[str]) -> set[str]:
        """Batched membership check (one round-trip, indexed on the PK)."""
        if not source_refs:
            return set()
        result = await self.session.execute(
            text("""
                SELECT source_ref FROM processing_dedup_drops
                WHERE source_ref = ANY(:source_refs)
            """),
            {"source_refs": list(source_refs)},
        )
        return {row.source_ref for row in result.fetchall()}

    async def get_drop(self, source_ref: str) -> dict | None:
        result = await self.session.execute(
            text("""
                SELECT source_ref, channel_id, canonical_source_ref,
                       raw_content_hash, dropped_at
                FROM processing_dedup_drops
                WHERE source_ref = :source_ref
            """),
            {"source_ref": source_ref},
        )
        row = result.fetchone()
        if row is None:
            return None
        return {
            "source_ref": row.source_ref,
            "channel_id": row.channel_id,
            "canonical_source_ref": row.canonical_source_ref,
            "raw_content_hash": row.raw_content_hash,
            "dropped_at": row.dropped_at,
        }
