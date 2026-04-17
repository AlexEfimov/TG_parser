"""
Scheduler service for incremental pipeline runs.

Session 30: Automatic incremental processing — iterates over active sources
and runs the full pipeline (ingest → process → topicize → export) for each.
"""

import asyncio
import contextlib
import signal
import time
from datetime import UTC, datetime
from typing import Any

import structlog

from tg_parser.config import settings
from tg_parser.services.db_context import ingestion_and_processing_repos, ingestion_state_repo
from tg_parser.storage.ports import IngestionStateRepo, ProcessedDocumentRepo

logger = structlog.get_logger(__name__)


async def run_incremental_for_all_sources(
    output_dir: str = "./output",
    *,
    state_repo: IngestionStateRepo | None = None,
    processed_repo: ProcessedDocumentRepo | None = None,
) -> dict[str, Any]:
    """
    Run incremental pipeline for every active source.

    For each source with status='active':
      1. Run full pipeline in incremental mode
      2. Record attempt with details in source_attempts
      3. Decide whether retopicization is needed (threshold strategy)

    Errors in one source do not block others.

    Returns:
        Aggregate statistics across all sources.
    """
    from tg_parser.services.pipeline_service import run_full_pipeline

    aggregate: dict[str, Any] = {
        "sources_total": 0,
        "sources_succeeded": 0,
        "sources_failed": 0,
        "sources_skipped": 0,
        "total_new_messages": 0,
        "total_processed": 0,
        "retopicized_sources": [],
        "errors": {},
        "started_at": datetime.now(UTC).isoformat(),
        "duration_seconds": 0,
    }
    start_time = time.time()

    async with contextlib.AsyncExitStack() as stack:
        if state_repo is None or processed_repo is None:
            state_repo, processed_repo, _db = await stack.enter_async_context(
                ingestion_and_processing_repos()
            )
        sources = await state_repo.list_sources(status="active")
        aggregate["sources_total"] = len(sources)

        if not sources:
            logger.info("No active sources found — nothing to do")
            return aggregate

        max_concurrent = settings.scheduler_max_concurrent_sources
        logger.info(
            "Incremental pipeline: found %d active source(s), max_concurrent=%d",
            len(sources),
            max_concurrent,
        )

        semaphore = asyncio.Semaphore(max_concurrent)
        repo_lock = asyncio.Lock()

        async def _process_source(source):
            source_start = time.time()
            source_id = source.source_id
            channel_id = source.channel_id.lstrip("@")

            logger.info("Processing source %s (channel=%s)", source_id, channel_id)

            async with repo_lock:
                docs_before = await processed_repo.list_by_channel(channel_id)

            try:
                async with semaphore:
                    stats = await run_full_pipeline(
                        source_id=source_id,
                        output_dir=output_dir,
                        mode="incremental",
                        skip_topicize=True,
                        concurrency=settings.processing_concurrency,
                    )

                new_messages = 0
                if stats.get("ingest"):
                    new_messages = stats["ingest"].get("posts_collected", 0) + stats["ingest"].get(
                        "comments_collected", 0
                    )

                new_processed = 0
                if stats.get("process"):
                    new_processed = stats["process"].get("processed_count", 0)

                async with repo_lock:
                    aggregate["total_new_messages"] += new_messages
                    aggregate["total_processed"] += new_processed
                    aggregate["sources_succeeded"] += 1

                    await state_repo.record_attempt(
                        source_id=source_id,
                        success=True,
                        details={
                            "trigger": "scheduled",
                            "new_messages": new_messages,
                            "new_processed": new_processed,
                            "duration_seconds": round(time.time() - source_start, 2),
                            "pipeline_stats": _safe_stats(stats),
                        },
                    )

                    docs_after = await processed_repo.list_by_channel(channel_id)

                new_doc_refs = [
                    d.source_ref
                    for d in docs_after
                    if d.source_ref not in {dd.source_ref for dd in docs_before}
                ]
                if new_doc_refs:
                    logger.info(
                        "Running incremental topicization for %s (%d new docs)",
                        source_id,
                        len(new_doc_refs),
                    )
                    try:
                        from tg_parser.services.topicization_service import (
                            run_incremental_topicization,
                        )

                        incr_result = await run_incremental_topicization(
                            channel_id,
                            new_doc_refs,
                        )
                        async with repo_lock:
                            aggregate["retopicized_sources"].append(source_id)
                        logger.info(
                            "Incremental topicization for %s: "
                            "assigned=%d, unassigned=%d, "
                            "coverage %.1f%% -> %.1f%%",
                            source_id,
                            len(incr_result.assigned_keyword),
                            len(incr_result.unassignable),
                            incr_result.coverage_before,
                            incr_result.coverage_after,
                        )

                        try:
                            from tg_parser.services.embedding_service import run_topic_embedding

                            await run_topic_embedding(channel_id=channel_id, force=False)
                        except Exception as te:
                            logger.warning(
                                "Topic embedding failed for %s: %s",
                                source_id,
                                te,
                            )
                    except Exception as e:
                        logger.error(
                            "Incremental topicization failed for %s: %s",
                            source_id,
                            e,
                            exc_info=True,
                        )

                logger.info(
                    "Source %s completed: new_messages=%d, processed=%d",
                    source_id,
                    new_messages,
                    new_processed,
                )

            except Exception as exc:
                async with repo_lock:
                    aggregate["sources_failed"] += 1
                    aggregate["errors"][source_id] = str(exc)

                await _safe_record_failure(
                    state_repo,
                    source_id,
                    exc,
                    time.time() - source_start,
                )

                logger.error("Source %s failed: %s", source_id, exc, exc_info=True)

        await asyncio.gather(*[_process_source(s) for s in sources])

    aggregate["duration_seconds"] = round(time.time() - start_time, 2)
    aggregate["finished_at"] = datetime.now(UTC).isoformat()

    logger.info(
        "Incremental pipeline completed: succeeded=%d, failed=%d, duration=%.2fs",
        aggregate["sources_succeeded"],
        aggregate["sources_failed"],
        aggregate["duration_seconds"],
    )

    return aggregate


