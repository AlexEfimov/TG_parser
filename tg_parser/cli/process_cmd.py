"""
CLI команда для processing pipeline.

Реализует обработку raw сообщений канала через LLM.
v2.0: Добавлена поддержка agent-based processing.
Phase 2E: Добавлена поддержка hybrid mode (agent + pipeline tool).
"""

import logging
import os
from typing import TYPE_CHECKING

from tg_parser.config import settings

if TYPE_CHECKING:
    from tg_parser.processing.pipeline import ProcessingPipelineImpl
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
    use_agent: bool = False,
    use_llm_tools: bool = False,
    use_pipeline_tool: bool = False,
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
        use_agent: Использовать agent-based processing (v2.0)
        use_llm_tools: Использовать LLM-enhanced tools в агенте (v2.0)
        use_pipeline_tool: Включить v1.2 pipeline как tool агента (Phase 2E)

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

            # v2.0: Agent-based processing или v1.2 pipeline
            if use_agent:
                processed_docs = await _process_with_agent(
                    raw_messages=raw_messages,
                    processed_repo=processed_repo,
                    force=force,
                    concurrency=concurrency,
                    provider=provider,
                    model=model,
                    use_llm_tools=use_llm_tools,
                    use_pipeline_tool=use_pipeline_tool,
                    pipeline=pipeline if use_pipeline_tool else None,
                )
                if not use_pipeline_tool:
                    pipeline = None  # No pipeline to close
            else:
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

            # Закрываем LLM client если это OpenAI (только для pipeline mode)
            if pipeline is not None and hasattr(pipeline, "llm_client") and hasattr(pipeline.llm_client, "close"):
                await pipeline.llm_client.close()

    finally:
        await db.close()


async def _process_with_agent(
    raw_messages: list,
    processed_repo: SQLiteProcessedDocumentRepo,
    force: bool = False,
    concurrency: int = 3,
    provider: str | None = None,
    model: str | None = None,
    use_llm_tools: bool = False,
    use_pipeline_tool: bool = False,
    pipeline: "ProcessingPipelineImpl | None" = None,
) -> list:
    """
    Process messages using TGProcessingAgent.
    
    Args:
        raw_messages: List of RawTelegramMessage to process
        processed_repo: Repository for saving processed documents
        force: Reprocess existing documents
        concurrency: Number of parallel requests
        provider: LLM provider
        model: Model override
        use_llm_tools: Enable LLM-enhanced tools
        use_pipeline_tool: Enable v1.2 pipeline as agent tool (Phase 2E)
        pipeline: ProcessingPipelineImpl instance for hybrid mode
        
    Returns:
        List of ProcessedDocument
    """
    from tg_parser.agents import TGProcessingAgent
    from tg_parser.processing.llm.factory import create_llm_client
    
    mode_str = "agent"
    if use_llm_tools:
        mode_str += "+llm"
    if use_pipeline_tool:
        mode_str += "+hybrid"
    
    logger.info(f"Starting {mode_str} processing for {len(raw_messages)} messages")
    
    # Create LLM client for enhanced tools if needed
    llm_client = None
    if use_llm_tools:
        # Get API key from environment
        provider_name = provider or "openai"
        api_key = _get_api_key_for_provider(provider_name)
        if api_key:
            llm_client = create_llm_client(
                provider=provider_name,
                api_key=api_key,
                model=model,
            )
            logger.info(f"Created LLM client for enhanced tools: {provider_name}")
        else:
            logger.warning(f"No API key for {provider_name}, LLM tools will use fallback")
    
    # Create agent (Phase 2E: pass pipeline for hybrid mode)
    agent = TGProcessingAgent(
        model=model or "gpt-4o-mini",
        provider=provider or "openai",
        use_llm_tools=use_llm_tools,
        use_pipeline_tool=use_pipeline_tool,
        llm_client=llm_client,
        pipeline=pipeline,
    )
    
    # Filter messages if not force mode
    messages_to_process = []
    for msg in raw_messages:
        if force or not await processed_repo.exists(msg.source_ref):
            messages_to_process.append(msg)
    
    if not messages_to_process:
        logger.info("No new messages to process")
        return []
    
    logger.info(f"Processing {len(messages_to_process)} messages with agent")
    
    # Process batch
    processed_docs = await agent.process_batch(
        messages_to_process,
        concurrency=concurrency,
    )
    
    # Save processed documents
    for doc in processed_docs:
        if force:
            await processed_repo.upsert(doc)
        else:
            await processed_repo.save(doc)
    
    logger.info(f"Agent processing complete: {len(processed_docs)} documents saved")
    
    return processed_docs


def _get_api_key_for_provider(provider: str) -> str | None:
    """Get API key for the specified provider from environment."""
    key_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "google": "GEMINI_API_KEY",
    }
    env_var = key_map.get(provider.lower())
    if env_var:
        return os.getenv(env_var)
    return None
