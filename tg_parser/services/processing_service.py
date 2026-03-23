"""
Processing service.

Extracted from cli/process_cmd.py — owns the business logic for
processing raw messages through the LLM pipeline.
"""

import logging
import os
from typing import TYPE_CHECKING

from tg_parser.config import settings

if TYPE_CHECKING:
    from tg_parser.processing.pipeline import ProcessingPipelineImpl
from tg_parser.processing import create_processing_pipeline
from tg_parser.storage.sqlalchemy import Database
from tg_parser.storage.sqlalchemy.processed_document_repo import (
    SQLiteProcessedDocumentRepo,
)
from tg_parser.storage.sqlalchemy.processing_failure_repo import (
    SQLiteProcessingFailureRepo,
)
from tg_parser.storage.sqlalchemy.raw_message_repo import SQLiteRawMessageRepo

logger = logging.getLogger(__name__)


async def run_processing(
    channel_id: str,
    force: bool = False,
    retry_failed: bool = False,
    provider: str | None = None,
    model: str | None = None,
    concurrency: int | None = None,
    use_agent: bool = False,
    use_llm_tools: bool = False,
    use_pipeline_tool: bool = False,
) -> dict[str, int]:
    """
    Run processing for a channel.

    Args:
        channel_id: Channel identifier
        force: Reprocess existing documents
        retry_failed: Retry only previously failed messages
        provider: LLM provider override
        model: Model override
        concurrency: Parallel requests (default: settings.processing_concurrency)
        use_agent: Use agent-based processing
        use_llm_tools: Use LLM-enhanced tools in agent
        use_pipeline_tool: Enable v1.2 pipeline as agent tool

    Returns:
        Processing statistics (processed_count, skipped_count, failed_count, total_count)
    """
    if concurrency is None:
        concurrency = settings.processing_concurrency

    logger.info("Processing concurrency: %d (from %s)",
                concurrency,
                "settings" if concurrency == settings.processing_concurrency else "override")
    db = Database.from_settings(settings)
    await db.init()

    try:
        raw_session = db.raw_storage_session()
        processing_session = db.processing_storage_session()

        try:
            raw_repo = SQLiteRawMessageRepo(raw_session)
            processed_repo = SQLiteProcessedDocumentRepo(processing_session)
            failure_repo = SQLiteProcessingFailureRepo(processing_session)

            pipeline = create_processing_pipeline(
                provider=provider,
                model=model,
                processed_doc_repo=processed_repo,
                failure_repo=failure_repo,
                raw_repo=raw_repo,
            )

            if retry_failed:
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

                failed_source_refs = {f["source_ref"] for f in failures}
                raw_messages = []
                for source_ref in failed_source_refs:
                    msg = await raw_repo.get_by_source_ref(source_ref)
                    if msg:
                        raw_messages.append(msg)

                logger.info(f"Found {len(raw_messages)} failed messages to retry")
            else:
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
                    pipeline = None
            else:
                processed_docs = await pipeline.process_batch(
                    raw_messages,
                    force=force,
                    concurrency=concurrency,
                )

            total_count = len(raw_messages)
            processed_count = len(processed_docs)

            if not force:
                skipped_count = 0
                for msg in raw_messages:
                    if await processed_repo.exists(msg.source_ref):
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
    """Process messages using TGProcessingAgent."""
    from tg_parser.agents import TGProcessingAgent
    from tg_parser.processing.llm.factory import create_llm_client

    mode_str = "agent"
    if use_llm_tools:
        mode_str += "+llm"
    if use_pipeline_tool:
        mode_str += "+hybrid"

    logger.info(f"Starting {mode_str} processing for {len(raw_messages)} messages")

    llm_client = None
    if use_llm_tools:
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

    agent = TGProcessingAgent(
        model=model or "gpt-4o-mini",
        provider=provider or "openai",
        use_llm_tools=use_llm_tools,
        use_pipeline_tool=use_pipeline_tool,
        llm_client=llm_client,
        pipeline=pipeline,
    )

    messages_to_process = []
    for msg in raw_messages:
        if force or not await processed_repo.exists(msg.source_ref):
            messages_to_process.append(msg)

    if not messages_to_process:
        logger.info("No new messages to process")
        return []

    logger.info(f"Processing {len(messages_to_process)} messages with agent")

    processed_docs = await agent.process_batch(
        messages_to_process,
        concurrency=concurrency,
    )

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


