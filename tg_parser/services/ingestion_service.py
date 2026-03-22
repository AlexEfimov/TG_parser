"""
Ingestion service.

Extracted from cli/ingest_cmd.py — owns the business logic for
collecting raw messages from Telegram channels.
"""

import logging

from tg_parser.config import settings
from tg_parser.ingestion import IngestionOrchestrator
from tg_parser.ingestion.telegram import TelethonClient
from tg_parser.storage.sqlalchemy import (
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
    Run ingestion for a source.

    Args:
        source_id: Source identifier
        mode: Collection mode (snapshot or incremental)
        limit: Message limit (for debugging)

    Returns:
        Statistics (posts_collected, comments_collected, errors, duration_seconds)

    Raises:
        NonRetryableError: if source is unavailable or invalid
    """
    db = Database.from_settings(settings)
    await db.init()

    telegram_client = TelethonClient(settings)

    try:
        await telegram_client.connect()

        state_session = db.ingestion_state_session()
        raw_session = db.raw_storage_session()

        try:
            state_repo = SQLiteIngestionStateRepo(state_session)
            raw_repo = SQLiteRawMessageRepo(raw_session)

            orchestrator = IngestionOrchestrator(
                telegram_client=telegram_client,
                raw_repo=raw_repo,
                state_repo=state_repo,
                settings=settings,
            )

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
        await telegram_client.disconnect()
        await db.close()
