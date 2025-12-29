"""
SQLite реализация RawMessageRepo.

Реализует TR-8/TR-18/TR-20: идемпотентность, snapshot, лимит payload.
"""

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tg_parser.domain.models import RawTelegramMessage
from tg_parser.storage.ports import RawMessageRepo
from tg_parser.storage.sqlite.json_utils import (
    parse_iso_datetime,
    stable_json_dumps,
    stable_json_loads,
)

# TR-20: лимит raw_payload 256KB
RAW_PAYLOAD_MAX_SIZE = 256 * 1024


class SQLiteRawMessageRepo(RawMessageRepo):
    """
    SQLite реализация RawMessageRepo.

    Хранилище: raw_storage.sqlite (таблица raw_messages)
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, message: RawTelegramMessage) -> bool:
        """
        TR-8: при конфликте не перезаписывать text/date (snapshot).
        TR-18: уникальность по source_ref.
        TR-20: лимит payload 256KB.

        Returns:
            True если запись создана, False если был конфликт.
        """
        # Сериализация raw_payload с учётом лимита
        raw_payload_json, truncated, original_size = self._serialize_payload(message.raw_payload)

        # TR-8: INSERT ... ON CONFLICT DO NOTHING (не перезаписываем snapshot)
        query = text("""
            INSERT INTO raw_messages (
                source_ref, id, message_type, channel_id, date, text,
                thread_id, parent_message_id, language,
                raw_payload_json, raw_payload_truncated, raw_payload_original_size_bytes,
                inserted_at
            )
            VALUES (
                :source_ref, :id, :message_type, :channel_id, :date, :text,
                :thread_id, :parent_message_id, :language,
                :raw_payload_json, :raw_payload_truncated, :raw_payload_original_size_bytes,
                :inserted_at
            )
            ON CONFLICT(source_ref) DO NOTHING
        """)

        result = await self.session.execute(
            query,
            {
                "source_ref": message.source_ref,
                "id": message.id,
                "message_type": message.message_type.value,
                "channel_id": message.channel_id,
                "date": message.date.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "text": message.text,
                "thread_id": message.thread_id,
                "parent_message_id": message.parent_message_id,
                "language": message.language,
                "raw_payload_json": raw_payload_json,
                "raw_payload_truncated": bool(truncated),
                "raw_payload_original_size_bytes": original_size,
                "inserted_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )

        await self.session.commit()

        # rowcount == 0 означает conflict (запись уже существовала)
        return result.rowcount > 0

    async def get_by_source_ref(self, source_ref: str) -> RawTelegramMessage | None:
        """Получить raw-сообщение по source_ref."""
        query = text("""
            SELECT source_ref, id, message_type, channel_id, date, text,
                   thread_id, parent_message_id, language, raw_payload_json
            FROM raw_messages
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
        limit: int | None = None,
    ) -> list[RawTelegramMessage]:
        """Получить raw-сообщения канала."""
        conditions = ["channel_id = :channel_id"]
        params = {"channel_id": channel_id}

        if from_date:
            conditions.append("date >= :from_date")
            params["from_date"] = from_date.strftime("%Y-%m-%dT%H:%M:%SZ")

        if to_date:
            conditions.append("date <= :to_date")
            params["to_date"] = to_date.strftime("%Y-%m-%dT%H:%M:%SZ")

        where_clause = " AND ".join(conditions)
        limit_clause = f"LIMIT {limit}" if limit else ""

        query = text(f"""
            SELECT source_ref, id, message_type, channel_id, date, text,
                   thread_id, parent_message_id, language, raw_payload_json
            FROM raw_messages
            WHERE {where_clause}
            ORDER BY date ASC
            {limit_clause}
        """)

        result = await self.session.execute(query, params)
        rows = result.fetchall()

        return [self._row_to_model(row) for row in rows]

    async def record_conflict(
        self,
        source_ref: str,
        reason: str,
        new_payload: dict | None = None,
        new_text: str | None = None,
        new_date: datetime | None = None,
    ) -> None:
        """Записать коллизию (TR-8)."""
        query = text("""
            INSERT INTO raw_conflicts (
                source_ref, observed_at, reason,
                new_payload_json, new_text, new_date
            )
            VALUES (
                :source_ref, :observed_at, :reason,
                :new_payload_json, :new_text, :new_date
            )
        """)

        await self.session.execute(
            query,
            {
                "source_ref": source_ref,
                "observed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "reason": reason,
                "new_payload_json": stable_json_dumps(new_payload) if new_payload else None,
                "new_text": new_text,
                "new_date": new_date.strftime("%Y-%m-%dT%H:%M:%SZ") if new_date else None,
            },
        )

        await self.session.commit()

    def _serialize_payload(self, payload: dict | None) -> tuple[str | None, bool, int | None]:
        """
        Сериализовать raw_payload с учётом лимита 256KB (TR-20).

        Returns:
            (payload_json, truncated, original_size_bytes)
        """
        if not payload:
            return None, False, None

        payload_json = stable_json_dumps(payload)
        original_size = len(payload_json.encode("utf-8"))

        if original_size <= RAW_PAYLOAD_MAX_SIZE:
            return payload_json, False, original_size

        # Мягкое усечение: оставляем только ключевые поля + признак truncated
        truncated_payload = {
            "truncated": True,
            "original_size_bytes": original_size,
            # Можно добавить kept_fields/summary по необходимости
        }

        return stable_json_dumps(truncated_payload), True, original_size

    def _row_to_model(self, row) -> RawTelegramMessage:
        """Преобразовать row в RawTelegramMessage."""
        raw_payload = stable_json_loads(row.raw_payload_json) if row.raw_payload_json else None

        return RawTelegramMessage(
            id=row.id,
            message_type=row.message_type,
            source_ref=row.source_ref,
            channel_id=row.channel_id,
            date=parse_iso_datetime(row.date),
            text=row.text,
            thread_id=row.thread_id,
            parent_message_id=row.parent_message_id,
            language=row.language,
            raw_payload=raw_payload,
        )
