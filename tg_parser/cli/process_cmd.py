"""
CLI команда для processing pipeline.

Реализует обработку raw сообщений канала через LLM.
"""

import logging

from tg_parser.config import settings
from tg_parser.processing import create_processing_pipeline
from tg_parser.storage.sqlite import Database, DatabaseConfig
from tg_parser.storage.sqlite.processed_document_repo import (
    SQLiteProcessedDocumentRepo,
)
from tg_parser.storage.sqlite.processing_failure_repo import (
    SQLiteProcessingFailureRepo,
)
from tg_parser.storage.sqlite.raw_message_repo import SQLiteRawMessageRepo

logger = logging.getLogger(__name__)


async def run_processing(
    channel_id: str,
    force: bool = False,
    retry_failed: bool = False,
    provider: str | None = None,
    model: str | None = None,
    concurrency: int = 1,
) -> dict[str, int]:
    """
    Запустить processing для канала.

    Args:
        channel_id: Идентификатор канала
        force: Переобработать существующие (TR-46)
        retry_failed: Повторить обработку только failed сообщений (v1.1)
        provider: LLM provider override (v1.2)
        model: Model override (v1.2)
        concurrency: Параллельные запросы (v1.2)

    Returns:
        Статистика обработки (processed_count, skipped_count, failed_count, total_count)
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

    try:
        # Создаём sessions
        raw_session = db.raw_storage_session()
        processing_session = db.processing_storage_session()

        try:
            # Создаём репозитории
            raw_repo = SQLiteRawMessageRepo(raw_session)
            processed_repo = SQLiteProcessedDocumentRepo(processing_session)
            failure_repo = SQLiteProcessingFailureRepo(processing_session)

            # Создаём processing pipeline (v1.2: Multi-LLM)
            pipeline = create_processing_pipeline(
                provider=provider,
                model=model,
                processed_doc_repo=processed_repo,
                failure_repo=failure_repo,
            )

            # Получаем сообщения для обработки
            if retry_failed:
                # Режим retry: получаем только failed сообщения
                logger.info(f"Loading failed messages for channel: {channel_id}")
                failures = await failure_repo.list_failures(channel_id=channel_id)

                if not failures:
                    logger.info(f"No failed messages to retry for channel: {channel_id}")
                    return {
                        "processed_count": 0,
                        "skipped_count": 0,
                        "failed_count": 0,
                        "total_count": 0,
                        "retry_mode": True,
                    }

                # Получаем raw сообщения для failed source_refs
                failed_source_refs = {f["source_ref"] for f in failures}
                raw_messages = []
                for source_ref in failed_source_refs:
                    msg = await raw_repo.get_by_source_ref(source_ref)
                    if msg:
                        raw_messages.append(msg)

                logger.info(f"Found {len(raw_messages)} failed messages to retry")
            else:
                # Обычный режим: все сообщения канала
                logger.info(f"Loading raw messages for channel: {channel_id}")
                raw_messages = await raw_repo.list_by_channel(channel_id)

            if not raw_messages:
                logger.warning(f"No raw messages found for channel: {channel_id}")
                return {
                    "processed_count": 0,
                    "skipped_count": 0,
                    "failed_count": 0,
                    "total_count": 0,
                }

            logger.info(f"Found {len(raw_messages)} raw messages")

            # Обрабатываем батч (v1.2: с concurrency)
            processed_docs = await pipeline.process_batch(
                raw_messages,
                force=force,
                concurrency=concurrency,
            )

            # Вычисляем статистику
            total_count = len(raw_messages)
            processed_count = len(processed_docs)

            # TR-46/TR-48: подсчёт skipped (если не force)
            if not force:
                # Проверяем какие сообщения уже были обработаны
                skipped_count = 0
                for msg in raw_messages:
                    if await processed_repo.exists(msg.source_ref):
                        # Если документ существует и не был переобработан
                        if not any(doc.source_ref == msg.source_ref for doc in processed_docs):
                            skipped_count += 1
            else:
                skipped_count = 0

            failed_count = total_count - processed_count - skipped_count

            return {
                "processed_count": processed_count,
                "skipped_count": skipped_count,
                "failed_count": failed_count,
                "total_count": total_count,
            }

        finally:
            await raw_session.close()
            await processing_session.close()

            # Закрываем LLM client если это OpenAI
            if hasattr(pipeline, "llm_client") and hasattr(pipeline.llm_client, "close"):
                await pipeline.llm_client.close()

    finally:
        await db.close()
