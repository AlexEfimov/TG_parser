"""
SQLite реализация TopicBundleRepo.

Реализует TR-43: идемпотентность подборок по topic_id (для MVP без time_range).
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tg_parser.domain.models import BundleItem, BundleItemRole, MessageType, TopicBundle
from tg_parser.storage.ports import TopicBundleRepo
from tg_parser.storage.sqlite.json_utils import (
    parse_iso_datetime,
    stable_json_dumps,
    stable_json_loads,
)


class SQLiteTopicBundleRepo(TopicBundleRepo):
    """
    SQLite реализация TopicBundleRepo.

    Хранилище: processing_storage.sqlite (таблица topic_bundles)
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, bundle: TopicBundle) -> None:
        """
        TR-43: upsert/replace по topic_id (для MVP без time_range).

        Для актуальной подборки (time_range=None) используется UNIQUE INDEX,
        который гарантирует только одну запись на topic_id.
        """
        # Для MVP time_range всегда None
        time_from = None
        time_to = None
        if bundle.time_range:
            time_from = bundle.time_range.from_.strftime("%Y-%m-%dT%H:%M:%SZ")
            time_to = bundle.time_range.to.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Для актуальных подборок (time_from=NULL, time_to=NULL):
        # Используем DELETE + INSERT вместо UPSERT, так как partial UNIQUE INDEX
        # не поддерживает ON CONFLICT в SQLite
        if time_from is None and time_to is None:
            # Удаляем существующую актуальную подборку
            delete_query = text("""
                DELETE FROM topic_bundles
                WHERE topic_id = :topic_id
                  AND time_from IS NULL
                  AND time_to IS NULL
            """)
            await self.session.execute(delete_query, {"topic_id": bundle.topic_id})

            # Вставляем новую
            insert_query = text("""
                INSERT INTO topic_bundles (
                    topic_id, updated_at, time_from, time_to,
                    items_json, channels_json, metadata_json
                )
                VALUES (
                    :topic_id, :updated_at, :time_from, :time_to,
                    :items_json, :channels_json, :metadata_json
                )
            """)

            await self.session.execute(
                insert_query,
                {
                    "topic_id": bundle.topic_id,
                    "updated_at": bundle.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "time_from": time_from,
                    "time_to": time_to,
                    "items_json": stable_json_dumps([item.model_dump() for item in bundle.items]),
                    "channels_json": stable_json_dumps(bundle.channels)
                    if bundle.channels
                    else None,
                    "metadata_json": stable_json_dumps(bundle.metadata)
                    if bundle.metadata
                    else None,
                },
            )
        else:
            # Для снапшотов с time_range: используем UPSERT
            query = text("""
                INSERT INTO topic_bundles (
                    topic_id, updated_at, time_from, time_to,
                    items_json, channels_json, metadata_json
                )
                VALUES (
                    :topic_id, :updated_at, :time_from, :time_to,
                    :items_json, :channels_json, :metadata_json
                )
                ON CONFLICT(topic_id, time_from, time_to)
                WHERE time_from IS NOT NULL AND time_to IS NOT NULL
                DO UPDATE SET
                    updated_at = excluded.updated_at,
                    items_json = excluded.items_json,
                    channels_json = excluded.channels_json,
                    metadata_json = excluded.metadata_json
            """)

            await self.session.execute(
                query,
                {
                    "topic_id": bundle.topic_id,
                    "updated_at": bundle.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "time_from": time_from,
                    "time_to": time_to,
                    "items_json": stable_json_dumps([item.model_dump() for item in bundle.items]),
                    "channels_json": stable_json_dumps(bundle.channels)
                    if bundle.channels
                    else None,
                    "metadata_json": stable_json_dumps(bundle.metadata)
                    if bundle.metadata
                    else None,
                },
            )

        await self.session.commit()

    async def get_by_topic_id(self, topic_id: str) -> TopicBundle | None:
        """
        Получить актуальную подборку по topic_id (без time_range).

        Для MVP возвращаем только актуальную подборку (time_from=NULL, time_to=NULL).
        """
        query = text("""
            SELECT topic_id, updated_at, time_from, time_to,
                   items_json, channels_json, metadata_json
            FROM topic_bundles
            WHERE topic_id = :topic_id
              AND time_from IS NULL
              AND time_to IS NULL
        """)

        result = await self.session.execute(query, {"topic_id": topic_id})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_model(row)

    async def list_by_channel(self, channel_id: str) -> list[TopicBundle]:
        """Получить все актуальные подборки канала."""
        query = text("""
            SELECT topic_id, updated_at, time_from, time_to,
                   items_json, channels_json, metadata_json
            FROM topic_bundles
            WHERE time_from IS NULL
              AND time_to IS NULL
              AND (channels_json LIKE :channel_pattern OR channels_json IS NULL)
            ORDER BY updated_at DESC
        """)

        # Pattern для поиска channel_id в JSON массиве
        channel_pattern = f'%"{channel_id}"%'

        result = await self.session.execute(query, {"channel_pattern": channel_pattern})
        rows = result.fetchall()

        return [self._row_to_model(row) for row in rows]

    async def list_all(self) -> list[TopicBundle]:
        """Получить все актуальные подборки."""
        query = text("""
            SELECT topic_id, updated_at, time_from, time_to,
                   items_json, channels_json, metadata_json
            FROM topic_bundles
            WHERE time_from IS NULL
              AND time_to IS NULL
            ORDER BY updated_at DESC
        """)

        result = await self.session.execute(query)
        rows = result.fetchall()

        return [self._row_to_model(row) for row in rows]

    def _row_to_model(self, row) -> TopicBundle:
        """Преобразовать row в TopicBundle."""
        items_data = stable_json_loads(row.items_json)
        items = [
            BundleItem(
                channel_id=item["channel_id"],
                message_id=item["message_id"],
                message_type=MessageType(item["message_type"]),
                source_ref=item["source_ref"],
                role=BundleItemRole(item["role"]),
                parent_message_id=item.get("parent_message_id"),
                thread_id=item.get("thread_id"),
                score=item.get("score"),
                justification=item.get("justification"),
            )
            for item in items_data
        ]

        channels = stable_json_loads(row.channels_json) if row.channels_json else None
        metadata = stable_json_loads(row.metadata_json) if row.metadata_json else None

        # Time range reconstruction
        time_range = None
        if row.time_from and row.time_to:
            from tg_parser.domain.models import TimeRange

            time_range = TimeRange(
                **{"from": parse_iso_datetime(row.time_from), "to": parse_iso_datetime(row.time_to)}
            )

        return TopicBundle(
            topic_id=row.topic_id,
            items=items,
            updated_at=parse_iso_datetime(row.updated_at),
            time_range=time_range,
            channels=channels,
            metadata=metadata,
        )