async def run_incremental_for_source(
    source_id: str,
    output_dir: str = "./output",
) -> dict[str, Any]:
    """
    Run incremental pipeline for a single source.

    Convenience wrapper for manual/CLI invocations targeting one source.
    """
    from tg_parser.services.pipeline_service import run_full_pipeline

    logger.info("Running incremental pipeline for source: %s", source_id)
    stats = await run_full_pipeline(
        source_id=source_id,
        output_dir=output_dir,
        mode="incremental",
        concurrency=settings.processing_concurrency,
    )
    return stats


async def get_scheduler_status(
    *,
    repo: IngestionStateRepo | None = None,
) -> dict[str, Any]:
    """
    Return status information about active sources and last attempts.
    """
    async with contextlib.AsyncExitStack() as stack:
        if repo is None:
            repo, _db = await stack.enter_async_context(ingestion_state_repo())
        state_repo = repo
        sources = await state_repo.list_sources()

        source_list = []
        for s in sources:
            source_list.append(
                {
                    "source_id": s.source_id,
                    "channel_id": s.channel_id,
                    "status": s.status,
                    "poll_interval_seconds": s.poll_interval_seconds
                    or settings.scheduler_default_interval,
                    "last_attempt_at": s.last_attempt_at.isoformat() if s.last_attempt_at else None,
                    "last_success_at": s.last_success_at.isoformat() if s.last_success_at else None,
                    "fail_count": s.fail_count,
                    "last_error": s.last_error,
                }
            )

        return {
            "scheduler_enabled": settings.scheduler_enabled,
            "default_interval_seconds": settings.scheduler_default_interval,
            "retopicize_threshold": settings.scheduler_retopicize_threshold,
            "sources": source_list,
        }


def run_scheduler_blocking(
    interval_seconds: int | None = None,
) -> None:
    """
    Run the scheduler in daemon/blocking mode with graceful shutdown.

    This is meant for the CLI ``tg-parser scheduler start`` command.
    It sets up an APScheduler, registers the incremental pipeline job,
    and blocks until SIGTERM/SIGINT.
    """
    asyncio.run(_run_scheduler_async(interval_seconds))


async def _run_scheduler_async(
    interval_seconds: int | None = None,
) -> None:
    """Async entry point for the scheduler daemon."""
    from tg_parser.services.background_scheduler import (
        BackgroundScheduler,
        setup_default_tasks,
    )

    interval = interval_seconds or settings.scheduler_default_interval

    scheduler = BackgroundScheduler()

    setup_default_tasks(
        scheduler,
        incremental_pipeline_interval=interval,
    )

    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _handle_signal() -> None:
        logger.info("Received shutdown signal — stopping scheduler")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    # Trigger the first run immediately
    scheduler.start()
    logger.info("Scheduler daemon started (interval=%ds). Press Ctrl+C to stop.", interval)

    # Run the pipeline once right away before the first scheduled tick
    try:
        await run_incremental_for_all_sources()
    except Exception as exc:
        logger.error("Initial incremental run failed: %s", exc, exc_info=True)

    await shutdown_event.wait()

    scheduler.shutdown(wait=True)
    logger.info("Scheduler daemon stopped")


# ---------------------------------------------------------------------------
# APScheduler task entry points
# ---------------------------------------------------------------------------


async def incremental_pipeline_task() -> dict:
    """
    Periodic task: run incremental pipeline for all active sources.

    Registered in APScheduler via ``setup_default_tasks``.
    Metric recording is handled by ``BackgroundScheduler.add_task`` wrapper —
    do NOT call ``record_scheduler_task`` here to avoid double-counting.
    """
    logger.info("Incremental pipeline task triggered")
    result = await run_incremental_for_all_sources()

    logger.info(
        "Incremental pipeline task finished: succeeded=%d, failed=%d",
        result.get("sources_succeeded", 0),
        result.get("sources_failed", 0),
    )
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _retopicize_source(channel_id: str) -> None:
    """Run topicization + export for a single channel."""
    from tg_parser.services.topicization_service import run_topicization

    logger.info("Auto-retopicizing channel %s", channel_id)
    stats = await run_topicization(
        channel_id=channel_id,
        force=True,
        build_bundles=True,
    )
    logger.info(
        "Retopicization done for %s: topics=%d, bundles=%d",
        channel_id,
        stats["topics_count"],
        stats["bundles_count"],
    )


async def _safe_record_failure(
    state_repo: IngestionStateRepo,
    source_id: str,
    exc: Exception,
    duration: float,
) -> None:
    """Record a failed attempt, swallowing any secondary exceptions."""
    try:
        await state_repo.record_attempt(
            source_id=source_id,
            success=False,
            error_class=type(exc).__name__,
            error_message=str(exc),
            details={
                "trigger": "scheduled",
                "duration_seconds": round(duration, 2),
            },
        )
    except Exception as inner:
        logger.error("Failed to record attempt for %s: %s", source_id, inner)


def _safe_stats(stats: dict) -> dict:
    """Extract serialisable subset of pipeline stats for storage."""
    safe: dict[str, Any] = {}
    for stage in ("ingest", "process", "topicize", "export"):
        if stats.get(stage):
            safe[stage] = {
                k: v
                for k, v in stats[stage].items()
                if isinstance(v, (int, float, str, bool, type(None)))
            }
    return safe
