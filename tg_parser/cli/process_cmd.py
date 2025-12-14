"""
CLI команда для processing pipeline.

Реализует обработку raw сообщений канала через LLM.
"""

import logging
from typing import Dict

from tg_parser.config import settings
from tg_parser.processing import create_processing_pipeline
from tg_parser.storage.sqlite import Database, DatabaseConfig
from tg_parser.storage.sqlite.processed_document_repo import (
    SQLiteProcessedDocumentRepo,
)
from tg_parser.storage.sqlite.raw_message_repo import SQLiteRawMessageRepo

logger = logging.getLogger(__name__)


async def run_processing(
    channel_id: str,
    force: bool = False,
) -> Dict[str, int]:
    """
    Запустить processing для канала.
    
    Args:
        channel_id: Идентификатор канала
        force: Переобработать существующие (TR-46)
        
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
            
            # Создаём processing pipeline
            # Note: failure_repo пока не реализован, передаём None
            pipeline = create_processing_pipeline(
                processed_doc_repo=processed_repo,
                failure_repo=None,
            )
            
            # Получаем raw сообщения канала
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
            
            # Обрабатываем батч
            processed_docs = await pipeline.process_batch(
                raw_messages,
                force=force,
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
            if hasattr(pipeline, 'llm_client') and hasattr(pipeline.llm_client, 'close'):
                await pipeline.llm_client.close()
    
    finally:
        await db.close()
