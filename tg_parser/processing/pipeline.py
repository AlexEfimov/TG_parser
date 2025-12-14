"""
Processing pipeline implementation.

Реализует ProcessingPipeline: обработка RawTelegramMessage → ProcessedDocument.
Требования: TR-21..TR-26, TR-46..TR-49.
"""

import asyncio
import json
import logging
import random
from datetime import UTC, datetime

from tg_parser.config import settings
from tg_parser.domain.ids import make_processed_document_id
from tg_parser.domain.models import Entity, ProcessedDocument, RawTelegramMessage
from tg_parser.processing.llm.openai_client import OpenAIClient
from tg_parser.processing.ports import LLMClient, ProcessingPipeline
from tg_parser.processing.prompts import (
    PROCESSING_SYSTEM_PROMPT,
    build_processing_prompt,
    get_processing_prompt_name,
)
from tg_parser.storage.ports import ProcessedDocumentRepo, ProcessingFailureRepo

logger = logging.getLogger(__name__)


class ProcessingPipelineImpl(ProcessingPipeline):
    """
    Реализация pipeline обработки сообщений.

    Требования:
    - TR-21: 1 raw → 1 processed
    - TR-22: идемпотентность по source_ref
    - TR-23: metadata с pipeline_version/model_id/prompt_id
    - TR-38: детерминизм LLM (temperature=0)
    - TR-46: инкрементальность
    - TR-47: ретраи per-message
    - TR-49: семантика processed_at
    """

    def __init__(
        self,
        llm_client: LLMClient,
        processed_doc_repo: ProcessedDocumentRepo,
        failure_repo: ProcessingFailureRepo | None = None,
        pipeline_version: str | None = None,
        model_id: str | None = None,
    ):
        """
        Args:
            llm_client: LLM клиент для обработки
            processed_doc_repo: Репозиторий processed документов
            failure_repo: Репозиторий ошибок (опционально)
            pipeline_version: Версия pipeline (default из settings)
            model_id: Идентификатор модели (default из OpenAI client)
        """
        self.llm_client = llm_client
        self.processed_doc_repo = processed_doc_repo
        self.failure_repo = failure_repo
        self.pipeline_version = pipeline_version or settings.pipeline_version_processing

        # Model ID извлекаем из OpenAI client если доступен
        if model_id:
            self.model_id = model_id
        elif isinstance(llm_client, OpenAIClient):
            self.model_id = llm_client.model
        else:
            self.model_id = "unknown"

        # Вычисляем prompt_id (TR-40)
        if isinstance(llm_client, OpenAIClient):
            self.prompt_id = llm_client.compute_prompt_id(
                PROCESSING_SYSTEM_PROMPT,
                build_processing_prompt("{text}"),  # Шаблон без подстановки
            )
        else:
            self.prompt_id = "unknown"

        self.prompt_name = get_processing_prompt_name()

    async def process_message(
        self,
        message: RawTelegramMessage,
        force: bool = False,
    ) -> ProcessedDocument:
        """
        Обработать одно сырое сообщение.

        TR-21: 1 raw → 1 processed
        TR-22: идемпотентность по source_ref
        TR-46/TR-48: инкрементальность (skip если уже обработано)
        TR-47: ретраи per-message (3 попытки, backoff 1/2/4s)

        Args:
            message: RawTelegramMessage
            force: Переобработать даже если уже есть processed (TR-46)

        Returns:
            ProcessedDocument

        Raises:
            Exception: При исчерпании ретраев
        """
        # TR-46/TR-48: проверяем существование
        if not force:
            exists = await self.processed_doc_repo.exists(message.source_ref)
            if exists:
                logger.info(f"Skipping already processed message: {message.source_ref}")
                # Загружаем существующий документ
                doc = await self.processed_doc_repo.get_by_source_ref(message.source_ref)
                if doc:
                    return doc
                # Если не смогли загрузить, продолжаем обработку
                logger.warning(
                    f"exists() returned True but get_by_source_ref() returned None for {message.source_ref}"
                )

        # TR-47: ретраи per-message (3 попытки, backoff 1/2/4s + jitter)
        max_attempts = settings.processing_max_attempts_per_message
        backoff_base = settings.processing_retry_backoff_base
        jitter_max = settings.processing_retry_jitter_max

        last_error = None

        for attempt in range(1, max_attempts + 1):
            try:
                # Обрабатываем сообщение
                processed = await self._process_single_message(message)

                # TR-22: сохраняем (upsert по source_ref)
                await self.processed_doc_repo.upsert(processed)

                # Очищаем ошибку если была записана ранее
                if self.failure_repo:
                    await self.failure_repo.delete_failure(message.source_ref)

                logger.info(
                    f"Successfully processed message: {message.source_ref}",
                    extra={"attempt": attempt, "max_attempts": max_attempts},
                )

                return processed

            except Exception as e:
                last_error = e
                logger.warning(
                    f"Processing attempt {attempt}/{max_attempts} failed for {message.source_ref}: {e}",
                    exc_info=True,
                )

                # Если есть ещё попытки, делаем backoff
                if attempt < max_attempts:
                    # Вычисляем backoff: 1s, 2s, 4s с jitter 0-30%
                    delay = backoff_base * (2 ** (attempt - 1))
                    jitter = random.uniform(0, delay * jitter_max)
                    total_delay = delay + jitter

                    logger.info(
                        f"Retrying after {total_delay:.2f}s (backoff={delay}s, jitter={jitter:.2f}s)"
                    )
                    await asyncio.sleep(total_delay)

        # TR-47: исчерпаны попытки, записываем в failures
        if self.failure_repo:
            await self.failure_repo.record_failure(
                source_ref=message.source_ref,
                channel_id=message.channel_id,
                attempts=max_attempts,
                error_class=type(last_error).__name__,
                error_message=str(last_error),
            )

        # Пробрасываем ошибку
        logger.error(
            f"Failed to process message after {max_attempts} attempts: {message.source_ref}"
        )
        raise last_error

    async def _process_single_message(
        self,
        message: RawTelegramMessage,
    ) -> ProcessedDocument:
        """
        Обработать одно сообщение через LLM (без ретраев).

        TR-21: извлечение text_clean, summary, topics, entities, language
        TR-23: формирование metadata
        TR-38: temperature=0 для детерминизма
        TR-41: id = "doc:" + source_ref
        TR-49: processed_at = now (UTC)

        Args:
            message: RawTelegramMessage

        Returns:
            ProcessedDocument
        """
        # Формируем промпт
        user_prompt = build_processing_prompt(message.text)

        # Вызываем LLM (TR-38: temperature=0)
        response_text = await self.llm_client.generate(
            prompt=user_prompt,
            system_prompt=PROCESSING_SYSTEM_PROMPT,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            response_format={"type": "json_object"},
        )

        # Парсим JSON ответ
        try:
            response_data = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(
                f"Failed to parse LLM response as JSON: {e}",
                extra={"response": response_text[:500]},
            )
            raise ValueError(f"Invalid JSON response from LLM: {e}") from e

        # Извлекаем обязательные поля
        text_clean = response_data.get("text_clean")
        if not text_clean:
            raise ValueError("LLM response missing required field: text_clean")

        # Опциональные поля
        summary = response_data.get("summary")
        topics = response_data.get("topics", [])
        language = response_data.get("language")

        # Парсим entities
        entities_data = response_data.get("entities", [])
        entities = [
            Entity(
                type=ent.get("type", "unknown"),
                value=ent.get("value", ""),
                confidence=ent.get("confidence"),
            )
            for ent in entities_data
        ]

        # TR-23: формируем metadata
        metadata = {
            "pipeline_version": self.pipeline_version,
            "model_id": self.model_id,
            "prompt_id": self.prompt_id,
            "prompt_name": self.prompt_name,
            "parameters": {
                "temperature": settings.llm_temperature,
                "max_tokens": settings.llm_max_tokens,
            },
        }

        # TR-41: id = "doc:" + source_ref
        doc_id = make_processed_document_id(message.source_ref)

        # TR-49: processed_at = now (UTC)
        processed_at = datetime.now(UTC)

        # Создаём ProcessedDocument
        processed = ProcessedDocument(
            id=doc_id,
            source_ref=message.source_ref,
            source_message_id=message.id,
            channel_id=message.channel_id,
            processed_at=processed_at,
            text_clean=text_clean,
            summary=summary,
            topics=topics,
            entities=entities,
            language=language,
            metadata=metadata,
        )

        return processed

    async def process_batch(
        self,
        messages: list[RawTelegramMessage],
        force: bool = False,
    ) -> list[ProcessedDocument]:
        """
        Обработать батч сообщений.

        TR-47: ошибка на одном сообщении не должна ронять весь батч.

        Args:
            messages: Список RawTelegramMessage
            force: Переобработать даже если уже есть processed

        Returns:
            Список ProcessedDocument (могут быть пропуски при ошибках)
        """
        results = []

        for message in messages:
            try:
                processed = await self.process_message(message, force=force)
                results.append(processed)
            except Exception as e:
                # TR-47: не роняем весь батч, логируем и продолжаем
                logger.error(
                    f"Failed to process message {message.source_ref} in batch: {e}",
                    exc_info=True,
                )
                # Продолжаем со следующим сообщением
                continue

        logger.info(f"Batch processing complete: {len(results)}/{len(messages)} successful")

        return results


