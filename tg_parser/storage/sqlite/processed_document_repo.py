"""
SQLite реализация ProcessedDocumentRepo.

Реализует TR-22/TR-43/TR-46/TR-48: идемпотентность, инкрементальность.
"""

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tg_parser.domain.models import Entity, ProcessedDocument
from tg_parser.storage.ports import ProcessedDocumentRepo
from tg_parser.storage.sqlite.json_utils import (
    parse_iso_datetime,
    stable_json_dumps,
    stable_json_loads,
)


class SQLiteProcessedDocumentRepo(ProcessedDocumentRepo):
    """
    SQLite реализация ProcessedDocumentRepo.

    Хранилище: processing_storage.sqlite (таблица processed_documents)
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
                text_clean, summary, topics_json, entities_json, language, metadata_json
            )
            VALUES (
                :source_ref, :id, :source_message_id, :channel_id, :processed_at,
                :text_clean, :summary, :topics_json, :entities_json, :language, :metadata_json
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
                metadata_json = excluded.metadata_json
        """)

        await self.session.execute(
            query,
            {
                "source_ref": doc.source_ref,
                "id": doc.id,
                "source_message_id": doc.source_message_id,
                "channel_id": doc.channel_id,
                "processed_at": doc.processed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "text_clean": doc.text_clean,
                "summary": doc.summary,
                "topics_json": stable_json_dumps(doc.topics) if doc.topics else None,
                "entities_json": stable_json_dumps([e.model_dump() for e in doc.entities])
                if doc.entities
                else None,
                "language": doc.language,
                "metadata_json": stable_json_dumps(doc.metadata) if doc.metadata else None,
            },
        )

        await self.session.commit()

    async def get_by_source_ref(self, source_ref: str) -> ProcessedDocument | None:
        """Получить processed document по source_ref."""
        query = text("""
            SELECT source_ref, id, source_message_id, channel_id, processed_at,
                   text_clean, summary, topics_json, entities_json, language, metadata_json
            FROM processed_documents
            WHERE source_ref = :source_ref
        """)

        result = await self.session.execute(query, {"source_ref": source_ref})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_model(row)

    async def list_by_channel(
        self,
        channel_id: str,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[ProcessedDocument]:
        """Получить processed documents канала."""
        conditions = ["channel_id = :channel_id"]
        params = {"channel_id": channel_id}

        if from_date:
            conditions.append("processed_at >= :from_date")
            params["from_date"] = from_date.strftime("%Y-%m-%dT%H:%M:%SZ")

        if to_date:
            conditions.append("processed_at <= :to_date")
            params["to_date"] = to_date.strftime("%Y-%m-%dT%H:%M:%SZ")

        where_clause = " AND ".join(conditions)

        query = text(f"""
            SELECT source_ref, id, source_message_id, channel_id, processed_at,
                   text_clean, summary, topics_json, entities_json, language, metadata_json
            FROM processed_documents
            WHERE {where_clause}
            ORDER BY processed_at ASC
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

    def _row_to_model(self, row) -> ProcessedDocument:
        """Преобразовать row в ProcessedDocument."""
        topics = stable_json_loads(row.topics_json) if row.topics_json else []

        entities_data = stable_json_loads(row.entities_json) if row.entities_json else []
        entities = [Entity(**e) for e in entities_data]

        metadata = stable_json_loads(row.metadata_json) if row.metadata_json else None

        return ProcessedDocument(
            id=row.id,
            source_ref=row.source_ref,
            source_message_id=row.source_message_id,
            channel_id=row.channel_id,
            processed_at=parse_iso_datetime(row.processed_at),
            text_clean=row.text_clean,
            summary=row.summary,
            topics=topics,
            entities=entities,
            language=row.language,
            metadata=metadata,
        )
