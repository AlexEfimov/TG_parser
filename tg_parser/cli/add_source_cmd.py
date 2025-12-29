"""
CLI команда для добавления источника (add-source).

Реализует добавление канала в ingestion_state.
"""

import logging
from datetime import UTC, datetime

from tg_parser.config import settings
from tg_parser.storage.ports import Source
from tg_parser.storage.sqlite import (
    Database,
    SQLiteIngestionStateRepo,
)

logger = logging.getLogger(__name__)


async def run_add_source(
    source_id: str,
    channel_id: str,
    channel_username: str | None = None,
    include_comments: bool = False,
    batch_size: int | None = None,
) -> None:
    """
    Добавить источник для ingestion (TR-15).

    Args:
        source_id: Идентификатор источника (уникальный ключ)
        channel_id: ID канала в Telegram
        channel_username: Username канала (опционально)
        include_comments: Собирать комментарии (TR-5)
        batch_size: Размер батча для ingestion
    """
    # Инициализируем database (Session 24: поддержка SQLite и PostgreSQL)
    db = Database.from_settings(settings)
    await db.init()

    try:
        # Создаём session
        state_session = db.ingestion_state_session()

        try:
            # Создаём репозиторий
            state_repo = SQLiteIngestionStateRepo(state_session)

            # Проверяем существующий источник
            existing = await state_repo.get_source(source_id)
            if existing:
                logger.info(f"Source {source_id} already exists, updating...")

            # Создаём/обновляем источник
            source = Source(
                source_id=source_id,
                channel_id=channel_id,
                channel_username=channel_username,
                status="active",  # Новые источники активны
                include_comments=include_comments,
                batch_size=batch_size or 100,  # Default batch size
                created_at=existing.created_at if existing else datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

            await state_repo.upsert_source(source)

            logger.info(
                f"Source added: {source_id} (channel={channel_id}, comments={include_comments})"
            )

        finally:
            await state_session.close()

    finally:
        await db.close()
