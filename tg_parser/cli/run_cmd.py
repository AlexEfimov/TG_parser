"""
CLI команда для one-shot запуска полного pipeline.

Реализует последовательный вызов: ingest → process → topicize → export.
"""

import logging
import time
from typing import Literal

from tg_parser.cli.export_cmd import run_export
from tg_parser.cli.ingest_cmd import run_ingestion
from tg_parser.cli.process_cmd import run_processing
from tg_parser.cli.topicize_cmd import run_topicization
from tg_parser.config import settings
from tg_parser.storage.sqlite import Database, DatabaseConfig, SQLiteIngestionStateRepo

logger = logging.getLogger(__name__)


def _normalize_channel_id(channel_id: str) -> str:
    """Нормализовать channel_id: убрать @ prefix."""
    return channel_id.lstrip("@") if channel_id.startswith("@") else channel_id


async def _get_channel_id_from_source(source_id: str) -> str:
    """
    Получить нормализованный channel_id из таблицы sources.

    Args:
        source_id: ID источника

    Returns:
        Нормализованный channel_id (без @)

    Raises:
        ValueError: если источник не найден
    """
    config = DatabaseConfig(
        ingestion_state_path=settings.ingestion_state_db_path,
        raw_storage_path=settings.raw_storage_db_path,
        processing_storage_path=settings.processing_storage_db_path,
    )
    db = Database(config)
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
    One-shot запуск полного pipeline: ingest → process → topicize → export.

    Args:
        source_id: Идентификатор источника/канала
        output_dir: Директория для экспорта (по умолчанию ./output)
        mode: Режим ingestion (snapshot или incremental)
        skip_ingest: Пропустить этап ingestion
        skip_process: Пропустить этап processing
        skip_topicize: Пропустить этап topicization
        force: Force режим для processing и topicization
        limit: Лимит сообщений для ingestion (для отладки)

    Returns:
        Статистика выполнения всех этапов с итоговым временем

    Raises:
        Exception: если любой из этапов провалился (с информацией о последнем успешном этапе)
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

    # Получаем нормализованный channel_id из источника
    # (source_id != channel_id, например: source_id="labdiag", channel_id="labdiagnostica_logical")
    try:
        channel_id = await _get_channel_id_from_source(source_id)
        logger.info(f"Resolved channel_id: {channel_id} for source: {source_id}")
    except ValueError:
        # Если источник не найден (например, при skip-ingest в тестах),
        # используем source_id как channel_id (обратная совместимость)
        channel_id = _normalize_channel_id(source_id)
        logger.warning(f"Source {source_id} not found, using as channel_id: {channel_id}")

    try:
        # Step 1: Ingestion (если не skip)
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

        # Step 2: Processing (если не skip)
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

                # Проверяем наличие данных для дальнейших этапов
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

        # Step 3: Topicization (если не skip)
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

        # Step 4: Export (всегда выполняется)
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

        # Вычисляем итоговое время
        end_time = time.time()
        stats["total_duration_seconds"] = end_time - start_time

        logger.info(f"Pipeline completed successfully in {stats['total_duration_seconds']:.2f}s")

        return stats

    except Exception:
        # В случае ошибки добавляем время выполнения и re-raise
        end_time = time.time()
        stats["total_duration_seconds"] = end_time - start_time
        logger.error(
            f"Pipeline failed after {stats['total_duration_seconds']:.2f}s "
            f"at stage: {stats['last_successful_stage']}"
        )
        raise