async def run_multi_agent_processing(
    channel_id: str,
    force: bool = False,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, int]:
    """
    Run multi-agent orchestrated processing for a channel (Phase 3A).

    Uses OrchestratorAgent to coordinate specialized agents:
    - ProcessingAgent: Process raw messages
    - TopicizationAgent: Cluster into topics
    """
    from tg_parser.agents import (
        AgentRegistry,
        OrchestratorAgent,
        ProcessingAgent,
        TopicizationAgent,
    )

    logger.info(f"Starting multi-agent processing for channel: {channel_id}")

    db = Database.from_settings(settings)
    await db.init()

    try:
        raw_session = db.raw_storage_session()
        processing_session = db.processing_storage_session()

        try:
            raw_repo = SQLiteRawMessageRepo(raw_session)
            processed_repo = SQLiteProcessedDocumentRepo(processing_session)

            logger.info(f"Loading raw messages for channel: {channel_id}")
            raw_messages = await raw_repo.list_by_channel(channel_id)

            if not raw_messages:
                logger.warning(f"No raw messages found for channel: {channel_id}")
                return {
                    "processed_count": 0,
                    "skipped_count": 0,
                    "failed_count": 0,
                    "total_count": 0,
                    "multi_agent": True,
                }

            logger.info(f"Found {len(raw_messages)} raw messages")

            messages_to_process = []
            for msg in raw_messages:
                if force or not await processed_repo.exists(msg.source_ref):
                    messages_to_process.append(msg)

            if not messages_to_process:
                logger.info("No new messages to process")
                return {
                    "processed_count": 0,
                    "skipped_count": len(raw_messages),
                    "failed_count": 0,
                    "total_count": len(raw_messages),
                    "multi_agent": True,
                }

            registry = AgentRegistry()

            processing_agent = ProcessingAgent(
                model=model or "gpt-4o-mini",
                provider=provider or "openai",
            )
            topicization_agent = TopicizationAgent(
                model=model or "gpt-4o-mini",
                provider=provider or "openai",
            )

            registry.register(processing_agent)
            registry.register(topicization_agent)

            orchestrator = OrchestratorAgent(registry=registry)

            await processing_agent.initialize()
            await topicization_agent.initialize()
            await orchestrator.initialize()

            logger.info("Multi-agent system initialized")

            processed_count = 0
            failed_count = 0
            processed_docs = []

            for msg in messages_to_process:
                try:
                    result = await orchestrator.send_to(
                        "ProcessingAgent",
                        {"text": msg.text},
                    )

                    if result:
                        from datetime import UTC, datetime

                        from tg_parser.domain.ids import make_processed_document_id
                        from tg_parser.domain.models import Entity, ProcessedDocument

                        entities = [
                            Entity(
                                type=e.get("type", "unknown"),
                                value=e.get("value", ""),
                                confidence=e.get("confidence"),
                            )
                            for e in result.get("entities", [])
                            if e.get("value")
                        ]

                        doc = ProcessedDocument(
                            id=make_processed_document_id(msg.source_ref),
                            source_ref=msg.source_ref,
                            source_message_id=msg.id,
                            channel_id=msg.channel_id,
                            processed_at=datetime.now(UTC),
                            text_clean=result.get("text_clean", msg.text),
                            summary=result.get("summary"),
                            topics=result.get("topics", []),
                            entities=entities,
                            language=result.get("language", "unknown"),
                            metadata={
                                "pipeline_version": "multi-agent-v3.0",
                                "orchestrator": "OrchestratorAgent",
                                "agent": "ProcessingAgent",
                            },
                        )

                        if force:
                            await processed_repo.upsert(doc)
                        else:
                            await processed_repo.save(doc)

                        processed_docs.append(doc)
                        processed_count += 1

                except Exception as e:
                    logger.error(f"Failed to process {msg.source_ref}: {e}")
                    failed_count += 1

            await orchestrator.shutdown()
            await topicization_agent.shutdown()
            await processing_agent.shutdown()

            logger.info(f"Multi-agent processing complete: {processed_count} processed, {failed_count} failed")

            return {
                "processed_count": processed_count,
                "skipped_count": len(raw_messages) - len(messages_to_process),
                "failed_count": failed_count,
                "total_count": len(raw_messages),
                "multi_agent": True,
            }

        finally:
            await raw_session.close()
            await processing_session.close()

    finally:
        await db.close()
