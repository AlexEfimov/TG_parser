"""
Processing pipeline implementation.

Реализует ProcessingPipeline: обработка RawTelegramMessage → ProcessedDocument.
Требования: TR-21..TR-26, TR-46..TR-49.
"""

import asyncio
import json
import random
import re
from datetime import UTC, datetime

import structlog

from tg_parser.config import settings
from tg_parser.domain.ids import make_processed_document_id
from tg_parser.domain.models import Entity, ProcessedDocument, RawTelegramMessage
from tg_parser.processing.llm import create_llm_client, get_model_id_from_client
from tg_parser.processing.llm.openai_client import OpenAIClient
from tg_parser.processing.ports import LLMClient, ProcessingPipeline
from tg_parser.processing.prompt_loader import PromptLoader, get_prompt_loader
from tg_parser.processing.prompts import (
    PROCESSING_SYSTEM_PROMPT,
    build_processing_prompt,
    get_processing_prompt_name,
)
from tg_parser.storage.ports import ProcessedDocumentRepo, ProcessingFailureRepo

logger = structlog.get_logger(__name__)


def extract_json_from_response(response_text: str) -> str:
    """
    Извлекает JSON из ответа LLM.
    
    Некоторые модели (например, Claude) возвращают JSON обёрнутый
    в markdown code block (```json ... ```). Эта функция извлекает
    чистый JSON из таких ответов.
    
    Args:
        response_text: Сырой текст ответа от LLM
        
    Returns:
        Чистый JSON строка
    """
    if not response_text:
        return response_text
    
    text = response_text.strip()
    
    # Проверяем, обёрнут ли ответ в markdown code block
    # Pattern: ```json\n{...}\n``` или ```\n{...}\n```
    md_pattern = r"```(?:json)?\s*\n?([\s\S]*?)\n?```"
    match = re.search(md_pattern, text)
    if match:
        extracted = match.group(1).strip()
        logger.debug("extracted_json_from_markdown", extracted_length=len(extracted))
        return extracted
    
    # Если начинается с ``` но не соответствует pattern, 
    # попробуем убрать ``` вручную
    if text.startswith("```"):
        lines = text.split("\n")
        # Убираем первую строку (```json или ```) и последнюю (```)
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        return "\n".join(lines).strip()
    
    # Ответ уже чистый JSON
    return text


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
        prompt_loader: PromptLoader | None = None,
    ):
        """
        Args:
            llm_client: LLM клиент для обработки
            processed_doc_repo: Репозиторий processed документов
            failure_repo: Репозиторий ошибок (опционально)
            pipeline_version: Версия pipeline (default из settings)
            model_id: Идентификатор модели (default из client)
            prompt_loader: PromptLoader для загрузки промптов (v1.2)
        """
        self.llm_client = llm_client
        self.processed_doc_repo = processed_doc_repo
        self.failure_repo = failure_repo
        self.pipeline_version = pipeline_version or settings.pipeline_version_processing
        self.prompt_loader = prompt_loader or get_prompt_loader()

        # Model ID извлекаем из client
        if model_id:
            self.model_id = model_id
        elif hasattr(llm_client, "model"):
            self.model_id = llm_client.model
        else:
            self.model_id = "unknown"

        # Загружаем промпты из PromptLoader (v1.2)
        self.system_prompt = self.prompt_loader.get_system_prompt("processing")
        self.user_template = self.prompt_loader.get_user_template("processing")
        
        # Fallback на старые промпты если PromptLoader вернул пустые
        if not self.system_prompt:
            self.system_prompt = PROCESSING_SYSTEM_PROMPT
        if not self.user_template:
            self.user_template = build_processing_prompt("{text}")

        # Вычисляем prompt_id (TR-40)
        if hasattr(llm_client, "compute_prompt_id"):
            self.prompt_id = llm_client.compute_prompt_id(
                self.system_prompt,
                self.user_template,
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
                logger.info("skipping_already_processed", source_ref=message.source_ref)
                # Загружаем существующий документ
                doc = await self.processed_doc_repo.get_by_source_ref(message.source_ref)
                if doc:
                    return doc
                # Если не смогли загрузить, продолжаем обработку
                logger.warning(
                    "exists_but_not_found",
                    source_ref=message.source_ref,
                    issue="exists() returned True but get_by_source_ref() returned None",
                )

        # TR-47: ретраи per-message (Session 23: from retry_settings)
        from tg_parser.config import retry_settings
        
        max_attempts = retry_settings.max_attempts
        backoff_base = retry_settings.backoff_base
        backoff_max = retry_settings.backoff_max
        jitter_factor = retry_settings.jitter

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
                    "message_processed_successfully",
                    source_ref=message.source_ref,
                    attempt=attempt,
                    max_attempts=max_attempts,
                )

                return processed

            except Exception as e:
                last_error = e
                logger.warning(
                    "processing_attempt_failed",
                    source_ref=message.source_ref,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True,
                )

                # Если есть ещё попытки, делаем backoff
                if attempt < max_attempts:
                    # Вычисляем backoff: exponential с cap и jitter
                    delay = min(backoff_base * (2 ** (attempt - 1)), backoff_max)
                    jitter = random.uniform(0, delay * jitter_factor)
                    total_delay = delay + jitter

                    logger.info(
                        "retrying_after_backoff",
                        total_delay_sec=round(total_delay, 2),
                        backoff_sec=delay,
                        backoff_max=backoff_max,
                        jitter_sec=round(jitter, 2),
                        jitter_factor=jitter_factor,
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
            "processing_failed_max_attempts",
            source_ref=message.source_ref,
            max_attempts=max_attempts,
            error=str(last_error),
            error_type=type(last_error).__name__,
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
        # Формируем промпт из template (v1.2: используем PromptLoader)
        user_prompt = self.user_template.format(text=message.text)

        # Загружаем model settings из PromptLoader
        model_settings = self.prompt_loader.get_model_settings("processing")
        temperature = model_settings.get("temperature", settings.llm_temperature)
        max_tokens = model_settings.get("max_tokens", settings.llm_max_tokens)

        # Вызываем LLM
        response_text = await self.llm_client.generate(
            prompt=user_prompt,
            system_prompt=self.system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

        # Извлекаем JSON из ответа (Claude может возвращать в markdown блоке)
        json_text = extract_json_from_response(response_text)
        
        # Парсим JSON ответ
        try:
            response_data = json.loads(json_text)
        except json.JSONDecodeError as e:
            logger.error(
                "failed_to_parse_llm_json",
                error=str(e),
                response_preview=response_text[:500],
                extracted_preview=json_text[:500] if json_text else "EMPTY",
            )
            raise ValueError(f"Invalid JSON response from LLM: {e}") from e

        # Валидируем и нормализуем ответ (v1.1)
        response_data = self._validate_llm_response(response_data)

        # Извлекаем поля
        text_clean = response_data["text_clean"]
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

    def _validate_llm_response(self, response: dict) -> dict:
        """
        Валидировать и нормализовать ответ LLM (v1.1).

        Args:
            response: Parsed JSON от LLM

        Returns:
            Валидированный response с defaults для optional полей

        Raises:
            ValueError: Если критические поля отсутствуют или невалидны
        """
        required_fields = ["text_clean"]
        optional_fields = {
            "summary": None,
            "topics": [],
            "entities": [],
            "language": "unknown",
        }

        # Проверяем required поля
        for field in required_fields:
            if field not in response or not response[field]:
                raise ValueError(f"LLM response missing required field: {field}")

        # Заполняем defaults для optional полей
        for field, default in optional_fields.items():
            if field not in response:
                response[field] = default
                logger.warning(
                    "llm_response_missing_optional_field",
                    field=field,
                    default_value=default,
                )

        # Валидация типов
        if not isinstance(response.get("topics"), list):
            logger.warning("llm_response_topics_not_list", converting=True)
            topics_value = response.get("topics")
            if topics_value:
                response["topics"] = [str(topics_value)]
            else:
                response["topics"] = []

        if not isinstance(response.get("entities"), list):
            logger.warning("llm_response_entities_not_list", converting=True)
            response["entities"] = []

        # Валидация entities
        valid_entities = []
        for i, ent in enumerate(response.get("entities", [])):
            if isinstance(ent, dict) and ent.get("value"):
                # Нормализация confidence
                confidence = ent.get("confidence")
                if confidence is not None:
                    try:
                        confidence = float(confidence)
                        if not (0.0 <= confidence <= 1.0):
                            logger.warning(
                                "entity_confidence_out_of_range",
                                entity_index=i,
                                confidence=confidence,
                                action="clamping",
                            )
                            confidence = max(0.0, min(1.0, confidence))
                        ent["confidence"] = confidence
                    except (TypeError, ValueError):
                        logger.warning(
                            "entity_invalid_confidence",
                            entity_index=i,
                            action="setting_to_none",
                        )
                        ent["confidence"] = None
                valid_entities.append(ent)
            else:
                logger.warning("skipping_invalid_entity", entity_index=i, entity=str(ent)[:100])

        response["entities"] = valid_entities

        return response

    async def process_batch(
        self,
        messages: list[RawTelegramMessage],
        force: bool = False,
        concurrency: int = 1,
    ) -> list[ProcessedDocument]:
        """
        Обработать батч сообщений (с опциональной параллельностью).

        TR-47: ошибка на одном сообщении не должна ронять весь батч.

        Args:
            messages: Список RawTelegramMessage
            force: Переобработать даже если уже есть processed
            concurrency: Максимальное число параллельных запросов (v1.2)

        Returns:
            Список ProcessedDocument (могут быть пропуски при ошибках)
        """
        if concurrency > 1:
            # v1.2: Параллельная обработка
            return await self._process_batch_parallel(messages, force, concurrency)
        else:
            # Последовательная обработка (backward compatible)
            return await self._process_batch_sequential(messages, force)

    async def _process_batch_sequential(
        self,
        messages: list[RawTelegramMessage],
        force: bool = False,
    ) -> list[ProcessedDocument]:
        """
        Последовательная обработка батча сообщений.

        Args:
            messages: Список RawTelegramMessage
            force: Переобработать даже если уже есть processed

        Returns:
            Список ProcessedDocument
        """
        results = []

        for message in messages:
            try:
                processed = await self.process_message(message, force=force)
                results.append(processed)
            except Exception as e:
                # TR-47: не роняем весь батч, логируем и продолжаем
                logger.error(
                    "batch_message_processing_failed",
                    source_ref=message.source_ref,
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True,
                )
                # Продолжаем со следующим сообщением
                continue

        logger.info(
            "batch_processing_complete",
            successful=len(results),
            total=len(messages),
        )

        return results

    async def _process_batch_parallel(
        self,
        messages: list[RawTelegramMessage],
        force: bool = False,
        concurrency: int = 5,
    ) -> list[ProcessedDocument]:
        """
        Параллельная обработка батча сообщений (v1.2).
        
        TR-47: ошибка на одном сообщении не должна ронять весь батч.
        
        Args:
            messages: Список RawTelegramMessage
            force: Переобработать даже если уже есть processed
            concurrency: Максимальное число параллельных запросов
            
        Returns:
            Список ProcessedDocument
        """
        semaphore = asyncio.Semaphore(concurrency)
        results: list[ProcessedDocument] = []

        async def process_with_semaphore(message: RawTelegramMessage) -> ProcessedDocument | None:
            async with semaphore:
                try:
                    return await self.process_message(message, force=force)
                except Exception as e:
                    logger.error(
                        "parallel_message_processing_failed",
                        source_ref=message.source_ref,
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True,
                    )
                    return None

        # Запускаем все задачи параллельно
        tasks = [process_with_semaphore(msg) for msg in messages]
        completed_results = await asyncio.gather(*tasks)

        # Фильтруем None (failed)
        results = [r for r in completed_results if r is not None]

        logger.info(
            "parallel_batch_complete",
            successful=len(results),
            total=len(messages),
            concurrency=concurrency,
        )

        return results


def create_processing_pipeline(
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    processed_doc_repo: ProcessedDocumentRepo | None = None,
    failure_repo: ProcessingFailureRepo | None = None,
) -> ProcessingPipelineImpl:
    """
    Factory function для создания ProcessingPipeline с Multi-LLM поддержкой (v1.2).

    Args:
        provider: LLM провайдер (openai | anthropic | gemini | ollama), default из settings
        api_key: API key провайдера (default из settings)
        model: Модель (default зависит от провайдера)
        base_url: Base URL (для Ollama или OpenAI-compatible прокси)
        processed_doc_repo: Репозиторий документов (required для CLI)
        failure_repo: Репозиторий ошибок (опционально)

    Returns:
        ProcessingPipelineImpl instance
    """
    # Провайдер из аргументов или settings
    provider = provider or settings.llm_provider

    # Получаем API key из аргументов или settings в зависимости от провайдера
    if api_key is None:
        if provider == "openai":
            api_key = settings.openai_api_key
        elif provider == "anthropic":
            api_key = settings.anthropic_api_key
        elif provider == "gemini":
            api_key = settings.gemini_api_key
        elif provider == "ollama":
            # Ollama не требует API key
            api_key = None
        else:
            raise ValueError(f"Unknown LLM provider: {provider}")

    # Проверяем наличие API key (кроме Ollama)
    if provider != "ollama" and not api_key:
        raise ValueError(
            f"{provider.capitalize()} API key not provided. "
            f"Set {provider.upper()}_API_KEY env variable or pass api_key argument."
        )

    # Модель из аргументов или settings
    model = model or settings.llm_model

    # Base URL из аргументов или settings
    base_url = base_url or settings.llm_base_url

    # Session 23: Передаём GPT-5 параметры в OpenAI client
    kwargs = {}
    if provider == "openai":
        kwargs["reasoning_effort"] = settings.llm_reasoning_effort
        kwargs["verbosity"] = settings.llm_verbosity
    
    # Создаём LLM клиент через factory
    llm_client = create_llm_client(
        provider=provider,
        api_key=api_key,
        model=model,
        base_url=base_url,
        **kwargs,
    )

    # Извлекаем model_id из клиента
    model_id = get_model_id_from_client(llm_client)

    logger.info(
        "llm_client_created",
        provider=provider,
        model=model_id,
    )

    # Создаём pipeline
    pipeline = ProcessingPipelineImpl(
        llm_client=llm_client,
        processed_doc_repo=processed_doc_repo,
        failure_repo=failure_repo,
        model_id=model_id,
    )

    return pipeline