def create_processing_pipeline(
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    processed_doc_repo: ProcessedDocumentRepo | None = None,
    failure_repo: ProcessingFailureRepo | None = None,
) -> ProcessingPipelineImpl:
    """
    Factory function для создания ProcessingPipeline с OpenAI клиентом.

    Args:
        api_key: OpenAI API key (default из settings)
        model: Модель (default из settings или gpt-4o-mini)
        base_url: Base URL для OpenAI-compatible API (default из settings)
        processed_doc_repo: Репозиторий документов (required для CLI)
        failure_repo: Репозиторий ошибок (опционально)

    Returns:
        ProcessingPipelineImpl instance
    """
    # Получаем API key из аргументов или settings
    api_key = api_key or settings.openai_api_key
    if not api_key:
        raise ValueError(
            "OpenAI API key not provided. Set OPENAI_API_KEY env variable or pass api_key argument."
        )

    # Модель из аргументов, settings или default
    model = model or settings.llm_model or "gpt-4o-mini"

    # Base URL из аргументов или settings
    base_url = base_url or settings.llm_base_url

    # Создаём OpenAI клиент
    llm_client = OpenAIClient(
        api_key=api_key,
        model=model,
        base_url=base_url,
    )

    # Создаём pipeline
    pipeline = ProcessingPipelineImpl(
        llm_client=llm_client,
        processed_doc_repo=processed_doc_repo,
        failure_repo=failure_repo,
        model_id=model,
    )

    return pipeline
