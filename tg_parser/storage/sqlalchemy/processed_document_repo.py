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
