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
from tg_parser.domain.models import (
    Entity,
    MessageType,
    ProcessedDocument,
    RawTelegramMessage,
)
from tg_parser.processing.llm import create_llm_client, get_model_id_from_client, resolve_llm_config
from tg_parser.processing.ports import LLMClient, ProcessingPipeline
from tg_parser.processing.prompt_loader import PromptLoader, get_prompt_loader
from tg_parser.processing.prompts import (
    PROCESSING_COMMENT_USER_PROMPT_TEMPLATE,
    PROCESSING_SYSTEM_PROMPT,
    build_processing_prompt,
    get_processing_prompt_name,
)
from tg_parser.storage.ports import ProcessedDocumentRepo, ProcessingFailureRepo, RawMessageRepo

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


PARENT_CONTEXT_MAX_CHARS = 500


def _describe_media(media: dict) -> str:
    """Generate a synthetic text descriptor for media-only messages."""
    media_type = media.get("type", "")
    if "Photo" in media_type or media.get("has_photo"):
        return "[Фото]"
    mime_type = media.get("mime_type", "")
    if mime_type.startswith("audio/"):
        return "[Голосовое сообщение]"
    if mime_type.startswith("video/"):
        return "[Видео]"
    if media.get("has_document"):
        return f"[Документ: {mime_type}]" if mime_type else "[Документ]"
    return "[Медиа]"


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
        raw_repo: RawMessageRepo | None = None,
        pipeline_version: str | None = None,
        model_id: str | None = None,
        prompt_loader: PromptLoader | None = None,
        llm_temperature: float = 0.0,
        llm_max_tokens: int = 4096,
    ):
        """
        Args:
            llm_client: LLM клиент для обработки
            processed_doc_repo: Репозиторий processed документов
            failure_repo: Репозиторий ошибок (опционально)
            raw_repo: Репозиторий raw сообщений (для загрузки контекста родительского поста)
            pipeline_version: Версия pipeline (default: "v1.0")
            model_id: Идентификатор модели (default из client)
            prompt_loader: PromptLoader для загрузки промптов (v1.2)
            llm_temperature: Default LLM temperature for processing calls
            llm_max_tokens: Default LLM max_tokens for processing calls
        """
        self.llm_client = llm_client
        self.processed_doc_repo = processed_doc_repo
        self.failure_repo = failure_repo
        self.raw_repo = raw_repo
        self._db_lock = asyncio.Lock()
        self.pipeline_version = pipeline_version or "v1.0"
        self.prompt_loader = prompt_loader or get_prompt_loader()
        self.llm_temperature = llm_temperature
        self.llm_max_tokens = llm_max_tokens

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
        self.comment_user_template = self.prompt_loader.get_comment_user_template("processing")
        
        # Fallback на старые промпты если PromptLoader вернул пустые
        if not self.system_prompt:
            self.system_prompt = PROCESSING_SYSTEM_PROMPT
        if not self.user_template:
            self.user_template = build_processing_prompt("{text}")
        if not self.comment_user_template:
            self.comment_user_template = PROCESSING_COMMENT_USER_PROMPT_TEMPLATE

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
        # TR-46/TR-48: проверяем существование (under lock — session is not task-safe)
        if not force:
            async with self._db_lock:
                exists = await self.processed_doc_repo.exists(message.source_ref)
                if exists:
                    logger.info("skipping_already_processed", source_ref=message.source_ref)
                    doc = await self.processed_doc_repo.get_by_source_ref(message.source_ref)
                    if doc:
                        return doc
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
                # LLM call runs WITHOUT lock — this is the parallel bottleneck
                processed = await self._process_single_message(message)

                # DB writes serialised via lock (session is not task-safe)
                async with self._db_lock:
                    await self.processed_doc_repo.upsert(processed)
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

                if attempt < max_attempts:
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
            async with self._db_lock:
                await self.failure_repo.record_failure(
                    source_ref=message.source_ref,
                    channel_id=message.channel_id,
                    attempts=max_attempts,
                    error_class=type(last_error).__name__,
                    error_message=str(last_error),
                )

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
        # Media-only: generate synthetic document without LLM call
        if not message.text or not message.text.strip():
            return self._build_media_only_document(message)

        is_comment = message.message_type == MessageType.COMMENT

        # Load parent post context for comments
        parent_context = None
        if is_comment and message.thread_id:
            parent_context = await self._load_parent_context(message)

        # Pick the appropriate template
        if is_comment and parent_context:
            user_prompt = self.comment_user_template.format(
                text=message.text,
                parent_text=parent_context,
            )
            logger.info(
                "processing_comment_with_parent_context",
                source_ref=message.source_ref,
                parent_post=f"post:{message.thread_id}",
                parent_context_len=len(parent_context),
            )
        else:
            user_prompt = self.user_template.format(text=message.text)

        # Загружаем model settings из PromptLoader
        model_settings = self.prompt_loader.get_model_settings("processing")
        temperature = model_settings.get("temperature", self.llm_temperature)
        max_tokens = model_settings.get("max_tokens", self.llm_max_tokens)

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
                "temperature": self.llm_temperature,
                "max_tokens": self.llm_max_tokens,
            },
        }
        
        # TR-6: добавляем thread metadata для комментариев
        if message.parent_message_id or message.thread_id:
            metadata["parent_message_id"] = message.parent_message_id
            metadata["thread_id"] = message.thread_id

        if is_comment and parent_context:
            metadata["has_parent_context"] = True

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

    async def _load_parent_context(self, message: RawTelegramMessage) -> str | None:
        """
        Load parent post text for a comment message.

        Tries processed_doc_repo first (for text_clean), then raw_repo as fallback.

        Returns:
            Parent post text (truncated to PARENT_CONTEXT_MAX_CHARS) or None
        """
        parent_ref = f"tg:{message.channel_id}:post:{message.thread_id}"

        try:
            parent_doc = await self.processed_doc_repo.get_by_source_ref(parent_ref)
            if parent_doc and parent_doc.text_clean:
                return parent_doc.text_clean[:PARENT_CONTEXT_MAX_CHARS]
        except Exception as e:
            logger.debug("failed_to_load_parent_from_processed", error=str(e))

        if self.raw_repo:
            try:
                parent_raw = await self.raw_repo.get_by_source_ref(parent_ref)
                if parent_raw and parent_raw.text:
                    return parent_raw.text[:PARENT_CONTEXT_MAX_CHARS]
            except Exception as e:
                logger.debug("failed_to_load_parent_from_raw", error=str(e))

        logger.warning(
            "parent_context_not_found",
            source_ref=message.source_ref,
            parent_ref=parent_ref,
        )
        return None

    def _build_media_only_document(self, message: RawTelegramMessage) -> ProcessedDocument:
        """
        Build a ProcessedDocument for media-only messages without LLM call.

        Generates synthetic text_clean from media metadata.
        """
        media = (message.raw_payload or {}).get("media")
        if media:
            text_clean = _describe_media(media)
        else:
            text_clean = "[Пустое сообщение]"

        logger.info(
            "media_only_synthetic_document",
            source_ref=message.source_ref,
            text_clean=text_clean,
        )

        metadata = {
            "pipeline_version": self.pipeline_version,
            "model_id": self.model_id,
            "prompt_id": "media_only_synthetic",
            "prompt_name": "media_only",
            "parameters": {"temperature": 0, "max_tokens": 0},
            "media_only": True,
        }
        if message.parent_message_id or message.thread_id:
            metadata["parent_message_id"] = message.parent_message_id
            metadata["thread_id"] = message.thread_id

        return ProcessedDocument(
            id=make_processed_document_id(message.source_ref),
            source_ref=message.source_ref,
            source_message_id=message.id,
            channel_id=message.channel_id,
            processed_at=datetime.now(UTC),
            text_clean=text_clean,
            summary=None,
            topics=[],
            entities=[],
            language="unknown",
            metadata=metadata,
        )

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
        requested = concurrency

        if concurrency > 1 and hasattr(self.llm_client, "suggest_processing_concurrency"):
            concurrency = self.llm_client.suggest_processing_concurrency(concurrency)

        if concurrency != requested:
            logger.info(
                "processing_concurrency_adjusted",
                requested=requested,
                effective=concurrency,
            )

        logger.info(
            "processing_batch_start",
            total_messages=len(messages),
            concurrency=concurrency,
            mode="parallel" if concurrency > 1 else "sequential",
        )

        if concurrency > 1:
            return await self._process_batch_parallel(messages, force, concurrency)
        else:
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
    raw_repo: RawMessageRepo | None = None,
    app_settings=None,
) -> ProcessingPipelineImpl:
    """
    Factory function for creating ProcessingPipeline with Multi-LLM support.

    Args:
        provider: LLM provider (openai | anthropic | gemini | ollama), default from settings
        api_key: Provider API key (default from settings)
        model: Model override (default depends on provider)
        base_url: Base URL (for Ollama or OpenAI-compatible proxies)
        processed_doc_repo: Document repository
        failure_repo: Failure repository (optional)
        app_settings: Optional Settings. Falls back to global singleton if not provided.

    Returns:
        ProcessingPipelineImpl instance
    """
    if app_settings is None:
        app_settings = settings

    resolved_provider, resolved_api_key, resolved_model = resolve_llm_config(
        "processing", settings=app_settings,
    )
    provider = provider or resolved_provider
    api_key = api_key or resolved_api_key
    model = model or resolved_model

    if provider != "ollama" and not api_key:
        raise ValueError(
            f"{provider.capitalize()} API key not provided. "
            f"Set {provider.upper()}_API_KEY env variable or pass api_key argument."
        )

    base_url = base_url or app_settings.llm_base_url

    kwargs = {}
    if provider == "openai":
        kwargs["reasoning_effort"] = app_settings.llm_reasoning_effort
        kwargs["verbosity"] = app_settings.llm_verbosity
    
    llm_client = create_llm_client(
        provider=provider,
        api_key=api_key,
        model=model,
        base_url=base_url,
        settings=app_settings,
        **kwargs,
    )

    # Извлекаем model_id из клиента
    model_id = get_model_id_from_client(llm_client)

    logger.info(
        "processing_llm_client_created",
        stage="processing",
        provider=provider,
        model=model_id,
    )

    # Создаём pipeline
    pipeline = ProcessingPipelineImpl(
        llm_client=llm_client,
        processed_doc_repo=processed_doc_repo,
        failure_repo=failure_repo,
        raw_repo=raw_repo,
        model_id=model_id,
        llm_temperature=app_settings.llm_temperature,
        llm_max_tokens=app_settings.llm_max_tokens,
    )

    return pipeline
