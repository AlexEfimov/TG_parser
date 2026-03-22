"""
Full pipeline orchestration service.

Extracted from cli/run_cmd.py — orchestrates ingest -> process -> topicize -> export.
"""

import logging
import time
from typing import Literal

from tg_parser.config import settings
from tg_parser.services.export_service import run_export
from tg_parser.services.ingestion_service import run_ingestion
from tg_parser.services.processing_service import run_processing
from tg_parser.services.topicization_service import run_topicization
from tg_parser.storage.sqlalchemy import Database, SQLiteIngestionStateRepo

logger = logging.getLogger(__name__)


def _normalize_channel_id(channel_id: str) -> str:
    """Normalize channel_id: remove @ prefix."""
    return channel_id.lstrip("@") if channel_id.startswith("@") else channel_id


async def _get_channel_id_from_source(source_id: str) -> str:
    """
    Resolve normalized channel_id from sources table.

    Raises:
        ValueError: if source not found
    """
    db = Database.from_settings(settings)
    await db.init()

    try:
        session = db.ingestion_state_session()
        try:
            repo = SQLiteIngestionStateRepo(session)
            source = await repo.get_source(source_id)
            if not source:
                raise ValueError(f"Source {source_id} not found")
            return _normalize_channel_id(source.channel_id)
        finally:
            await session.close()
    finally:
        await db.close()


async def run_full_pipeline(
    source_id: str,
    output_dir: str = "./output",
    mode: Literal["snapshot", "incremental"] = "incremental",
    skip_ingest: bool = False,
    skip_process: bool = False,
    skip_topicize: bool = False,
    force: bool = False,
    limit: int | None = None,
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
        logger.info(f"Resolved channel_id: {channel_id} for source: {source_id}")
    except ValueError:
        channel_id = _normalize_channel_id(source_id)
        logger.warning(f"Source {source_id} not found, using as channel_id: {channel_id}")

    try:
        if not skip_ingest:
            logger.info(f"[1/4] Starting ingestion: source={source_id}, mode={mode}")
            try:
                ingest_stats = await run_ingestion(
                    source_id=source_id,
                    mode=mode,
                    limit=limit,
                )
                stats["ingest"] = ingest_stats
                stats["last_successful_stage"] = "ingest"
                logger.info(
                    f"[1/4] Ingestion completed: posts={ingest_stats['posts_collected']}, "
                    f"comments={ingest_stats['comments_collected']}"
                )
            except Exception as e:
                logger.error(f"[1/4] Ingestion failed: {e}", exc_info=True)
                raise RuntimeError(f"Pipeline failed at ingestion stage: {e}") from e
        else:
            logger.info("[1/4] Ingestion skipped (--skip-ingest)")
            stats["last_successful_stage"] = "ingest"

        if not skip_process:
            logger.info(f"[2/4] Starting processing: channel={channel_id}, force={force}")
            try:
                process_stats = await run_processing(
                    channel_id=channel_id,
                    force=force,
                )
                stats["process"] = process_stats
                stats["last_successful_stage"] = "process"
                logger.info(
                    f"[2/4] Processing completed: processed={process_stats['processed_count']}, "
                    f"failed={process_stats['failed_count']}"
                )

                if process_stats["processed_count"] == 0:
                    logger.warning(
                        "[2/4] No documents processed - subsequent stages may have no data"
                    )

            except Exception as e:
                logger.error(f"[2/4] Processing failed: {e}", exc_info=True)
                raise RuntimeError(f"Pipeline failed at processing stage: {e}") from e
        else:
            logger.info("[2/4] Processing skipped (--skip-process)")
            stats["last_successful_stage"] = "process"

        if not skip_topicize:
            logger.info(f"[3/4] Starting topicization: channel={channel_id}, force={force}")
            try:
                topicize_stats = await run_topicization(
                    channel_id=channel_id,
                    force=force,
                    build_bundles=True,
                )
                stats["topicize"] = topicize_stats
                stats["last_successful_stage"] = "topicize"
                logger.info(
                    f"[3/4] Topicization completed: topics={topicize_stats['topics_count']}, "
                    f"bundles={topicize_stats['bundles_count']}"
                )
            except Exception as e:
                logger.error(f"[3/4] Topicization failed: {e}", exc_info=True)
                raise RuntimeError(f"Pipeline failed at topicization stage: {e}") from e
        else:
            logger.info("[3/4] Topicization skipped (--skip-topicize)")
            stats["last_successful_stage"] = "topicize"

        logger.info(f"[4/4] Starting export: channel={channel_id}, output={output_dir}")
        try:
            export_stats = await run_export(
                output_dir=output_dir,
                channel_id=channel_id,
                topic_id=None,
                from_date=None,
                to_date=None,
                pretty=False,
            )
            stats["export"] = export_stats
            stats["last_successful_stage"] = "export"
            logger.info(
                f"[4/4] Export completed: kb_entries={export_stats['kb_entries_count']}, "
                f"topics={export_stats['topics_count']}"
            )
        except Exception as e:
            logger.error(f"[4/4] Export failed: {e}", exc_info=True)
            raise RuntimeError(f"Pipeline failed at export stage: {e}") from e

        end_time = time.time()
        stats["total_duration_seconds"] = end_time - start_time

        logger.info(f"Pipeline completed successfully in {stats['total_duration_seconds']:.2f}s")

        return stats

    except Exception:
        end_time = time.time()
        stats["total_duration_seconds"] = end_time - start_time
        logger.error(
            f"Pipeline failed after {stats['total_duration_seconds']:.2f}s "
            f"at stage: {stats['last_successful_stage']}"
        )
        raise
