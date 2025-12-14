"""
SQLite реализация TopicCardRepo.

Реализует TR-43: идемпотентность топиков по id.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tg_parser.domain.models import Anchor, TopicCard, TopicType
from tg_parser.storage.ports import TopicCardRepo
from tg_parser.storage.sqlite.json_utils import (
    parse_iso_datetime,
    stable_json_dumps,
    stable_json_loads,
)


class SQLiteTopicCardRepo(TopicCardRepo):
    """
    SQLite реализация TopicCardRepo.

    Хранилище: processing_storage.sqlite (таблица topic_cards)
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, card: TopicCard) -> None:
        """
        TR-43: upsert/replace по id.
        TR-IF-4: id детерминирован (topic: + anchors[0].anchor_ref).
        """
        query = text("""
            INSERT INTO topic_cards (
                id, title, summary, scope_in_json, scope_out_json, type,
                anchors_json, sources_json, updated_at, tags_json,
                related_topics_json, status, metadata_json
            )
            VALUES (
                :id, :title, :summary, :scope_in_json, :scope_out_json, :type,
                :anchors_json, :sources_json, :updated_at, :tags_json,
                :related_topics_json, :status, :metadata_json
            )
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                summary = excluded.summary,
                scope_in_json = excluded.scope_in_json,
                scope_out_json = excluded.scope_out_json,
                type = excluded.type,
                anchors_json = excluded.anchors_json,
                sources_json = excluded.sources_json,
                updated_at = excluded.updated_at,
                tags_json = excluded.tags_json,
                related_topics_json = excluded.related_topics_json,
                status = excluded.status,
                metadata_json = excluded.metadata_json
        """)

        await self.session.execute(
            query,
            {
                "id": card.id,
                "title": card.title,
                "summary": card.summary,
                "scope_in_json": stable_json_dumps(card.scope_in),
                "scope_out_json": stable_json_dumps(card.scope_out),
                "type": card.type.value,
                "anchors_json": stable_json_dumps([a.model_dump() for a in card.anchors]),
                "sources_json": stable_json_dumps(card.sources),
                "updated_at": card.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "tags_json": stable_json_dumps(card.tags) if card.tags else None,
                "related_topics_json": stable_json_dumps(card.related_topics)
                if card.related_topics
                else None,
                "status": card.status,
                "metadata_json": stable_json_dumps(card.metadata) if card.metadata else None,
            },
        )

        await self.session.commit()

    async def get_by_id(self, topic_id: str) -> TopicCard | None:
        """Получить topic card по id."""
        query = text("""
            SELECT id, title, summary, scope_in_json, scope_out_json, type,
                   anchors_json, sources_json, updated_at, tags_json,
                   related_topics_json, status, metadata_json
            FROM topic_cards
            WHERE id = :topic_id
        """)

        result = await self.session.execute(query, {"topic_id": topic_id})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_model(row)

    async def list_by_channel(self, channel_id: str) -> list[TopicCard]:
        """Получить все topic cards канала."""
        # Topic card может содержать материалы из разных каналов,
        # но для MVP фильтруем по sources (список источников)
        query = text("""
            SELECT id, title, summary, scope_in_json, scope_out_json, type,
                   anchors_json, sources_json, updated_at, tags_json,
                   related_topics_json, status, metadata_json
            FROM topic_cards
            WHERE sources_json LIKE :channel_pattern
            ORDER BY updated_at DESC
        """)

        # Pattern для поиска channel_id в JSON массиве
        channel_pattern = f'%"{channel_id}"%'

        result = await self.session.execute(query, {"channel_pattern": channel_pattern})
        rows = result.fetchall()

        return [self._row_to_model(row) for row in rows]

    async def list_all(self) -> list[TopicCard]:
        """Получить все topic cards."""
        query = text("""
            SELECT id, title, summary, scope_in_json, scope_out_json, type,
                   anchors_json, sources_json, updated_at, tags_json,
                   related_topics_json, status, metadata_json
            FROM topic_cards
            ORDER BY updated_at DESC
        """)

        result = await self.session.execute(query)
        rows = result.fetchall()

        return [self._row_to_model(row) for row in rows]

    def _row_to_model(self, row) -> TopicCard:
        """Преобразовать row в TopicCard."""
        scope_in = stable_json_loads(row.scope_in_json)
        scope_out = stable_json_loads(row.scope_out_json)

        anchors_data = stable_json_loads(row.anchors_json)
        anchors = [Anchor(**a) for a in anchors_data]

        sources = stable_json_loads(row.sources_json)

        tags = stable_json_loads(row.tags_json) if row.tags_json else None
        related_topics = (
            stable_json_loads(row.related_topics_json) if row.related_topics_json else None
        )
        metadata = stable_json_loads(row.metadata_json) if row.metadata_json else None

        return TopicCard(
            id=row.id,
            title=row.title,
            summary=row.summary,
            scope_in=scope_in,
            scope_out=scope_out,
            type=TopicType(row.type),
            anchors=anchors,
            sources=sources,
            updated_at=parse_iso_datetime(row.updated_at),
            tags=tags,
            related_topics=related_topics,
            status=row.status,
            metadata=metadata,
        )
