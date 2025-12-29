"""
CLI команда для ingestion (ingest).

Реализует сбор сырых сообщений из Telegram каналов.
"""

import logging

from tg_parser.config import settings
from tg_parser.ingestion import IngestionOrchestrator
from tg_parser.ingestion.telegram import TelethonClient
from tg_parser.storage.sqlite import (
    Database,
    SQLiteIngestionStateRepo,
    SQLiteRawMessageRepo,
)

logger = logging.getLogger(__name__)


async def run_ingestion(
    source_id: str,
    mode: str = "incremental",
    limit: int | None = None,
) -> dict[str, int]:
    """
    Запустить ingestion для источника (TR-4..TR-17).

    Args:
        source_id: Идентификатор источника
        mode: Режим сбора (snapshot или incremental)
        limit: Лимит сообщений (для отладки)

    Returns:
        Статистика ingestion (posts_collected, comments_collected, errors, duration_seconds)

    Raises:
        NonRetryableError: если источник недоступен или некорректен
    """
    # Инициализируем database (Session 24: поддержка SQLite и PostgreSQL)
    db = Database.from_settings(settings)
    await db.init()

    # Создаём Telegram client
    telegram_client = TelethonClient(settings)

    try:
        # Подключаемся к Telegram
        await telegram_client.connect()

        # Создаём sessions
        state_session = db.ingestion_state_session()
        raw_session = db.raw_storage_session()

        try:
            # Создаём репозитории
            state_repo = SQLiteIngestionStateRepo(state_session)
            raw_repo = SQLiteRawMessageRepo(raw_session)

            # Создаём orchestrator
            orchestrator = IngestionOrchestrator(
                telegram_client=telegram_client,
                raw_repo=raw_repo,
                state_repo=state_repo,
                settings=settings,
            )

            # Запускаем ingestion
            logger.info(f"Starting ingestion: source={source_id}, mode={mode}")

            stats = await orchestrator.ingest_source(
                source_id=source_id,
                mode=mode,  # type: ignore
                limit=limit,
            )

            logger.info(
                f"Ingestion completed: posts={stats['posts_collected']}, "
                f"comments={stats['comments_collected']}, "
                f"duration={stats['duration_seconds']:.2f}s"
            )

            return stats

        finally:
            await state_session.close()
            await raw_session.close()

    finally:
        # Отключаемся от Telegram
        await telegram_client.disconnect()
        await db.close()
