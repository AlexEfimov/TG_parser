"""
SQLAlchemy реализация ProcessedDocumentRepo.

Реализует TR-22/TR-43/TR-46/TR-48: идемпотентность, инкрементальность.
"""

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tg_parser.domain.json_utils import (
    stable_json_dumps,
    stable_json_loads,
)
from tg_parser.domain.models import Entity, ProcessedDocument
from tg_parser.storage.ports import ProcessedDocumentRepo


def _ensure_aware_utc(dt: datetime) -> datetime:
    """Defensive: domain layer normally produces aware UTC datetimes, but
    some legacy callers (and a few tests) still pass naive ones.  Treat
    naive as UTC so asyncpg always sees a TIMESTAMPTZ-compatible value
    after DI-10.
    """
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class SAProcessedDocumentRepo(ProcessedDocumentRepo):
    """
    SQLAlchemy реализация ProcessedDocumentRepo.

    Хранилище: PostgreSQL (таблица processed_documents)
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, doc: ProcessedDocument) -> None:
        """
        TR-22: одно актуальное состояние на source_ref.
        TR-43: upsert/replace по source_ref.
        """
        query = text("""
            INSERT INTO processed_documents (
                source_ref, id, source_message_id, channel_id, processed_at,
                text_clean, summary, topics_json, entities_json, language,
                metadata_json, content_hash
            )
            VALUES (
                :source_ref, :id, :source_message_id, :channel_id, :processed_at,
                :text_clean, :summary, :topics_json, :entities_json, :language,
                :metadata_json, :content_hash
            )
            ON CONFLICT(source_ref) DO UPDATE SET
                id = excluded.id,
                source_message_id = excluded.source_message_id,
                channel_id = excluded.channel_id,
                processed_at = excluded.processed_at,
                text_clean = excluded.text_clean,
                summary = excluded.summary,
                topics_json = excluded.topics_json,
                entities_json = excluded.entities_json,
                language = excluded.language,
                metadata_json = excluded.metadata_json,
                content_hash = excluded.content_hash
        """)

        await self.session.execute(
            query,
            {
                "source_ref": doc.source_ref,
                "id": doc.id,
                "source_message_id": doc.source_message_id,
                "channel_id": doc.channel_id,
                "processed_at": _ensure_aware_utc(doc.processed_at),
                "text_clean": doc.text_clean,
                "summary": doc.summary,
                "topics_json": stable_json_dumps(doc.topics) if doc.topics else None,
                "entities_json": stable_json_dumps([e.model_dump() for e in doc.entities])
                if doc.entities
                else None,
                "language": doc.language,
                "metadata_json": stable_json_dumps(doc.metadata) if doc.metadata else None,
                "content_hash": doc.content_hash,
            },
        )

        await self.session.commit()

    async def upsert_batch(self, docs: list[ProcessedDocument]) -> int:
        """Batch upsert with a single COMMIT. Returns count of upserted rows."""
        if not docs:
            return 0

        query = text("""
            INSERT INTO processed_documents (
                source_ref, id, source_message_id, channel_id, processed_at,
                text_clean, summary, topics_json, entities_json, language,
                metadata_json, content_hash
            )
            VALUES (
                :source_ref, :id, :source_message_id, :channel_id, :processed_at,
                :text_clean, :summary, :topics_json, :entities_json, :language,
                :metadata_json, :content_hash
            )
            ON CONFLICT(source_ref) DO UPDATE SET
                id = excluded.id,
                source_message_id = excluded.source_message_id,
                channel_id = excluded.channel_id,
                processed_at = excluded.processed_at,
                text_clean = excluded.text_clean,
                summary = excluded.summary,
                topics_json = excluded.topics_json,
                entities_json = excluded.entities_json,
                language = excluded.language,
                metadata_json = excluded.metadata_json,
                content_hash = excluded.content_hash
        """)

        for doc in docs:
            await self.session.execute(
                query,
                {
                    "source_ref": doc.source_ref,
                    "id": doc.id,
                    "source_message_id": doc.source_message_id,
                    "channel_id": doc.channel_id,
                    "processed_at": _ensure_aware_utc(doc.processed_at),
                    "text_clean": doc.text_clean,
                    "summary": doc.summary,
                    "topics_json": stable_json_dumps(doc.topics) if doc.topics else None,
                    "entities_json": stable_json_dumps([e.model_dump() for e in doc.entities])
                    if doc.entities
                    else None,
                    "language": doc.language,
                    "metadata_json": stable_json_dumps(doc.metadata) if doc.metadata else None,
                    "content_hash": doc.content_hash,
                },
            )

        await self.session.commit()
        return len(docs)

    async def get_by_source_ref(self, source_ref: str) -> ProcessedDocument | None:
        """Получить processed document по source_ref."""
        query = text("""
            SELECT source_ref, id, source_message_id, channel_id, processed_at,
                   text_clean, summary, topics_json, entities_json, language,
                   metadata_json, content_hash
            FROM processed_documents
            WHERE source_ref = :source_ref
        """)

        result = await self.session.execute(query, {"source_ref": source_ref})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_model(row)

    async def get_by_source_refs(self, source_refs: list[str]) -> dict[str, ProcessedDocument]:
        if not source_refs:
            return {}
        query = text("""
            SELECT source_ref, id, source_message_id, channel_id, processed_at,
                   text_clean, summary, topics_json, entities_json, language,
                   metadata_json, content_hash
            FROM processed_documents
            WHERE source_ref = ANY(:refs)
        """)
        result = await self.session.execute(query, {"refs": source_refs})
        rows = result.fetchall()
        return {row.source_ref: self._row_to_model(row) for row in rows}

    async def list_by_channel(
        self,
        channel_id: str,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[ProcessedDocument]:
        """Получить processed documents канала."""
        conditions = ["channel_id = :channel_id"]
        params: dict = {"channel_id": channel_id}

        if from_date:
            conditions.append("processed_at >= :from_date")
            params["from_date"] = _ensure_aware_utc(from_date)

        if to_date:
            conditions.append("processed_at <= :to_date")
            params["to_date"] = _ensure_aware_utc(to_date)

        where_clause = " AND ".join(conditions)

        query = text(f"""
            SELECT source_ref, id, source_message_id, channel_id, processed_at,
                   text_clean, summary, topics_json, entities_json, language,
                   metadata_json, content_hash
            FROM processed_documents
            WHERE {where_clause}
            ORDER BY source_ref ASC
        """)

        result = await self.session.execute(query, params)
        rows = result.fetchall()

        return [self._row_to_model(row) for row in rows]

    async def exists(self, source_ref: str) -> bool:
        """
        TR-48: проверить наличие processed document для инкрементальности.
        """
        query = text("""
            SELECT 1 FROM processed_documents WHERE source_ref = :source_ref
        """)

        result = await self.session.execute(query, {"source_ref": source_ref})
        return result.fetchone() is not None

    async def list_all(
        self,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int | None = None,
    ) -> list["ProcessedDocument"]:
        """
        Получить все processed documents (для экспорта всех каналов).

        Args:
            from_date: Фильтр по дате "от" (опционально)
            to_date: Фильтр по дате "до" (опционально)
            limit: Максимальное количество документов (опционально)

        Returns:
            Список ProcessedDocument
        """
        conditions = []
        params: dict = {}

        if from_date:
            conditions.append("processed_at >= :from_date")
            params["from_date"] = _ensure_aware_utc(from_date)

        if to_date:
            conditions.append("processed_at <= :to_date")
            params["to_date"] = _ensure_aware_utc(to_date)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        limit_clause = f"LIMIT {limit}" if limit else ""

        query = text(f"""
            SELECT source_ref, id, source_message_id, channel_id, processed_at,
                   text_clean, summary, topics_json, entities_json, language,
                   metadata_json, content_hash
            FROM processed_documents
            WHERE {where_clause}
            ORDER BY source_ref ASC
            {limit_clause}
        """)

        result = await self.session.execute(query, params)
        rows = result.fetchall()

        return [self._row_to_model(row) for row in rows]

    async def count_by_channel(self, channel_id: str) -> int:
        result = await self.session.execute(
            text("SELECT COUNT(*) FROM processed_documents WHERE channel_id = :channel_id"),
            {"channel_id": channel_id},
        )
        return result.scalar() or 0

    async def list_source_refs_by_channel(self, channel_id: str) -> list[str]:
        result = await self.session.execute(
            text("SELECT source_ref FROM processed_documents WHERE channel_id = :channel_id"),
            {"channel_id": channel_id},
        )
        return [row.source_ref for row in result.fetchall()]

    async def count_all_grouped_by_channel(self) -> dict[str, int]:
        """Return ``{channel_id: processed_document_count}`` for all channels in one query.

        BUG-008 H1: batched replacement for the per-channel ``count_by_channel``
        fan-out. Uses the existing ``processed_documents_channel_idx`` btree for
        the ``GROUP BY``. Channels with no processed docs are absent (default 0).
        """
        result = await self.session.execute(
            text("SELECT channel_id, COUNT(*) AS cnt FROM processed_documents GROUP BY channel_id")
        )
        return {row.channel_id: row.cnt for row in result.fetchall()}

    async def coverage_counts_by_channel(self) -> dict[str, int]:
        """Return ``{channel_id: covered_document_count}`` for all channels in one query.

        BUG-008 H1: batched, set-based replacement for the per-channel
        ``list_source_refs_by_channel`` + ``topic_bundle_repo.list_by_channel`` +
        Python ``_compute_coverage`` fan-out (which loaded every source-ref onto
        the event loop and ran a CPU-bound set-intersection per channel).

        Behavior-preserving semantics (matches the old per-channel path):
        a processed document ``(channel_id=C, source_ref=S)`` counts as *covered*
        iff ``S`` appears as a bundle item ``source_ref`` in some **active** bundle
        (``time_from IS NULL AND time_to IS NULL``) that is EITHER associated with
        channel ``C`` (``C`` in ``channels_json``) OR has ``channels_json IS NULL``
        (channel-agnostic bundles count for every channel — mirrors the old
        ``channels_json LIKE :pattern OR channels_json IS NULL`` filter).

        The leading-wildcard ``LIKE`` on the un-indexed ``Text`` JSON column is
        eliminated: ``channels_json`` / ``items_json`` are parsed once via
        ``jsonb`` array functions and aggregated set-wise in the DB.

        BUG-098 (b) / BUG-066 (2): a correlated ``EXISTS`` over the exploded
        CTE rescanned every bundle item once per processed document (prod
        2026-08-16: ~10 ms × 45 783 docs, timeout on every call). Distinct
        ``(channel_id, source_ref)`` pairs are materialized and hash-joined
        to ``processed_documents``; semantics above are unchanged.
        """
        query = text("""
            WITH named_refs AS MATERIALIZED (
                SELECT DISTINCT
                       ch.channel AS channel_id,
                       (item ->> 'source_ref') AS source_ref
                FROM topic_bundles ab
                CROSS JOIN LATERAL jsonb_array_elements(ab.items_json::jsonb) AS item
                CROSS JOIN LATERAL
                    jsonb_array_elements_text(ab.channels_json::jsonb) AS ch(channel)
                WHERE ab.time_from IS NULL AND ab.time_to IS NULL
                  AND ab.channels_json IS NOT NULL
            ),
            null_refs AS MATERIALIZED (
                SELECT DISTINCT (item ->> 'source_ref') AS source_ref
                FROM topic_bundles ab
                CROSS JOIN LATERAL jsonb_array_elements(ab.items_json::jsonb) AS item
                WHERE ab.time_from IS NULL AND ab.time_to IS NULL
                  AND ab.channels_json IS NULL
            )
            SELECT pd.channel_id AS channel_id,
                   COUNT(DISTINCT pd.source_ref) AS covered
            FROM processed_documents pd
            LEFT JOIN named_refs n
              ON n.channel_id = pd.channel_id
             AND n.source_ref = pd.source_ref
            LEFT JOIN null_refs nr
              ON nr.source_ref = pd.source_ref
            WHERE n.source_ref IS NOT NULL
               OR nr.source_ref IS NOT NULL
            GROUP BY pd.channel_id
        """)
        result = await self.session.execute(query)
        return {row.channel_id: row.covered for row in result.fetchall()}

    async def find_by_content_hash(
        self,
        channel_id: str,
        content_hash: str,
    ) -> ProcessedDocument | None:
        """F5-A Phase 3: look up existing document by (channel_id, content_hash).

        Uses partial composite index ``idx_pd_channel_content_hash``.
        Returns ``None`` if no match.  Never matches NULL content_hash rows
        (partial index predicate + explicit equality).
        """
        query = text("""
            SELECT source_ref, id, source_message_id, channel_id, processed_at,
                   text_clean, summary, topics_json, entities_json, language,
                   metadata_json, content_hash
            FROM processed_documents
            WHERE channel_id = :channel_id AND content_hash = :content_hash
            LIMIT 1
        """)
        result = await self.session.execute(
            query,
            {"channel_id": channel_id, "content_hash": content_hash},
        )
        row = result.fetchone()
        return self._row_to_model(row) if row else None

    async def find_by_content_hashes(
        self,
        channel_id: str,
        content_hashes: list[str],
    ) -> dict[str, ProcessedDocument]:
        """S3 (O-8): batched ``find_by_content_hash``.

        One query (``content_hash = ANY(:hashes)``) using the same partial
        composite index as the singular lookup. Returns ``{content_hash: doc}``;
        if several rows share a hash, the earliest (``processed_at``) wins so the
        result is deterministic and prefers the original document.
        """
        if not content_hashes:
            return {}
        query = text("""
            SELECT source_ref, id, source_message_id, channel_id, processed_at,
                   text_clean, summary, topics_json, entities_json, language,
                   metadata_json, content_hash
            FROM processed_documents
            WHERE channel_id = :channel_id AND content_hash = ANY(:hashes)
            ORDER BY processed_at ASC, source_ref ASC
        """)
        result = await self.session.execute(
            query,
            {"channel_id": channel_id, "hashes": list(content_hashes)},
        )
        rows = result.fetchall()
        out: dict[str, ProcessedDocument] = {}
        for row in rows:
            key = getattr(row, "content_hash", None)
            if isinstance(key, str):
                key = key.strip() or None
            if key is not None and key not in out:
                out[key] = self._row_to_model(row)
        return out

    async def find_by_raw_content_hashes(
        self,
        channel_id: str,
        raw_hashes: list[str],
    ) -> dict[str, ProcessedDocument]:
        """S3 (O-2): pre-LLM cross-tick dedup lookup by raw-text hash.

        Matches on ``metadata['raw_content_hash']`` (written pre-LLM in the
        processing pipeline). ``metadata_json`` is an unindexed TEXT column, so
        this is a per-channel scan (PostgreSQL) — no schema/index change is made
        in S3 (WORKFLOW §7). The ``channel_id`` equality uses
        ``processed_documents_channel_idx`` to bound the scan to the channel's
        rows. Returns ``{raw_content_hash: doc}``; earliest ``processed_at`` wins
        per hash (prefers the original).

        Matching is a **total** ``LIKE`` text prefilter, NOT a ``metadata_json::
        jsonb`` cast: casting every row in the channel scan would make a single
        malformed/legacy ``metadata_json`` (empty string, truncated text, any
        non-JSON payload) abort the whole query and fail the processing tick.
        ``LIKE`` never errors. It is safe because ``metadata_json`` is always
        written by :func:`stable_json_dumps` (``sort_keys`` + compact
        ``separators=(",", ":")``), so the field serialises verbatim as
        ``"raw_content_hash":"<hash>"``; the hashes are SHA-256 hex (no ``%``/
        ``_`` LIKE metacharacters) and the key literal makes cross-key false
        positives impossible. The exact hash is re-verified in Python from the
        parsed metadata below, so a LIKE over-match cannot leak a wrong row.
        """
        if not raw_hashes:
            return {}
        wanted = set(raw_hashes)
        patterns = [f'%"raw_content_hash":"{h}"%' for h in wanted]
        query = text("""
            SELECT source_ref, id, source_message_id, channel_id, processed_at,
                   text_clean, summary, topics_json, entities_json, language,
                   metadata_json, content_hash
            FROM processed_documents
            WHERE channel_id = :channel_id
              AND metadata_json IS NOT NULL
              AND metadata_json LIKE ANY(:patterns)
            ORDER BY processed_at ASC, source_ref ASC
        """)
        result = await self.session.execute(
            query,
            {"channel_id": channel_id, "patterns": patterns},
        )
        rows = result.fetchall()
        out: dict[str, ProcessedDocument] = {}
        for row in rows:
            doc = self._row_to_model(row)
            key = (doc.metadata or {}).get("raw_content_hash")
            if key in wanted and key not in out:
                out[key] = doc
        return out

    async def delete_by_channel(self, channel_id: str) -> int:
        result = await self.session.execute(
            text("DELETE FROM processed_documents WHERE channel_id = :channel_id"),
            {"channel_id": channel_id},
        )
        await self.session.commit()
        return result.rowcount

    def _row_to_model(self, row) -> ProcessedDocument:
        """Преобразовать row в ProcessedDocument."""
        topics = stable_json_loads(row.topics_json) if row.topics_json else []

        entities_data = stable_json_loads(row.entities_json) if row.entities_json else []
        entities = [Entity(**e) for e in entities_data]

        metadata = stable_json_loads(row.metadata_json) if row.metadata_json else None

        content_hash = getattr(row, "content_hash", None)
        if isinstance(content_hash, str):
            content_hash = content_hash.strip() or None

        return ProcessedDocument(
            id=row.id,
            source_ref=row.source_ref,
            source_message_id=row.source_message_id,
            channel_id=row.channel_id,
            processed_at=row.processed_at,
            text_clean=row.text_clean,
            summary=row.summary,
            topics=topics,
            entities=entities,
            language=row.language,
            metadata=metadata,
            content_hash=content_hash,
        )
