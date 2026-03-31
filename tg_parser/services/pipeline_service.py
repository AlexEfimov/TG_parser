"""
Full pipeline orchestration service.

Extracted from cli/run_cmd.py — orchestrates ingest -> process -> topicize -> export.
"""

import contextlib
import structlog
import time
from typing import Literal

from tg_parser.services.db_context import ingestion_state_repo
from tg_parser.services.export_service import run_export
from tg_parser.services.ingestion_service import run_ingestion
from tg_parser.services.processing_service import run_processing
from tg_parser.services.topicization_service import run_topicization
from tg_parser.storage.ports import IngestionStateRepo

logger = structlog.get_logger(__name__)


def _normalize_channel_id(channel_id: str) -> str:
    """Normalize channel_id: remove @ prefix."""
    return channel_id.lstrip("@") if channel_id.startswith("@") else channel_id


async def _get_channel_id_from_source(
    source_id: str,
    *,
    repo: IngestionStateRepo | None = None,
) -> str:
    """
    Resolve normalized channel_id from sources table.

    Raises:
        ValueError: if source not found
    """
    async with contextlib.AsyncExitStack() as stack:
        if repo is None:
            repo, _db = await stack.enter_async_context(ingestion_state_repo())
        source = await repo.get_source(source_id)
        if not source:
            raise ValueError(f"Source {source_id} not found")
        return _normalize_channel_id(source.channel_id)


async def run_full_pipeline(
    source_id: str,
    output_dir: str = "./output",
    mode: Literal["snapshot", "incremental"] = "incremental",
    skip_ingest: bool = False,
    skip_process: bool = False,
    skip_topicize: bool = False,
    force: bool = False,
    limit: int | None = None,
    concurrency: int | None = None,
) -> dict:
    """
    One-shot full pipeline: ingest -> process -> topicize -> export.

    Args:
        source_id: Source/channel identifier
        output_dir: Export output directory
        mode: Ingestion mode (snapshot or incremental)
        skip_ingest: Skip ingestion stage
        skip_process: Skip processing stage
        skip_topicize: Skip topicization stage
        force: Force mode for processing and topicization
        limit: Message limit for ingestion (debugging)
        concurrency: Parallel LLM requests for processing (default: settings.processing_concurrency)

    Returns:
        Statistics for all stages with total duration

    Raises:
        RuntimeError: if any stage fails (with info about last successful stage)
    """
    start_time = time.time()

    stats = {
        "ingest": None,
        "process": None,
        "topicize": None,
        "export": None,
        "total_duration_seconds": 0,
        "last_successful_stage": None,
    }

    try:
        channel_id = await _get_channel_id_from_source(source_id)
        logger.info("Resolved channel_id: %s for source: %s", channel_id, source_id)
    except ValueError:
        channel_id = _normalize_channel_id(source_id)
        logger.warning("Source %s not found, using as channel_id: %s", source_id, channel_id)

    try:
        if not skip_ingest:
            logger.info("[1/4] Starting ingestion: source=%s, mode=%s", source_id, mode)
            stage_t0 = time.perf_counter()
            try:
                ingest_stats = await run_ingestion(
                    source_id=source_id,
                    mode=mode,
                    limit=limit,
                )
                ingest_duration = time.perf_counter() - stage_t0
                ingest_stats["stage_duration_seconds"] = round(ingest_duration, 3)
                stats["ingest"] = ingest_stats
                stats["last_successful_stage"] = "ingest"
                logger.info(
                    "[1/4] Ingestion completed in %.2fs: posts=%s, comments=%s",
                    ingest_duration,
                    ingest_stats["posts_collected"],
                    ingest_stats["comments_collected"],
                )
            except Exception as e:
                logger.error("[1/4] Ingestion failed: %s", e, exc_info=True)
                raise RuntimeError(f"Pipeline failed at ingestion stage: {e}") from e
        else:
            logger.info("[1/4] Ingestion skipped (--skip-ingest)")
            stats["last_successful_stage"] = "ingest"

        if not skip_process:
            logger.info(
                "[2/4] Starting processing: channel=%s, force=%s, concurrency=%s",
                channel_id,
                force,
                concurrency,
            )
            stage_t0 = time.perf_counter()
            try:
                process_stats = await run_processing(
                    channel_id=channel_id,
                    force=force,
                    concurrency=concurrency,
                )
                process_duration = time.perf_counter() - stage_t0
                process_stats["stage_duration_seconds"] = round(process_duration, 3)
                stats["process"] = process_stats
                stats["last_successful_stage"] = "process"
                logger.info(
                    "[2/4] Processing completed in %.2fs: processed=%s, failed=%s",
                    process_duration,
                    process_stats["processed_count"],
                    process_stats["failed_count"],
                )

                if process_stats["processed_count"] == 0:
                    logger.warning(
                        "[2/4] No documents processed - subsequent stages may have no data"
                    )

            except Exception as e:
                logger.error("[2/4] Processing failed: %s", e, exc_info=True)
                raise RuntimeError(f"Pipeline failed at processing stage: {e}") from e
        else:
            logger.info("[2/4] Processing skipped (--skip-process)")
            stats["last_successful_stage"] = "process"

        if not skip_topicize:
            logger.info("[3/4] Starting topicization: channel=%s, force=%s", channel_id, force)
            stage_t0 = time.perf_counter()
            try:
                topicize_stats = await run_topicization(
                    channel_id=channel_id,
                    force=force,
                    build_bundles=True,
                )
                topicize_duration = time.perf_counter() - stage_t0
                topicize_stats["stage_duration_seconds"] = round(topicize_duration, 3)
                stats["topicize"] = topicize_stats
                stats["last_successful_stage"] = "topicize"
                logger.info(
                    "[3/4] Topicization completed in %.2fs: topics=%s, bundles=%s",
                    topicize_duration,
                    topicize_stats["topics_count"],
                    topicize_stats["bundles_count"],
                )
            except Exception as e:
                logger.error("[3/4] Topicization failed: %s", e, exc_info=True)
                raise RuntimeError(f"Pipeline failed at topicization stage: {e}") from e
        else:
            logger.info("[3/4] Topicization skipped (--skip-topicize)")
            stats["last_successful_stage"] = "topicize"

        logger.info("[4/4] Starting export: channel=%s, output=%s", channel_id, output_dir)
        stage_t0 = time.perf_counter()
        try:
            export_stats = await run_export(
                output_dir=output_dir,
                channel_id=channel_id,
                topic_id=None,
                from_date=None,
                to_date=None,
                pretty=False,
            )
            export_duration = time.perf_counter() - stage_t0
            export_stats["stage_duration_seconds"] = round(export_duration, 3)
            stats["export"] = export_stats
            stats["last_successful_stage"] = "export"
            logger.info(
                "[4/4] Export completed in %.2fs: kb_entries=%s, topics=%s",
                export_duration,
                export_stats["kb_entries_count"],
                export_stats["topics_count"],
            )
        except Exception as e:
            logger.error("[4/4] Export failed: %s", e, exc_info=True)
            raise RuntimeError(f"Pipeline failed at export stage: {e}") from e

        end_time = time.time()
        stats["total_duration_seconds"] = round(end_time - start_time, 3)

        logger.info(
            "Pipeline completed successfully in %.2fs",
            stats["total_duration_seconds"],
        )

        return stats

    except Exception:
        end_time = time.time()
        stats["total_duration_seconds"] = round(end_time - start_time, 3)
        logger.error(
            "Pipeline failed after %.2fs at stage: %s",
            stats["total_duration_seconds"],
            stats["last_successful_stage"],
        )
        raise
