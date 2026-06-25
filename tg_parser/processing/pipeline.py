"""
Processing pipeline implementation.

Реализует ProcessingPipeline: обработка RawTelegramMessage → ProcessedDocument.
Требования: TR-21..TR-26, TR-46..TR-49.
"""

import asyncio
import json
import random
import re
import time
from datetime import UTC, datetime

import structlog
from sqlalchemy.exc import SQLAlchemyError

from tg_parser.config import settings
from tg_parser.domain.hashing import compute_content_hash
from tg_parser.domain.ids import make_processed_document_id
from tg_parser.domain.models import (
    Entity,
    MessageType,
    ProcessedDocument,
    RawTelegramMessage,
)
from tg_parser.processing.llm import create_llm_client, get_model_id_from_client, resolve_llm_config
from tg_parser.processing.llm.errors import AnthropicBillingError, LLMJsonParseError
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


def _repair_unescaped_quotes(text: str) -> str:
    """Escape unescaped inner double-quotes inside JSON string values.

    BUG-065: the processing LLM (notably Anthropic ``claude-haiku-4-5``) writes
    verbatim message text into the ``text_clean`` string value WITHOUT escaping
    inner ``"`` characters, producing invalid JSON (``Expecting ',' delimiter``
    mid-string). This is a conservative single-pass state machine: a ``"`` seen
    inside a string is treated as the *closing* quote only when the next
    non-whitespace character is the structural delimiter that legitimately
    follows that string (``:`` for an object key; ``,`` / ``}`` / ``]`` / EOF
    for a value). Any other ``"`` is an unescaped inner quote and is escaped.

    It tracks object/array context so a key string and a value string use the
    correct expected delimiter, which keeps already-valid JSON untouched.
    """
    out: list[str] = []
    stack: list[str] = []  # container stack: "{" (object) or "[" (array)
    expecting_key = False  # next string opened is an object key
    in_string = False
    string_is_key = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_string:
            if ch == "\\":
                # Copy the escape sequence (\" \\ \n …) verbatim.
                out.append(ch)
                if i + 1 < n:
                    out.append(text[i + 1])
                    i += 2
                else:
                    i += 1
                continue
            if ch == '"':
                j = i + 1
                while j < n and text[j] in " \t\r\n":
                    j += 1
                nxt = text[j] if j < n else ""
                if string_is_key:
                    closes = nxt in (":", "")
                else:
                    closes = nxt in (",", "}", "]", "")
                if closes:
                    out.append(ch)
                    in_string = False
                else:
                    # Unescaped inner quote → escape it.
                    out.append('\\"')
                i += 1
                continue
            out.append(ch)
            i += 1
            continue

        # Outside a string: track structural context.
        if ch == '"':
            in_string = True
            string_is_key = expecting_key
        elif ch == "{":
            stack.append("{")
            expecting_key = True
        elif ch == "[":
            stack.append("[")
            expecting_key = False
        elif ch in ("}", "]"):
            if stack:
                stack.pop()
            expecting_key = False
        elif ch == ",":
            expecting_key = bool(stack) and stack[-1] == "{"
        elif ch == ":":
            expecting_key = False
        out.append(ch)
        i += 1
    return "".join(out)


def _strip_trailing_commas(text: str) -> str:
    """Remove commas immediately preceding ``}`` / ``]`` (string-aware).

    Operates outside string literals only, so a comma inside a value (e.g.
    ``"a, ]"``) is never touched.
    """
    out: list[str] = []
    in_string = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                # Trailing comma → drop it.
                i += 1
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def repair_json(text: str) -> str:
    """Best-effort, dependency-free repair of malformed LLM JSON (BUG-065).

    Applies two conservative passes — escaping unescaped inner double-quotes in
    string values and stripping trailing commas — and returns the (possibly
    unchanged) text. Callers must re-run :func:`json.loads`; the repair never
    parses on its own and is only invoked after a real ``JSONDecodeError``.
    """
    if not text:
        return text
    repaired = _repair_unescaped_quotes(text)
    repaired = _strip_trailing_commas(repaired)
    return repaired


