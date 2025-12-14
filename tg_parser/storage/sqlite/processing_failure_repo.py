"""
SQLite реализация ProcessingFailureRepo.

Реализует TR-47: журналирование неудачной обработки сообщений.
"""

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tg_parser.storage.ports import ProcessingFailureRepo
from tg_parser.storage.sqlite.json_utils import stable_json_dumps, stable_json_loads


class SQLiteProcessingFailureRepo(ProcessingFailureRepo):
    """
    SQLite реализация ProcessingFailureRepo.

    Хранилище: processing_storage.sqlite (таблица processing_failures)
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def record_failure(
        self,
        source_ref: str,
        channel_id: str,
        attempts: int,
        error_class: str,
        error_message: str,
        error_details: dict | None = None,
    ) -> None:
        """
        Записать или обновить запись о неудачной обработке.

        TR-47: при повторных неудачах обновляем существующую запись.
        """
        query = text("""
            INSERT INTO processing_failures (
                source_ref, channel_id, attempts, last_attempt_at,
                error_class, error_message, error_details_json
            )
            VALUES (
                :source_ref, :channel_id, :attempts, :last_attempt_at,
                :error_class, :error_message, :error_details_json
            )
            ON CONFLICT(source_ref) DO UPDATE SET
                channel_id = excluded.channel_id,
                attempts = excluded.attempts,
                last_attempt_at = excluded.last_attempt_at,
                error_class = excluded.error_class,
                error_message = excluded.error_message,
                error_details_json = excluded.error_details_json
        """)

        await self.session.execute(
            query,
            {
                "source_ref": source_ref,
                "channel_id": channel_id,
                "attempts": attempts,
                "last_attempt_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "error_class": error_class,
                "error_message": error_message,
                "error_details_json": stable_json_dumps(error_details) if error_details else None,
            },
        )

        await self.session.commit()

    async def delete_failure(self, source_ref: str) -> None:
        """
        Удалить запись о неудаче при успешной обработке.

        TR-47: при успехе обработки должна исчезать запись в failures.
        """
        query = text("""
            DELETE FROM processing_failures
            WHERE source_ref = :source_ref
        """)

        await self.session.execute(query, {"source_ref": source_ref})
        await self.session.commit()

    async def list_failures(
        self,
        channel_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """
        Получить список неудачных обработок для отчётов.

        Args:
            channel_id: фильтр по каналу (опционально)
            limit: ограничение количества записей (опционально)

        Returns:
            Список dict с полями: source_ref, channel_id, attempts,
            last_attempt_at, error_class, error_message, error_details
        """
        conditions = []
        params = {}

        if channel_id:
            conditions.append("channel_id = :channel_id")
            params["channel_id"] = channel_id

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        limit_clause = f"LIMIT {limit}" if limit else ""

        query = text(f"""
            SELECT source_ref, channel_id, attempts, last_attempt_at,
                   error_class, error_message, error_details_json
            FROM processing_failures
            WHERE {where_clause}
            ORDER BY last_attempt_at DESC
            {limit_clause}
        """)

        result = await self.session.execute(query, params)
        rows = result.fetchall()

        failures = []
        for row in rows:
            error_details = (
                stable_json_loads(row.error_details_json) if row.error_details_json else None
            )

            failures.append(
                {
                    "source_ref": row.source_ref,
                    "channel_id": row.channel_id,
                    "attempts": row.attempts,
                    "last_attempt_at": row.last_attempt_at,
                    "error_class": row.error_class,
                    "error_message": row.error_message,
                    "error_details": error_details,
                }
            )

        return failures
