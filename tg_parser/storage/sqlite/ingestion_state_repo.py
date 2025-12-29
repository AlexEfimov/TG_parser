"""
SQLite реализация IngestionStateRepo.

Реализует TR-14/TR-15: управление источниками, курсорами, попытками ingestion.
"""

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tg_parser.storage.ports import IngestionStateRepo, Source
from tg_parser.storage.sqlite.json_utils import (
    parse_iso_datetime,
    stable_json_dumps,
)


class SQLiteIngestionStateRepo(IngestionStateRepo):
    """
    SQLite реализация IngestionStateRepo.

    Хранилище: ingestion_state.sqlite (таблицы sources, comment_cursors, source_attempts)
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_source(self, source_id: str) -> Source | None:
        """Получить источник по id."""
        query = text("""
            SELECT source_id, channel_id, channel_username, status, include_comments,
                   history_from, history_to, poll_interval_seconds, batch_size,
                   last_post_id, backfill_completed_at, last_attempt_at, last_success_at,
                   fail_count, last_error, rate_limit_until, comments_unavailable,
                   created_at, updated_at
            FROM sources
            WHERE source_id = :source_id
        """)

        result = await self.session.execute(query, {"source_id": source_id})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_source(row)

    async def list_sources(self, status: str | None = None) -> list[Source]:
        """Получить список источников (опционально отфильтрованный по статусу)."""
        if status:
            query = text("""
                SELECT source_id, channel_id, channel_username, status, include_comments,
                       history_from, history_to, poll_interval_seconds, batch_size,
                       last_post_id, backfill_completed_at, last_attempt_at, last_success_at,
                       fail_count, last_error, rate_limit_until, comments_unavailable,
                       created_at, updated_at
                FROM sources
                WHERE status = :status
                ORDER BY source_id ASC
            """)
            result = await self.session.execute(query, {"status": status})
        else:
            query = text("""
                SELECT source_id, channel_id, channel_username, status, include_comments,
                       history_from, history_to, poll_interval_seconds, batch_size,
                       last_post_id, backfill_completed_at, last_attempt_at, last_success_at,
                       fail_count, last_error, rate_limit_until, comments_unavailable,
                       created_at, updated_at
                FROM sources
                ORDER BY source_id ASC
            """)
            result = await self.session.execute(query)

        rows = result.fetchall()
        return [self._row_to_source(row) for row in rows]

    async def upsert_source(self, source: Source) -> None:
        """Создать или обновить источник."""
        # TR-15: полная модель состояния источника
        query = text("""
            INSERT INTO sources (
                source_id, channel_id, channel_username, status, include_comments,
                history_from, history_to, poll_interval_seconds, batch_size,
                last_post_id, backfill_completed_at, last_attempt_at, last_success_at,
                fail_count, last_error, rate_limit_until, comments_unavailable,
                created_at, updated_at
            )
            VALUES (
                :source_id, :channel_id, :channel_username, :status, :include_comments,
                :history_from, :history_to, :poll_interval_seconds, :batch_size,
                :last_post_id, :backfill_completed_at, :last_attempt_at, :last_success_at,
                :fail_count, :last_error, :rate_limit_until, :comments_unavailable,
                :created_at, :updated_at
            )
            ON CONFLICT(source_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                channel_username = excluded.channel_username,
                status = excluded.status,
                include_comments = excluded.include_comments,
                history_from = excluded.history_from,
                history_to = excluded.history_to,
                poll_interval_seconds = excluded.poll_interval_seconds,
                batch_size = excluded.batch_size,
                last_post_id = excluded.last_post_id,
                backfill_completed_at = excluded.backfill_completed_at,
                last_attempt_at = excluded.last_attempt_at,
                last_success_at = excluded.last_success_at,
                fail_count = excluded.fail_count,
                last_error = excluded.last_error,
                rate_limit_until = excluded.rate_limit_until,
                comments_unavailable = excluded.comments_unavailable,
                updated_at = excluded.updated_at
        """)

        await self.session.execute(
            query,
            {
                "source_id": source.source_id,
                "channel_id": source.channel_id,
                "channel_username": source.channel_username,
                "status": source.status,
                "include_comments": bool(source.include_comments),
                "history_from": self._format_datetime(source.history_from),
                "history_to": self._format_datetime(source.history_to),
                "poll_interval_seconds": source.poll_interval_seconds,
                "batch_size": source.batch_size,
                "last_post_id": source.last_post_id,
                "backfill_completed_at": self._format_datetime(source.backfill_completed_at),
                "last_attempt_at": self._format_datetime(source.last_attempt_at),
                "last_success_at": self._format_datetime(source.last_success_at),
                "fail_count": source.fail_count,
                "last_error": source.last_error,
                "rate_limit_until": self._format_datetime(source.rate_limit_until),
                "comments_unavailable": bool(source.comments_unavailable),
                "created_at": self._format_datetime(source.created_at),
                "updated_at": self._format_datetime(source.updated_at or datetime.now(UTC)),
            },
        )

        await self.session.commit()

    async def update_cursors(
        self,
        source_id: str,
        last_post_id: str | None = None,
        comment_cursors: dict[str, str] | None = None,
    ) -> None:
        """
        Обновить курсоры источника (TR-7, TR-10).

        TR-10: курсоры обновляются только после успешной записи raw.
        """
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Обновить last_post_id в sources
        if last_post_id is not None:
            query = text("""
                UPDATE sources
                SET last_post_id = :last_post_id, updated_at = :updated_at
                WHERE source_id = :source_id
            """)
            await self.session.execute(
                query,
                {
                    "source_id": source_id,
                    "last_post_id": last_post_id,
                    "updated_at": now,
                },
            )

        # Обновить per-thread курсоры комментариев
        if comment_cursors:
            for thread_id, last_comment_id in comment_cursors.items():
                query = text("""
                    INSERT INTO comment_cursors (
                        source_id, thread_id, last_comment_id, updated_at
                    )
                    VALUES (
                        :source_id, :thread_id, :last_comment_id, :updated_at
                    )
                    ON CONFLICT(source_id, thread_id) DO UPDATE SET
                        last_comment_id = excluded.last_comment_id,
                        updated_at = excluded.updated_at
                """)
                await self.session.execute(
                    query,
                    {
                        "source_id": source_id,
                        "thread_id": thread_id,
                        "last_comment_id": last_comment_id,
                        "updated_at": now,
                    },
                )

        await self.session.commit()

    async def get_comment_cursor(self, source_id: str, thread_id: str) -> str | None:
        """Получить last_comment_id для треда."""
        query = text("""
            SELECT last_comment_id
            FROM comment_cursors
            WHERE source_id = :source_id AND thread_id = :thread_id
        """)

        result = await self.session.execute(
            query,
            {"source_id": source_id, "thread_id": thread_id},
        )
        row = result.fetchone()

        return row.last_comment_id if row else None

    async def record_attempt(
        self,
        source_id: str,
        success: bool,
        error_class: str | None = None,
        error_message: str | None = None,
        details: dict | None = None,
    ) -> None:
        """Записать попытку ingestion (TR-11, TR-15)."""
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Записать в source_attempts
        query = text("""
            INSERT INTO source_attempts (
                source_id, attempt_at, success, error_class, error_message, details_json
            )
            VALUES (
                :source_id, :attempt_at, :success, :error_class, :error_message, :details_json
            )
        """)

        await self.session.execute(
            query,
            {
                "source_id": source_id,
                "attempt_at": now,
                "success": bool(success),
                "error_class": error_class,
                "error_message": error_message,
                "details_json": stable_json_dumps(details) if details else None,
            },
        )

        # Обновить last_attempt_at и last_success_at в sources
        if success:
            update_query = text("""
                UPDATE sources
                SET last_attempt_at = :attempt_at,
                    last_success_at = :attempt_at,
                    fail_count = 0,
                    last_error = NULL,
                    updated_at = :attempt_at
                WHERE source_id = :source_id
            """)
        else:
            # Увеличить fail_count
            update_query = text("""
                UPDATE sources
                SET last_attempt_at = :attempt_at,
                    fail_count = fail_count + 1,
                    last_error = :last_error,
                    updated_at = :attempt_at
                WHERE source_id = :source_id
            """)

        await self.session.execute(
            update_query,
            {
                "source_id": source_id,
                "attempt_at": now,
                "last_error": error_message if not success else None,
            },
        )

        await self.session.commit()

    async def get_channel_usernames(self) -> dict[str, str | None]:
        """
        Получить маппинг channel_id -> channel_username для всех источников.

        Returns:
            Dict с channel_id как ключом и channel_username как значением
        """
        query = text("""
            SELECT channel_id, channel_username
            FROM sources
        """)

        result = await self.session.execute(query)
        rows = result.fetchall()

        return {row.channel_id: row.channel_username for row in rows}

    def _row_to_source(self, row) -> Source:
        """Преобразовать row в Source."""
        return Source(
            source_id=row.source_id,
            channel_id=row.channel_id,
            channel_username=row.channel_username,
            status=row.status,
            include_comments=bool(row.include_comments),
            history_from=parse_iso_datetime(row.history_from) if row.history_from else None,
            history_to=parse_iso_datetime(row.history_to) if row.history_to else None,
            poll_interval_seconds=row.poll_interval_seconds,
            batch_size=row.batch_size,
            last_post_id=row.last_post_id,
            backfill_completed_at=(
                parse_iso_datetime(row.backfill_completed_at) if row.backfill_completed_at else None
            ),
            last_attempt_at=parse_iso_datetime(row.last_attempt_at)
            if row.last_attempt_at
            else None,
            last_success_at=parse_iso_datetime(row.last_success_at)
            if row.last_success_at
            else None,
            fail_count=row.fail_count,
            last_error=row.last_error,
            rate_limit_until=(
                parse_iso_datetime(row.rate_limit_until) if row.rate_limit_until else None
            ),
            comments_unavailable=bool(row.comments_unavailable),
            created_at=parse_iso_datetime(row.created_at),
            updated_at=parse_iso_datetime(row.updated_at),
        )

    def _format_datetime(self, dt: datetime | None) -> str | None:
        """Форматировать datetime в ISO 8601 UTC string."""
        if dt is None:
            return None
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