# BUG-019: corrective hint appended to the user prompt on a JSON-parse retry.
# The first attempt prompt is left untouched; subsequent attempts append this so
# the model is steered back to valid JSON without bumping temperature/seed. A
# single helper keeps the four retry sites (processing + 3 topicization stages)
# from drifting apart.
_JSON_RETRY_HINT = (
    "\n\nIMPORTANT: your previous response could not be parsed as JSON. "
    "Return ONLY a single valid JSON object matching the schema described above, "
    "with no markdown fences, prose, or commentary. Do not repeat the previous "
    "malformed output."
)


def apply_json_retry_hint(base_prompt: str, attempt: int) -> str:
    """Return ``base_prompt`` unchanged on the first attempt, hinted afterwards.

    ``attempt`` is 1-based: attempt 1 (first try) is verbatim; attempts >= 2
    (which only happen after a prior JSON-parse failure) append
    :data:`_JSON_RETRY_HINT`.
    """
    if attempt <= 1:
        return base_prompt
    return base_prompt + _JSON_RETRY_HINT


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

        # Token usage accumulators (reset per batch)
        self._batch_input_tokens = 0
        self._batch_output_tokens = 0

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

                # DB writes serialised via lock (session is not task-safe).
                # F5-A Phase 3: dedup check is inside the SAME lock as upsert
                # to close the TOCTOU window (a concurrent task could otherwise
                # insert a duplicate between the check and the upsert).
                async with self._db_lock:
                    if settings.dedup_enabled and processed.content_hash and not force:
                        existing = await self.processed_doc_repo.find_by_content_hash(
                            channel_id=message.channel_id,
                            content_hash=processed.content_hash,
                        )
                        if existing is not None and existing.source_ref != message.source_ref:
                            from tg_parser.api.metrics import (
                                record_dedup_duplicate_detected,
                            )

                            record_dedup_duplicate_detected(channel_id=message.channel_id)
                            logger.info(
                                "dedup_duplicate_found",
                                source_ref=message.source_ref,
                                duplicate_of=existing.source_ref,
                                channel_id=message.channel_id,
                                content_hash=processed.content_hash,
                            )
                            return existing

                    await self.processed_doc_repo.upsert(processed)
                    if self.failure_repo:
                        await self.failure_repo.delete_failure(message.source_ref)

                from tg_parser.api.metrics import record_message_processed

                record_message_processed(channel_id=message.channel_id, success=True)

                logger.info(
                    "message_processed_successfully",
                    source_ref=message.source_ref,
                    attempt=attempt,
                    max_attempts=max_attempts,
                )

                return processed

            except Exception as e:
                if isinstance(e, AnthropicBillingError):
                    from tg_parser.api.metrics import record_anthropic_billing_block

                    record_anthropic_billing_block(stage="processing")
                    logger.error(
                        "anthropic_billing_block_processing",
                        source_ref=message.source_ref,
                        error=str(e),
                    )
                    raise
                last_error = e
                # BUG-019: the inner _process_single_message loop already
                # exhausted the hinted JSON retries; do not re-retry malformed
                # JSON at the outer layer (would multiply LLM cost). Record the
                # failure below and stop.
                if isinstance(e, LLMJsonParseError):
                    logger.error(
                        "processing_json_parse_non_retryable",
                        source_ref=message.source_ref,
                        error=str(e),
                    )
                    break
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

        from tg_parser.api.metrics import record_message_processed

        record_message_processed(channel_id=message.channel_id, success=False)

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

        # BUG-019: own the JSON-parse retry here so the OUTER process_message
        # loop can treat malformed JSON as non-retryable (no 3x3 blow-up). The
        # first attempt prompt is verbatim; later attempts append a corrective
        # hint. Transient HTTP/network errors are NOT caught here — they bubble
        # up to the outer loop which still retries them.
        from tg_parser.config import retry_settings

        max_json_attempts = retry_settings.max_attempts
        response_data: dict | None = None
        last_json_error: json.JSONDecodeError | None = None
        for attempt in range(1, max_json_attempts + 1):
            prompt = apply_json_retry_hint(user_prompt, attempt)
            if attempt > 1:
                from tg_parser.api.metrics import record_llm_json_parse_retry

                record_llm_json_parse_retry(stage="processing")

            llm_response = await self.llm_client.generate_with_usage(
                prompt=prompt,
                system_prompt=self.system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            response_text = llm_response.text
            self._batch_input_tokens += llm_response.input_tokens
            self._batch_output_tokens += llm_response.output_tokens

            # Извлекаем JSON из ответа (Claude может возвращать в markdown блоке)
            json_text = extract_json_from_response(response_text)

            try:
                response_data = json.loads(json_text)
                break
            except json.JSONDecodeError as e:
                # BUG-065: provider-agnostic pure-Python repair pass BEFORE the
                # attempt is counted as failed. Anthropic (and most providers'
                # json-mode is a no-op) emit unescaped inner quotes in
                # text_clean → invalid JSON; repair escapes those + strips
                # trailing commas, then we re-parse. Only fall through to the
                # failure path if the repaired parse ALSO fails.
                repaired_text = repair_json(json_text)
                if repaired_text != json_text:
                    try:
                        response_data = json.loads(repaired_text)
                        logger.info(
                            "recovered_llm_json_via_repair",
                            attempt=attempt,
                            original_error=str(e),
                        )
                        break
                    except json.JSONDecodeError:
                        pass
                last_json_error = e
                logger.error(
                    "failed_to_parse_llm_json",
                    error=str(e),
                    attempt=attempt,
                    max_attempts=max_json_attempts,
                    response_preview=response_text[:500],
                    extracted_preview=json_text[:500] if json_text else "EMPTY",
                )

        if response_data is None:
            raise LLMJsonParseError(
                f"Invalid JSON response from LLM after {max_json_attempts} attempts: "
                f"{last_json_error}"
            ) from last_json_error

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

        urls = (message.raw_payload or {}).get("urls") or []
        if urls:
            metadata["urls"] = urls

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

        # F5-A Phase 3: content-hash for dedup (post-LLM over stable text_clean).
        if processed.text_clean:
            processed.content_hash = compute_content_hash(
                processed.text_clean,
                strip_url_query=settings.dedup_strip_url_query,
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
        except SQLAlchemyError as e:
            logger.debug("failed_to_load_parent_from_processed", error=str(e))

        if self.raw_repo:
            try:
                parent_raw = await self.raw_repo.get_by_source_ref(parent_ref)
                if parent_raw and parent_raw.text:
                    return parent_raw.text[:PARENT_CONTEXT_MAX_CHARS]
            except SQLAlchemyError as e:
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

        urls = (message.raw_payload or {}).get("urls") or []
        if urls:
            metadata["urls"] = urls

        processed = ProcessedDocument(
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

        # F5-A Phase 3: hash the synthetic media descriptor for within-channel
        # dedup of repeated media-only posts.
        if processed.text_clean:
            processed.content_hash = compute_content_hash(
                processed.text_clean,
                strip_url_query=settings.dedup_strip_url_query,
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
        t0 = time.perf_counter()
        self._batch_input_tokens = 0
        self._batch_output_tokens = 0
        results = []

        for message in messages:
            try:
                processed = await self.process_message(message, force=force)
                results.append(processed)
            except Exception as e:
                logger.error(
                    "batch_message_processing_failed",
                    source_ref=message.source_ref,
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True,
                )
                continue

        elapsed = time.perf_counter() - t0
        logger.info(
            "batch_processing_complete",
            successful=len(results),
            total=len(messages),
            elapsed_sec=round(elapsed, 3),
            avg_per_msg_sec=round(elapsed / max(len(messages), 1), 3),
            input_tokens=self._batch_input_tokens,
            output_tokens=self._batch_output_tokens,
            total_tokens=self._batch_input_tokens + self._batch_output_tokens,
        )

        return results

    async def _filter_duplicates(
        self,
        docs: list[ProcessedDocument],
    ) -> list[ProcessedDocument]:
        """F5-A Phase 3: remove within-batch + DB duplicates from ``docs``.

        Preserves input order for kept documents. Emits one log + metric per
        duplicate detected. Duplicates without a ``content_hash`` (e.g.
        legacy/empty-text) always pass through.

        Called in the serial post-gather phase of ``_process_batch_parallel``;
        no ``db_lock`` is needed (matches ``upsert_batch`` pattern — same
        serial phase, no concurrent DB access).
        """
        from tg_parser.api.metrics import record_dedup_duplicate_detected

        seen: dict[tuple[str, str], str] = {}
        unique: list[ProcessedDocument] = []
        for doc in docs:
            if not doc.content_hash:
                unique.append(doc)
                continue
            key = (doc.channel_id, doc.content_hash)
            if key in seen:
                record_dedup_duplicate_detected(channel_id=doc.channel_id)
                logger.info(
                    "dedup_within_batch_duplicate",
                    source_ref=doc.source_ref,
                    duplicate_of=seen[key],
                    channel_id=doc.channel_id,
                    content_hash=doc.content_hash,
                )
                continue
            existing = await self.processed_doc_repo.find_by_content_hash(
                channel_id=doc.channel_id,
                content_hash=doc.content_hash,
            )
            if existing is not None and existing.source_ref != doc.source_ref:
                record_dedup_duplicate_detected(channel_id=doc.channel_id)
                logger.info(
                    "dedup_db_duplicate",
                    source_ref=doc.source_ref,
                    duplicate_of=existing.source_ref,
                    channel_id=doc.channel_id,
                    content_hash=doc.content_hash,
                )
                continue
            seen[key] = doc.source_ref
            unique.append(doc)
        return unique

    async def _process_batch_parallel(
        self,
        messages: list[RawTelegramMessage],
        force: bool = False,
        concurrency: int = 5,
    ) -> list[ProcessedDocument]:
        """
        Параллельная обработка батча сообщений (v1.2, Perf-b2).

        LLM calls run fully parallel (semaphore-bounded).
        DB writes are batched in a single transaction after all LLM calls complete.

        TR-47: ошибка на одном сообщении не должна ронять весь батч.
        """
        t0 = time.perf_counter()
        self._batch_input_tokens = 0
        self._batch_output_tokens = 0
        semaphore = asyncio.Semaphore(concurrency)

        # Phase 1: filter already-processed (single DB query)
        if not force:
            existing_refs = set()
            for msg in messages:
                if await self.processed_doc_repo.exists(msg.source_ref):
                    existing_refs.add(msg.source_ref)
            to_process = [m for m in messages if m.source_ref not in existing_refs]
            skipped = len(existing_refs)
        else:
            to_process = list(messages)
            skipped = 0

        if skipped:
            logger.info("parallel_batch_skipped_existing", skipped=skipped)

        # Phase 2: parallel LLM calls (no DB writes)
        llm_t0 = time.perf_counter()

        async def llm_only(message: RawTelegramMessage) -> ProcessedDocument | None:
            async with semaphore:
                from tg_parser.config import retry_settings

                max_attempts = retry_settings.max_attempts
                backoff_base = retry_settings.backoff_base
                backoff_max = retry_settings.backoff_max
                jitter_factor = retry_settings.jitter
                last_error = None

                for attempt in range(1, max_attempts + 1):
                    try:
                        return await self._process_single_message(message)
                    except Exception as e:
                        if isinstance(e, AnthropicBillingError):
                            from tg_parser.api.metrics import record_anthropic_billing_block

                            record_anthropic_billing_block(stage="processing")
                            logger.error(
                                "anthropic_billing_block_processing",
                                source_ref=message.source_ref,
                                error=str(e),
                            )
                            return None
                        last_error = e
                        # BUG-019: malformed JSON already exhausted the inner
                        # hinted-retry loop — non-retryable here (no 3x3 blow-up).
                        if isinstance(e, LLMJsonParseError):
                            logger.error(
                                "processing_json_parse_non_retryable",
                                source_ref=message.source_ref,
                                error=str(e),
                            )
                            break
                        logger.warning(
                            "processing_attempt_failed",
                            source_ref=message.source_ref,
                            attempt=attempt,
                            max_attempts=max_attempts,
                            error=str(e),
                        )
                        if attempt < max_attempts:
                            delay = min(backoff_base * (2 ** (attempt - 1)), backoff_max)
                            jitter = random.uniform(0, delay * jitter_factor)
                            await asyncio.sleep(delay + jitter)

                logger.error(
                    "parallel_message_processing_failed",
                    source_ref=message.source_ref,
                    error=str(last_error),
                    error_type=type(last_error).__name__,
                )
                return None

        tasks = [llm_only(msg) for msg in to_process]
        completed_results = await asyncio.gather(*tasks)
        llm_duration = time.perf_counter() - llm_t0

        new_docs = [r for r in completed_results if r is not None]
        failed_refs = [
            m.source_ref for m, r in zip(to_process, completed_results, strict=False) if r is None
        ]

        # F5-A Phase 3: within-batch + DB dedup (force bypasses).
        # Visible behaviour: batch may return fewer docs than len(messages)
        # when duplicates are detected. Documented in USER_GUIDE.
        if settings.dedup_enabled and new_docs and not force:
            new_docs = await self._filter_duplicates(new_docs)

        # Phase 3: batch DB write
        db_t0 = time.perf_counter()
        if new_docs and hasattr(self.processed_doc_repo, "upsert_batch"):
            await self.processed_doc_repo.upsert_batch(new_docs)
        elif new_docs:
            for doc in new_docs:
                await self.processed_doc_repo.upsert(doc)
        db_duration = time.perf_counter() - db_t0

        # Phase 4: record failures
        if failed_refs and self.failure_repo:
            for ref in failed_refs:
                await self.failure_repo.record_failure(
                    source_ref=ref,
                    channel_id=to_process[0].channel_id if to_process else "unknown",
                    attempts=3,
                    error_class="ProcessingError",
                    error_message="Failed after retries in parallel batch",
                )

        # Delete failure records for successfully processed
        if self.failure_repo:
            for doc in new_docs:
                await self.failure_repo.delete_failure(doc.source_ref)

        # Collect already-processed docs for the return value
        results = list(new_docs)
        if not force and skipped > 0:
            for msg in messages:
                if msg.source_ref in existing_refs:
                    doc = await self.processed_doc_repo.get_by_source_ref(msg.source_ref)
                    if doc:
                        results.append(doc)

        elapsed = time.perf_counter() - t0
        logger.info(
            "parallel_batch_complete",
            successful=len(new_docs),
            skipped=skipped,
            failed=len(failed_refs),
            total=len(messages),
            concurrency=concurrency,
            elapsed_sec=round(elapsed, 3),
            llm_sec=round(llm_duration, 3),
            db_write_sec=round(db_duration, 3),
            avg_per_msg_sec=round(llm_duration / max(len(to_process), 1), 3),
            input_tokens=self._batch_input_tokens,
            output_tokens=self._batch_output_tokens,
            total_tokens=self._batch_input_tokens + self._batch_output_tokens,
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
        "processing",
        settings=app_settings,
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
