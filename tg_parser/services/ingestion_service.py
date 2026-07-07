"""
Ingestion service.

Extracted from cli/ingest_cmd.py — owns the business logic for
collecting raw messages from Telegram channels.
"""

import contextlib
from typing import Literal

import structlog

from tg_parser.config import settings
from tg_parser.ingestion import IngestionOrchestrator
from tg_parser.ingestion.telegram import TelethonClient
from tg_parser.ingestion.telegram.telethon_client import telethon_session_lock_guard
from tg_parser.services.db_context import ingestion_repos
from tg_parser.storage.ports import IngestionStateRepo, RawMessageRepo

logger = structlog.get_logger(__name__)


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

    # BUG-070: serialize the ENTIRE Telethon client lifetime (connect -> use ->
    # disconnect) across concurrent sources. Telethon writes to the shared
    # session sqlite not only on connect() but throughout iteration
    # (entity/update-state persistence), so locking only connect() would not
    # prevent the "database is locked" collision. ``async with`` guarantees the
    # lock is released even if a source raises. Only ingestion is serialized;
    # the downstream LLM-bound processing/topicization stages run after this
    # function returns and stay parallel (scheduler_max_concurrent_sources=2).
    #
    # BUG-070 (H1): acquire with an explicit wait budget
    # (scheduler_session_lock_wait_timeout_s) so time spent WAITING for a
    # sibling's session is NOT conflated with a stuck pipeline. On budget
    # elapse the guard raises SessionLockContentionError (benign,
    # retry-next-tick) which the scheduler records as session_lock_contention
    # instead of the per-source watchdog firing as pipeline_timeout.
    async with telethon_session_lock_guard(settings.scheduler_session_lock_wait_timeout_s):
        try:
            await telegram_client.connect()

            async with contextlib.AsyncExitStack() as stack:
                if state_repo is None or raw_repo is None:
                    state_repo, raw_repo, _db = await stack.enter_async_context(ingestion_repos())

                orchestrator = IngestionOrchestrator(
                    telegram_client=telegram_client,
                    raw_repo=raw_repo,
                    state_repo=state_repo,
                    settings=settings,
                )

                logger.info("Starting ingestion: source=%s, mode=%s", source_id, mode)

                stats = await orchestrator.ingest_source(
                    source_id=source_id,
                    mode=mode,
                    limit=limit,
                )

                logger.info(
                    "Ingestion completed: posts=%s, comments=%s, duration=%.2fs",
                    stats["posts_collected"],
                    stats["comments_collected"],
                    stats["duration_seconds"],
                )

                return stats

        finally:
            await telegram_client.disconnect()
