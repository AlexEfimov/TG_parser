"""
Orchestrator для ingestion процесса.

Реализует TR-4..TR-17: координация сбора данных в режимах snapshot/incremental.
"""

import asyncio
import random
from datetime import UTC, datetime
from typing import Literal

from tg_parser.config.settings import Settings
from tg_parser.ingestion.telegram import TelethonClient
from tg_parser.storage.ports import IngestionStateRepo, RawMessageRepo, Source


class IngestionError(Exception):
    """Базовая ошибка ingestion."""

    pass


class RetryableError(IngestionError):
    """Retryable ошибка (TR-12): сетевые ошибки, rate limit, 5xx."""

    pass


class NonRetryableError(IngestionError):
    """Non-retryable ошибка (TR-12): нет доступа, неверные креды, канал недоступен."""

    pass


class IngestionOrchestrator:
    """
    Orchestrator для координации ingestion процесса.

    Реализует:
    - TR-4: snapshot vs incremental режимы
    - TR-5/TR-6: сбор постов и комментариев
    - TR-7: per-thread курсоры комментариев
    - TR-8: идемпотентность (ON CONFLICT DO NOTHING)
    - TR-10: атомарность обновления курсоров
    - TR-11..TR-17: error handling, retry logic, статусы
    """

    def __init__(
        self,
        telegram_client: TelethonClient,
        raw_repo: RawMessageRepo,
        state_repo: IngestionStateRepo,
        settings: Settings,
    ):
        """
        Инициализировать orchestrator.

        Args:
            telegram_client: Клиент для Telegram API
            raw_repo: Репозиторий raw-сообщений
            state_repo: Репозиторий состояния ingestion
            settings: Настройки приложения
        """
        self.telegram = telegram_client
        self.raw_repo = raw_repo
        self.state_repo = state_repo
        self.settings = settings

    async def ingest_source(
        self,
        source_id: str,
        mode: Literal["snapshot", "incremental"] = "incremental",
        limit: int | None = None,
    ) -> dict:
        """
        Выполнить ingestion для источника (TR-4, TR-5).

        Args:
            source_id: ID источника
            mode: Режим сбора (snapshot или incremental)
            limit: Максимальное количество сообщений (для отладки)

        Returns:
            Dict с метриками: {posts_collected, comments_collected, errors, duration}

        Raises:
            NonRetryableError: если источник недоступен или некорректен
        """
        start_time = datetime.now(UTC)
        posts_collected = 0
        comments_collected = 0
        errors = 0

        # Получаем состояние источника
        source = await self.state_repo.get_source(source_id)
        if not source:
            raise NonRetryableError(f"Source {source_id} not found")

        if source.status != "active":
            raise NonRetryableError(f"Source {source_id} is not active (status={source.status})")

        # Выполняем ingestion с retry logic (TR-12, TR-13)
        max_attempts = self.settings.ingestion_max_attempts_per_run

        for attempt in range(1, max_attempts + 1):
            try:
                # Собираем посты
                posts_count = await self._ingest_posts(source, mode, limit)
                posts_collected += posts_count

                # Собираем комментарии (если включены, TR-5)
                if source.include_comments and not source.comments_unavailable:
                    comments_count = await self._ingest_comments(source, limit)
                    comments_collected += comments_count

                # Успешная попытка
                await self.state_repo.record_attempt(
                    source_id=source_id,
                    success=True,
                )

                # Обновляем статус источника
                source.status = "active"
                source.last_success_at = datetime.now(UTC)
                await self.state_repo.upsert_source(source)

                break  # Успех, выходим из retry loop

            except RetryableError as e:
                errors += 1
                error_message = str(e)

                # TR-13: exponential backoff с jitter
                if attempt < max_attempts:
                    backoff = self.settings.ingestion_retry_backoff_base * (2 ** (attempt - 1))
                    jitter = random.uniform(0, self.settings.ingestion_retry_jitter_max * backoff)
                    await asyncio.sleep(backoff + jitter)
                    continue
                else:
                    # Исчерпаны попытки
                    await self.state_repo.record_attempt(
                        source_id=source_id,
                        success=False,
                        error_class=type(e).__name__,
                        error_message=error_message,
                    )

                    # Переводим источник в error (TR-11)
                    source.status = "error"
                    source.last_error = error_message
                    await self.state_repo.upsert_source(source)

                    raise

            except NonRetryableError as e:
                errors += 1
                error_message = str(e)

                # Не ретраим, сразу переводим в error
                await self.state_repo.record_attempt(
                    source_id=source_id,
                    success=False,
                    error_class=type(e).__name__,
                    error_message=error_message,
                )

                source.status = "error"
                source.last_error = error_message
                await self.state_repo.upsert_source(source)

                raise

        duration = (datetime.now(UTC) - start_time).total_seconds()

        return {
            "posts_collected": posts_collected,
            "comments_collected": comments_collected,
            "errors": errors,
            "duration_seconds": duration,
        }

    async def _ingest_posts(
        self,
        source: Source,
        mode: Literal["snapshot", "incremental"],
        limit: int | None = None,
    ) -> int:
        """
        Собрать посты из канала (TR-4).

        Args:
            source: Состояние источника
            mode: Режим сбора
            limit: Лимит сообщений

        Returns:
            Количество собранных постов
        """
        collected = 0

        # Определяем min_id для incremental mode (TR-7)
        min_id = None
        if mode == "incremental" and source.last_post_id:
            min_id = int(source.last_post_id)

        # Собираем посты
        last_post_id = source.last_post_id

        try:
            async for raw_msg in self.telegram.get_messages(
                channel_id=source.channel_id,
                limit=limit,
                min_id=min_id,
            ):
                # Сохраняем в raw storage (TR-8: идемпотентность)
                created = await self.raw_repo.upsert(raw_msg)

                if created:
                    collected += 1

                # Отслеживаем последний ID для курсора
                last_post_id = raw_msg.id

        except Exception as e:
            # Классифицируем ошибку (TR-12)
            if self._is_retryable_error(e):
                raise RetryableError(f"Failed to fetch posts: {e}") from e
            else:
                raise NonRetryableError(f"Channel not accessible: {e}") from e

        # TR-10: обновляем курсор после успешной записи
        if last_post_id:
            await self.state_repo.update_cursors(
                source_id=source.source_id,
                last_post_id=last_post_id,
            )
            source.last_post_id = last_post_id

        return collected

    async def _ingest_comments(
        self,
        source: Source,
        limit: int | None = None,
    ) -> int:
        """
        Собрать комментарии для постов (TR-6, TR-7).

        Args:
            source: Состояние источника
            limit: Лимит комментариев на пост

        Returns:
            Количество собранных комментариев
        """
        collected = 0

        # Получаем посты канала для сбора комментариев
        # (в реальности нужно оптимизировать: не все посты имеют комментарии)
        raw_messages = await self.raw_repo.list_by_channel(
            channel_id=source.channel_id,
            limit=100,  # Последние N постов
        )

        comment_cursors = {}

        for raw_msg in raw_messages:
            thread_id = raw_msg.thread_id
            if not thread_id:
                continue

            # Получаем текущий курсор для треда (TR-7)
            min_id = None
            last_comment_id = await self.state_repo.get_comment_cursor(
                source_id=source.source_id,
                thread_id=thread_id,
            )
            if last_comment_id:
                min_id = int(last_comment_id)

            # Собираем комментарии к посту
            last_comment_id_for_thread = last_comment_id

            try:
                async for comment in self.telegram.get_comments(
                    channel_id=source.channel_id,
                    post_id=int(raw_msg.id),
                    limit=limit,
                    min_id=min_id,
                ):
                    # Сохраняем комментарий (TR-8: идемпотентность)
                    created = await self.raw_repo.upsert(comment)

                    if created:
                        collected += 1

                    # Отслеживаем последний комментарий в треде
                    last_comment_id_for_thread = comment.id

            except Exception as e:
                # Если комментарии недоступны для канала, отмечаем это
                if "comments are disabled" in str(e).lower():
                    source.comments_unavailable = True
                    await self.state_repo.upsert_source(source)
                    return collected
                else:
                    # Другие ошибки логируем но продолжаем
                    continue

            # Сохраняем курсор для треда
            if last_comment_id_for_thread:
                comment_cursors[thread_id] = last_comment_id_for_thread

        # TR-10: обновляем per-thread курсоры после успешной записи
        if comment_cursors:
            await self.state_repo.update_cursors(
                source_id=source.source_id,
                comment_cursors=comment_cursors,
            )

        return collected

    def _is_retryable_error(self, error: Exception) -> bool:
        """
        Определить является ли ошибка retryable (TR-12).

        Args:
            error: Exception

        Returns:
            True если ошибка retryable (сетевая, rate limit, 5xx)
        """
        error_str = str(error).lower()

        # Retryable: сетевые ошибки
        retryable_keywords = [
            "timeout",
            "connection",
            "network",
            "rate limit",
            "flood",
            "server error",
            "503",
            "502",
            "500",
        ]

        for keyword in retryable_keywords:
            if keyword in error_str:
                return True

        # Non-retryable: доступ, креды, не найден
        non_retryable_keywords = [
            "not found",
            "access denied",
            "forbidden",
            "unauthorized",
            "invalid",
            "credential",
        ]

        for keyword in non_retryable_keywords:
            if keyword in error_str:
                return False

        # По умолчанию считаем retryable (осторожный подход)
        return True
