"""
CLI команда для добавления источника (add-source).

Реализует добавление канала в ingestion_state.
"""

import structlog
from datetime import UTC, datetime

from tg_parser.storage.ports import Source

logger = structlog.get_logger(__name__)


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
    from tg_parser.services.db_context import ingestion_state_repo

    async with ingestion_state_repo() as (state_repo, _db):
        existing = await state_repo.get_source(source_id)
        if existing:
            logger.info("Source %s already exists, updating...", source_id)

        source = Source(
            source_id=source_id,
            channel_id=channel_id,
            channel_username=channel_username,
            status="active",
            include_comments=include_comments,
            batch_size=batch_size or 100,
            created_at=existing.created_at if existing else datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        await state_repo.upsert_source(source)

        logger.info(
            "Source added: %s (channel=%s, comments=%s)",
            source_id,
            channel_id,
            include_comments,
        )
