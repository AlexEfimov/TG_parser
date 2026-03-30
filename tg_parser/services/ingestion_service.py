"""
Ingestion service.

Extracted from cli/ingest_cmd.py — owns the business logic for
collecting raw messages from Telegram channels.
"""

import contextlib
import logging
from typing import Literal

from tg_parser.config import settings
from tg_parser.ingestion import IngestionOrchestrator
from tg_parser.ingestion.telegram import TelethonClient
from tg_parser.services.db_context import ingestion_repos
from tg_parser.storage.ports import IngestionStateRepo, RawMessageRepo

logger = logging.getLogger(__name__)


async def run_ingestion(
    source_id: str,
    mode: Literal["snapshot", "incremental"] = "incremental",
    limit: int | None = None,
    *,
    state_repo: IngestionStateRepo | None = None,
    raw_repo: RawMessageRepo | None = None,
) -> dict[str, int]:
    """
    Run ingestion for a source.

    Args:
        source_id: Source identifier
        mode: Collection mode (snapshot or incremental)
        limit: Message limit (for debugging)
        state_repo: Optional DI for IngestionStateRepo
        raw_repo: Optional DI for RawMessageRepo

    Returns:
        Statistics (posts_collected, comments_collected, errors, duration_seconds)

    Raises:
        NonRetryableError: if source is unavailable or invalid
    """
    telegram_client = TelethonClient(settings)

    try:
        await telegram_client.connect()

        async with contextlib.AsyncExitStack() as stack:
            if state_repo is None or raw_repo is None:
                state_repo, raw_repo, _db = await stack.enter_async_context(
                    ingestion_repos()
                )

            orchestrator = IngestionOrchestrator(
                telegram_client=telegram_client,
                raw_repo=raw_repo,
                state_repo=state_repo,
                settings=settings,
            )

            logger.info(f"Starting ingestion: source={source_id}, mode={mode}")

            stats = await orchestrator.ingest_source(
                source_id=source_id,
                mode=mode,
                limit=limit,
            )

            logger.info(
                f"Ingestion completed: posts={stats['posts_collected']}, "
                f"comments={stats['comments_collected']}, "
                f"duration={stats['duration_seconds']:.2f}s"
            )

            return stats

    finally:
        await telegram_client.disconnect()
