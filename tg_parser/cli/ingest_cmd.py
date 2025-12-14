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
    DatabaseConfig,
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
    # Создаём database config
    config = DatabaseConfig(
        ingestion_state_path=settings.ingestion_state_db_path,
        raw_storage_path=settings.raw_storage_db_path,
        processing_storage_path=settings.processing_storage_db_path,
    )

    # Инициализируем database
    db = Database(config)
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
