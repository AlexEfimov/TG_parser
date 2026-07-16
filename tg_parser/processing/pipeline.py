"""
Processing pipeline implementation.

Реализует ProcessingPipeline: обработка RawTelegramMessage → ProcessedDocument.
Требования: TR-21..TR-26, TR-46..TR-49.
"""

import asyncio
import inspect
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
from tg_parser.processing.llm.errors import (
    AnthropicBillingError,
    LLMCallTimeoutError,
    LLMJsonParseError,
)
from tg_parser.processing.ports import LLMClient, ProcessingPipeline
from tg_parser.processing.prompt_loader import PromptLoader, get_prompt_loader
from tg_parser.processing.prompts import (
    PROCESSING_COMMENT_USER_PROMPT_TEMPLATE,
    PROCESSING_SYSTEM_PROMPT,
    build_processing_prompt,
    get_processing_prompt_name,
)
from tg_parser.storage.ports import ProcessedDocumentRepo, ProcessingFailureRepo, RawMessageRepo
from tg_parser.utils.prompt_render import render_prompt

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# BUG-067 (B2b) — failure categories for the bounded-retry / cooldown logic.
# ---------------------------------------------------------------------------
_FAILURE_BILLING = "billing"  # temporary — clears on balance top-up
_FAILURE_PARSE = "parse"  # sticky — e.g. BUG-065 irreparable JSON
_FAILURE_TIMEOUT = "timeout"  # BUG-068 A1 aggregate wall-clock timeout (transient)
_FAILURE_OTHER = "other"  # generic / transient


def _categorize_failure(error_class: str | None) -> str:
    """Map a recorded ``processing_failures.error_class`` to a cooldown category.

    N3 note: the per-tick ``_DocFailure.category`` (incl. ``timeout``) is a
    write-only annotation stored in ``error_details_json``; the NEXT tick's
    cooldown decision is driven solely by this function reading the persisted
    ``error_class``. ``LLMCallTimeoutError`` is transient, so it maps to
    ``other`` (the default short cooldown) — never retried *within* a tick
    (see ``llm_only``) but eligible again after the default cooldown.
    """
    if error_class == "AnthropicBillingError":
        return _FAILURE_BILLING
    if error_class == "LLMJsonParseError":
        return _FAILURE_PARSE
    return _FAILURE_OTHER


def _parse_failure_ts(value: str | None) -> datetime | None:
    """Parse a ``processing_failures.last_attempt_at`` string into aware UTC.

    Returns ``None`` for missing/unparseable values so the caller treats the
    failure as "no usable cooldown timestamp" and does NOT hide the doc.
    """
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


class _DocFailure:
    """A per-document failure carried out of the parallel worker (BUG-067 B2b).

    Distinct from ``None`` (which historically meant "this doc failed") so the
    batch can record the REAL ``error_class`` + cooldown ``category`` instead of
    the old hardcoded ``error_class="ProcessingError"`` — the category is what
    lets the next tick differentiate temporary (billing) from sticky (parse)
    failures for the cooldown/budget decision.
    """

    __slots__ = ("source_ref", "channel_id", "category", "error_class", "error_message")

    def __init__(
        self,
        source_ref: str,
        channel_id: str,
        category: str,
        error_class: str,
        error_message: str,
    ):
        self.source_ref = source_ref
        self.channel_id = channel_id
        self.category = category
        self.error_class = error_class
        self.error_message = error_message


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

        # S3 (O-2 / F-01): pre-LLM dedup. Hash the RAW text and, if an exact
        # repost already exists in this channel, materialise a provenance row and
        # return it WITHOUT the (paid) LLM call. The lookup + upsert run under the
        # same lock as the post-LLM dedup to keep the check-then-write atomic.
        if settings.dedup_enabled and not force:
            raw_hash = self._compute_raw_hash(message)
            if raw_hash is not None:
                async with self._db_lock:
                    existing = await self._find_pre_llm_duplicate(
                        message.channel_id, raw_hash, message.source_ref
                    )
                    if existing is not None:
                        mirror = self._build_dedup_mirror(message, existing, raw_hash)
                        await self.processed_doc_repo.upsert(mirror)
                        if self.failure_repo:
                            await self.failure_repo.delete_failure(message.source_ref)
                        from tg_parser.api.metrics import record_pre_llm_dedup_hit

                        record_pre_llm_dedup_hit(channel_id=message.channel_id)
                        logger.info(
                            "pre_llm_dedup_hit",
                            source_ref=message.source_ref,
                            duplicate_of=existing.source_ref,
                            channel_id=message.channel_id,
                            raw_content_hash=raw_hash,
                        )
                        return mirror

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

        # Pick the appropriate template (F9 Phase 2: safe-render — braces in
        # channel text must not crash str.format).
        if is_comment and parent_context:
            user_prompt = render_prompt(
                self.comment_user_template,
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
            user_prompt = render_prompt(self.user_template, text=message.text)

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

        # S3 (O-2): stash the RAW-text hash so a future tick can dedup an exact
        # repost/forward BEFORE the (paid) LLM call. Hash space is the raw
        # message.text (pre-LLM), distinct from content_hash below which hashes
        # the post-LLM text_clean. Only set for non-empty text (media-only never
        # reaches here). No schema change — lives in the free-form metadata JSON.
        if settings.dedup_enabled and message.text and message.text.strip():
            metadata["raw_content_hash"] = compute_content_hash(
                message.text,
                strip_url_query=settings.dedup_strip_url_query,
            )

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
        *,
        bypass_failure_cooldown: bool = False,
    ) -> list[ProcessedDocument]:
        """
        Обработать батч сообщений (с опциональной параллельностью).

        TR-47: ошибка на одном сообщении не должна ронять весь батч.

        Args:
            messages: Список RawTelegramMessage
            force: Переобработать даже если уже есть processed
            concurrency: Максимальное число параллельных запросов (v1.2)
            bypass_failure_cooldown: BUG-067 B2b — when True (e.g. an explicit
                ``retry_failed`` run) the failure-cooldown skip is NOT applied,
                so a deliberately-retried doc is sent to the LLM even if it is
                still inside its cooldown window.

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
            return await self._process_batch_parallel(
                messages,
                force,
                concurrency,
                bypass_failure_cooldown=bypass_failure_cooldown,
            )
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

    # ------------------------------------------------------------------
    # S3 (O-2 / O-8): pre-LLM dedup helpers
    # ------------------------------------------------------------------

    def _compute_raw_hash(self, message: RawTelegramMessage) -> str | None:
        """Hash of the RAW Telegram text for pre-LLM dedup (None if empty)."""
        if not message.text or not message.text.strip():
            return None
        return compute_content_hash(
            message.text,
            strip_url_query=settings.dedup_strip_url_query,
        )

    def _build_dedup_mirror(
        self,
        message: RawTelegramMessage,
        original: ProcessedDocument,
        raw_hash: str,
    ) -> ProcessedDocument:
        """S3 (O-2): build a NEW persisted row for an exact repost of ``original``.

        Unlike the post-LLM dedup path (which returns the existing doc and writes
        nothing), the pre-LLM path materialises a traceable row: it carries the
        repost's own ``source_ref``/``id``/``source_message_id``/``processed_at``
        but mirrors the original's LLM-derived fields (``text_clean``, ``summary``,
        ``topics``, ``entities``, ``language``, ``content_hash``). Provenance is
        kept via ``metadata['dedup_of']`` (original ``source_ref``) and the
        repost's own ``metadata['raw_content_hash']`` so future reposts match it.
        """
        meta = dict(original.metadata or {})
        meta["raw_content_hash"] = raw_hash
        meta["dedup_of"] = original.source_ref
        return ProcessedDocument(
            id=make_processed_document_id(message.source_ref),
            source_ref=message.source_ref,
            source_message_id=message.id,
            channel_id=message.channel_id,
            processed_at=datetime.now(UTC),
            text_clean=original.text_clean,
            summary=original.summary,
            topics=list(original.topics),
            entities=list(original.entities),
            language=original.language,
            metadata=meta,
            content_hash=original.content_hash,
        )

    @staticmethod
    async def _maybe_await(value):
        """Return the awaited result if ``value`` is awaitable, else ``None``.

        Lets the batched repo lookups degrade gracefully when a test double lacks
        the method (a plain ``MagicMock`` attribute returns a non-awaitable), so
        the pre-LLM/O-8 paths simply fall back to "no hits" instead of raising.
        Real repos and ``AsyncMock`` return coroutines and are awaited normally.
        """
        if inspect.isawaitable(value):
            return await value
        return None

    async def _find_by_raw_content_hashes(
        self,
        channel_id: str,
        raw_hashes: list[str],
    ) -> dict[str, ProcessedDocument]:
        """Guarded call to the (PG-specific) cross-tick raw-hash lookup."""
        if not raw_hashes:
            return {}
        method = getattr(self.processed_doc_repo, "find_by_raw_content_hashes", None)
        if method is None:
            return {}
        result = await self._maybe_await(method(channel_id=channel_id, raw_hashes=list(raw_hashes)))
        return result or {}

    async def _find_by_content_hashes(
        self,
        channel_id: str,
        content_hashes: list[str],
    ) -> dict[str, ProcessedDocument]:
        """Guarded call to the batched content-hash lookup (O-8)."""
        if not content_hashes:
            return {}
        method = getattr(self.processed_doc_repo, "find_by_content_hashes", None)
        if method is None:
            return {}
        result = await self._maybe_await(
            method(channel_id=channel_id, content_hashes=list(content_hashes))
        )
        return result or {}

    async def _persist_dedup_mirrors(
        self,
        mirrors: list[ProcessedDocument],
    ) -> list[ProcessedDocument]:
        """Persist pre-LLM dedup mirror rows, clear their failures, count hits.

        Bypasses ``_filter_duplicates`` deliberately — a mirror shares its
        original's ``content_hash`` and would otherwise be dropped as a post-LLM
        duplicate. Runs in the serial post-gather phase (no ``db_lock`` needed,
        same as ``_persist_chunk``).
        """
        if not mirrors:
            return []
        if hasattr(self.processed_doc_repo, "upsert_batch"):
            await self.processed_doc_repo.upsert_batch(mirrors)
        else:
            for m in mirrors:
                await self.processed_doc_repo.upsert(m)
        if self.failure_repo:
            for m in mirrors:
                await self.failure_repo.delete_failure(m.source_ref)
        from tg_parser.api.metrics import record_pre_llm_dedup_hit

        for m in mirrors:
            record_pre_llm_dedup_hit(channel_id=m.channel_id)
            logger.info(
                "pre_llm_dedup_hit",
                source_ref=m.source_ref,
                duplicate_of=(m.metadata or {}).get("dedup_of"),
                channel_id=m.channel_id,
                raw_content_hash=(m.metadata or {}).get("raw_content_hash"),
            )
        return mirrors

    async def _find_pre_llm_duplicate(
        self,
        channel_id: str,
        raw_hash: str,
        self_source_ref: str,
    ) -> ProcessedDocument | None:
        """Return an existing cross-tick document matching ``raw_hash`` (or None).

        Ignores a self-match (same ``source_ref``) so a re-process of the same
        message is never treated as its own duplicate.
        """
        hits = await self._find_by_raw_content_hashes(channel_id, [raw_hash])
        existing = hits.get(raw_hash)
        if existing is not None and existing.source_ref != self_source_ref:
            return existing
        return None

    async def _batch_existing_source_refs(self, source_refs: list[str]) -> set[str]:
        """S3 (O-8 / F-09): one batched lookup of already-processed source_refs.

        Replaces the per-message ``exists()`` fan-out in the parallel Phase 1.
        In the tick path the messages are already ``NOT EXISTS``-filtered by the
        SQL selection, so this is usually a tiny result; in non-tick paths it
        preserves the "skip already-processed" correctness with one round-trip.
        Degrades to an empty set for test doubles lacking ``get_by_source_refs``.
        """
        if not source_refs:
            return set()
        method = getattr(self.processed_doc_repo, "get_by_source_refs", None)
        if method is None:
            return set()
        result = await self._maybe_await(method(list(source_refs)))
        if not result:
            return set()
        return set(result.keys())

    async def _filter_duplicates(
        self,
        docs: list[ProcessedDocument],
    ) -> tuple[list[ProcessedDocument], dict[str, ProcessedDocument]]:
        """F5-A Phase 3: remove within-batch + DB duplicates from ``docs``.

        Preserves input order for kept documents. Emits one log + metric per
        duplicate detected. Duplicates without a ``content_hash`` (e.g.
        legacy/empty-text) always pass through.

        Returns ``(unique, dropped_to_canonical)`` — the second dict maps each
        DROPPED doc's ``source_ref`` to the canonical surviving doc it collapsed
        into (the earlier in-batch doc or the existing DB row). S3 uses this so a
        within-tick pre-LLM repost whose leader is dropped here (e.g. the leader
        matched a legacy DB row without ``metadata['raw_content_hash']``) can
        still be mirrored against that canonical doc instead of being deferred
        forever while the leader re-burns the LLM every tick.

        Called in the serial post-gather phase of ``_process_batch_parallel``;
        no ``db_lock`` is needed (matches ``upsert_batch`` pattern — same
        serial phase, no concurrent DB access).
        """
        from tg_parser.api.metrics import record_dedup_duplicate_detected

        # S3 (O-8): one batched DB lookup per channel instead of a per-document
        # ``find_by_content_hash`` fan-out (~20 queries per chunk → 1). A tick is
        # single-channel in practice, but grouping keeps correctness if a chunk
        # ever spans channels. Cross-chunk dedup still holds: earlier chunks are
        # already persisted, so their hashes are returned by this query.
        hashes_by_channel: dict[str, set[str]] = {}
        for doc in docs:
            if doc.content_hash:
                hashes_by_channel.setdefault(doc.channel_id, set()).add(doc.content_hash)
        db_hits: dict[tuple[str, str], ProcessedDocument] = {}
        for ch, hashes in hashes_by_channel.items():
            found = await self._find_by_content_hashes(ch, list(hashes))
            for h, existing in found.items():
                db_hits[(ch, h)] = existing

        seen: dict[tuple[str, str], ProcessedDocument] = {}
        dropped_to_canonical: dict[str, ProcessedDocument] = {}
        unique: list[ProcessedDocument] = []
        for doc in docs:
            if not doc.content_hash:
                unique.append(doc)
                continue
            key = (doc.channel_id, doc.content_hash)
            if key in seen:
                canonical = seen[key]
                dropped_to_canonical[doc.source_ref] = canonical
                record_dedup_duplicate_detected(channel_id=doc.channel_id)
                logger.info(
                    "dedup_within_batch_duplicate",
                    source_ref=doc.source_ref,
                    duplicate_of=canonical.source_ref,
                    channel_id=doc.channel_id,
                    content_hash=doc.content_hash,
                )
                continue
            existing = db_hits.get(key)
            if existing is not None and existing.source_ref != doc.source_ref:
                dropped_to_canonical[doc.source_ref] = existing
                record_dedup_duplicate_detected(channel_id=doc.channel_id)
                logger.info(
                    "dedup_db_duplicate",
                    source_ref=doc.source_ref,
                    duplicate_of=existing.source_ref,
                    channel_id=doc.channel_id,
                    content_hash=doc.content_hash,
                )
                continue
            seen[key] = doc
            unique.append(doc)
        return unique, dropped_to_canonical

    async def _persist_chunk(
        self,
        chunk: list[ProcessedDocument],
        force: bool,
    ) -> tuple[list[ProcessedDocument], dict[str, ProcessedDocument]]:
        """Dedup + persist one chunk of completed docs, clearing their failures.

        Partial-batch-loss fix: each chunk is committed as it completes, so an
        interrupted tick (A2 watchdog cancel / hang / restart) keeps the
        already-completed (paid-for) chunks instead of discarding the whole
        batch at a single end-of-batch ``upsert_batch``.

        Cross-chunk dedup still holds: ``_filter_duplicates`` checks the DB via
        ``find_by_content_hash``, and earlier chunks are already persisted, so a
        duplicate spanning two chunks of the same tick is still caught. N5:
        chunks group by LLM COMPLETION order (``as_completed``), not input order
        — irrelevant to correctness since dedup is keyed on content_hash, not
        position.
        """
        docs = chunk
        dropped_to_canonical: dict[str, ProcessedDocument] = {}
        if settings.dedup_enabled and docs and not force:
            docs, dropped_to_canonical = await self._filter_duplicates(docs)
        if not docs:
            return [], dropped_to_canonical
        if hasattr(self.processed_doc_repo, "upsert_batch"):
            await self.processed_doc_repo.upsert_batch(docs)
        else:
            for doc in docs:
                await self.processed_doc_repo.upsert(doc)
        # A previously-failed doc that now succeeds must clear its failure row
        # (so it is not cooldown-skipped on the next tick). N2: ``upsert_batch``
        # and ``delete_failure`` commit independently (they share the proc
        # session but each COMMITs), so a cancel between them can leave an orphan
        # stale failure row. That is harmless: Phase 1 checks ``exists()`` FIRST,
        # so a persisted doc is never consulted against its failure record (no
        # re-burn, no wrong skip). upsert-then-delete is the safe ordering;
        # delete-first would risk re-burning a paid doc if cancelled between.
        if self.failure_repo:
            for doc in docs:
                await self.failure_repo.delete_failure(doc.source_ref)
        return docs, dropped_to_canonical

    async def _process_batch_parallel(
        self,
        messages: list[RawTelegramMessage],
        force: bool = False,
        concurrency: int = 5,
        *,
        bypass_failure_cooldown: bool = False,
    ) -> list[ProcessedDocument]:
        """
        Параллельная обработка батча сообщений (v1.2, Perf-b2).

        LLM calls run fully parallel (semaphore-bounded). Completed docs are
        persisted INCREMENTALLY in chunks as they finish (partial-batch-loss
        fix) rather than a single end-of-batch write.

        BUG-067 B2b: the already-processed skip filter ALSO consults
        ``failure_repo`` so a doc that has already failed is skipped until its
        category-specific cooldown elapses (or its parse-attempt budget is
        exhausted) — the main lever against re-sending the whole failed backlog
        to the LLM every tick.

        TR-47: ошибка на одном сообщении не должна ронять весь батч.
        """
        t0 = time.perf_counter()
        self._batch_input_tokens = 0
        self._batch_output_tokens = 0
        self._batch_billing_blocked = 0
        self._batch_cooldown_skipped = 0
        self._batch_attempted = 0
        self._batch_pre_llm_dedup = 0
        self._batch_pre_llm_deferred = 0
        semaphore = asyncio.Semaphore(concurrency)

        channel_id = messages[0].channel_id if messages else None

        # BUG-067 B2b: load this channel's existing failures once so the skip
        # filter can apply per-category cooldowns and the recorder can carry a
        # cumulative (cross-tick) attempt count. Resilient: a read error (or a
        # test double lacking list_failures) degrades to "no cooldown data".
        # N4: list_failures has no LIMIT, but the result set is bounded by the
        # channel's failure count (one row per failed source_ref, cleared on
        # success) — far smaller than the raw backlog and a single indexed read.
        failure_map: dict[str, dict] = {}
        if self.failure_repo and channel_id and not force:
            try:
                for f in await self.failure_repo.list_failures(channel_id=channel_id):
                    failure_map[str(f["source_ref"])] = f
            except Exception as e:  # noqa: BLE001 — best-effort, never block processing
                logger.warning("failure_cooldown_load_failed", error=str(e))
                failure_map = {}

        # Phase 1: filter already-processed + cooldown-skip prior failures.
        # S3 (O-8 / F-09): the per-message ``exists()`` fan-out is replaced by a
        # single batched ``get_by_source_refs`` lookup. In the tick path the
        # selection SQL already applied ``NOT EXISTS (processed_documents)``
        # (raw_message_repo), so this returns (almost) nothing; the loop is kept
        # because it also computes ``cooldown_skipped_refs`` and it preserves
        # correctness for non-tick callers whose messages are not pre-filtered.
        if not force:
            existing_refs = await self._batch_existing_source_refs([m.source_ref for m in messages])
            cooldown_skipped_refs: set[str] = set()
            now = datetime.now(UTC)
            cooldown_active = settings.failure_cooldown_enabled and not bypass_failure_cooldown
            for msg in messages:
                if msg.source_ref in existing_refs:
                    continue
                if cooldown_active:
                    record = failure_map.get(msg.source_ref)
                    if record is not None and self._should_skip_failed(record, now):
                        cooldown_skipped_refs.add(msg.source_ref)
            to_process = [
                m
                for m in messages
                if m.source_ref not in existing_refs and m.source_ref not in cooldown_skipped_refs
            ]
            skipped = len(existing_refs)
            self._batch_cooldown_skipped = len(cooldown_skipped_refs)
        else:
            existing_refs = set()
            to_process = list(messages)
            skipped = 0

        # Phase 1.5 (S3 / O-2): pre-LLM dedup of exact reposts BEFORE the LLM.
        # Splits ``to_process`` into (a) docs that actually go to the LLM and
        # (b) exact reposts handled without a paid call. Two hit kinds:
        #   - cross-tick: raw hash matches an already-persisted doc (built now);
        #   - within-tick: raw hash first appears in THIS batch (mirror built
        #     after the leader is processed, resolved in the persist phase).
        # ``leader_by_key`` / ``within_tick_dups`` are keyed by (channel_id,
        # raw_hash) so a repost is only ever matched against a same-channel
        # leader (dedup is per-channel; batches are single-channel in practice
        # but the key stays correct if that ever changes).
        cross_tick_mirrors: list[ProcessedDocument] = []
        within_tick_dups: list[tuple[RawTelegramMessage, tuple[str, str]]] = []
        leader_by_key: dict[tuple[str, str], str] = {}
        if settings.dedup_enabled and not force and to_process:
            msg_raw_hash: dict[str, str] = {}
            for msg in to_process:
                rh = self._compute_raw_hash(msg)
                if rh is not None:
                    msg_raw_hash[msg.source_ref] = rh
            cross_hits: dict[str, ProcessedDocument] = {}
            if msg_raw_hash and channel_id:
                cross_hits = await self._find_by_raw_content_hashes(
                    channel_id, list(set(msg_raw_hash.values()))
                )
            filtered: list[RawTelegramMessage] = []
            for msg in to_process:
                rh = msg_raw_hash.get(msg.source_ref)
                if rh is None:
                    filtered.append(msg)
                    continue
                key = (msg.channel_id, rh)
                existing = cross_hits.get(rh)
                if existing is not None and existing.source_ref != msg.source_ref:
                    cross_tick_mirrors.append(self._build_dedup_mirror(msg, existing, rh))
                elif key in leader_by_key:
                    within_tick_dups.append((msg, key))
                else:
                    leader_by_key[key] = msg.source_ref
                    filtered.append(msg)
            to_process = filtered

        # Fix 2 (HIGH): docs actually attempted (sent to the LLM) THIS tick —
        # the post-filter, post-cooldown list. Exposed via process_stats so the
        # scheduler's B1 degraded ratio is computed over real attempts, not the
        # whole channel backlog (which re-appends already-processed docs and
        # would dilute fail_ratio to ~0 on any established channel). S3: pre-LLM
        # dedup hits are NOT attempts (never sent to the LLM) and are excluded
        # here, keeping ``attempted`` = "sent to the LLM".
        self._batch_attempted = len(to_process)

        if skipped:
            logger.info("parallel_batch_skipped_existing", skipped=skipped)
        if self._batch_cooldown_skipped:
            logger.info(
                "parallel_batch_failure_cooldown_skipped",
                cooldown_skipped=self._batch_cooldown_skipped,
                channel_id=channel_id,
            )

        # Phase 2: parallel LLM calls; persist completed docs in chunks.
        llm_t0 = time.perf_counter()

        async def llm_only(message: RawTelegramMessage) -> ProcessedDocument | _DocFailure:
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
                            return _DocFailure(
                                source_ref=message.source_ref,
                                channel_id=message.channel_id,
                                category=_FAILURE_BILLING,
                                error_class="AnthropicBillingError",
                                error_message=str(e),
                            )
                        last_error = e
                        # Fix 1 (HIGH): LLMCallTimeoutError is the BUG-068 (A1)
                        # aggregate wall-clock timeout. It MUST NOT fall through
                        # to the generic retry path — retrying would burn
                        # max_attempts × anthropic_call_timeout_s on a single
                        # hung doc. Fail fast (one attempt) like the parse case.
                        # Checked before LLMJsonParseError purely for clarity;
                        # the two classes are disjoint.
                        if isinstance(e, LLMCallTimeoutError):
                            logger.error(
                                "processing_call_timeout_non_retryable",
                                source_ref=message.source_ref,
                                error=str(e),
                            )
                            return _DocFailure(
                                source_ref=message.source_ref,
                                channel_id=message.channel_id,
                                category=_FAILURE_TIMEOUT,
                                error_class="LLMCallTimeoutError",
                                error_message=str(e),
                            )
                        # BUG-019: malformed JSON already exhausted the inner
                        # hinted-retry loop — non-retryable here (no 3x3 blow-up).
                        if isinstance(e, LLMJsonParseError):
                            logger.error(
                                "processing_json_parse_non_retryable",
                                source_ref=message.source_ref,
                                error=str(e),
                            )
                            return _DocFailure(
                                source_ref=message.source_ref,
                                channel_id=message.channel_id,
                                category=_FAILURE_PARSE,
                                error_class="LLMJsonParseError",
                                error_message=str(e),
                            )
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
                return _DocFailure(
                    source_ref=message.source_ref,
                    channel_id=message.channel_id,
                    category=_FAILURE_OTHER,
                    error_class=type(last_error).__name__ if last_error else "ProcessingError",
                    error_message=str(last_error) if last_error else "Failed after retries",
                )

        async def _record_doc_failure(f: _DocFailure) -> None:
            """Persist one failure's cooldown row with the REAL class + category +
            cumulative (cross-tick) attempt count.

            Fix 3(b): called AS each ``_DocFailure`` arrives (not after the whole
            loop) so an A2-watchdog cancel mid-batch still records
            attempts/last_attempt_at for the failures that already completed —
            otherwise those docs would carry no updated cooldown and be re-burned
            immediately on the next tick. These are the only failure writes; no
            bulk write happens at the end.
            """
            if not self.failure_repo:
                return
            prev = failure_map.get(f.source_ref)
            prev_attempts = int(prev.get("attempts") or 0) if prev else 0
            await self.failure_repo.record_failure(
                source_ref=f.source_ref,
                channel_id=f.channel_id,
                attempts=prev_attempts + 1,
                error_class=f.error_class,
                error_message=f.error_message,
                error_details={"category": f.category},
            )

        chunk_size = max(1, settings.processing_persist_chunk_size)
        persisted: list[ProcessedDocument] = []
        doc_failures: list[_DocFailure] = []
        pending: list[ProcessedDocument] = []
        # S3: leaders dropped by post-LLM _filter_duplicates → the canonical doc
        # they collapsed into. Lets a within-tick repost whose leader was deduped
        # away here still be mirrored (not deferred forever).
        dropped_to_canonical: dict[str, ProcessedDocument] = {}

        tasks = [asyncio.create_task(llm_only(msg)) for msg in to_process]
        db_duration = 0.0
        try:
            for fut in asyncio.as_completed(tasks):
                result = await fut
                if isinstance(result, _DocFailure):
                    doc_failures.append(result)
                    await _record_doc_failure(result)
                    continue
                pending.append(result)
                if len(pending) >= chunk_size:
                    db_t0 = time.perf_counter()
                    chunk_persisted, chunk_dropped = await self._persist_chunk(pending, force)
                    persisted.extend(chunk_persisted)
                    dropped_to_canonical.update(chunk_dropped)
                    db_duration += time.perf_counter() - db_t0
                    pending = []
            if pending:
                db_t0 = time.perf_counter()
                chunk_persisted, chunk_dropped = await self._persist_chunk(pending, force)
                persisted.extend(chunk_persisted)
                dropped_to_canonical.update(chunk_dropped)
                db_duration += time.perf_counter() - db_t0
                pending = []
        except (asyncio.CancelledError, Exception) as e:
            # Interrupted mid-batch (A2 watchdog cancel / hang / unexpected
            # error). N1: chunk persistence is atomic per transaction —
            # ``_persist_chunk`` → ``upsert_batch`` is a single COMMIT — so every
            # already-persisted chunk is durable and the in-flight (unpersisted)
            # sub-chunk is simply dropped (no partial-chunk corruption, no DB
            # write during unwind). Failures that already arrived were recorded
            # incrementally (Fix 3b), so their cooldown rows survive too.
            for t in tasks:
                if not t.done():
                    t.cancel()
            # Fix 3(a): await the cancelled children so they fully unwind BEFORE
            # re-raising — bounds in-flight token burn and avoids
            # "Task was destroyed but it is pending". return_exceptions=True so a
            # child CancelledError/exception cannot mask the original error.
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except asyncio.CancelledError:
                pass
            logger.warning(
                "parallel_batch_interrupted",
                persisted=len(persisted),
                dropped_in_flight=len(pending),
                recorded_failures=len(doc_failures),
                channel_id=channel_id,
                error_type=type(e).__name__,
            )
            raise
        llm_duration = time.perf_counter() - llm_t0

        self._batch_billing_blocked = sum(1 for f in doc_failures if f.category == _FAILURE_BILLING)

        # S3 (O-2): materialise pre-LLM dedup mirror rows. Cross-tick mirrors were
        # built in Phase 1.5; within-tick duplicates are resolved now against
        # their leader's canonical doc: the leader's freshly-persisted row OR, if
        # the leader was itself dropped by post-LLM ``_filter_duplicates`` (e.g.
        # it matched a legacy DB row lacking ``metadata['raw_content_hash']``),
        # the existing doc it collapsed into. Resolving against that canonical row
        # is what stops the repost being deferred forever while the leader
        # re-burns the LLM every tick (the mirror carries the raw hash, so the
        # next tick the leader itself resolves cross-tick). Only a leader that
        # truly FAILED (no doc at all) leaves its duplicate deferred. Mirrors
        # bypass ``_filter_duplicates`` on purpose (they intentionally share the
        # original's content_hash) and count under the pre-LLM metric only.
        mirror_docs = list(cross_tick_mirrors)
        within_resolved = 0
        if within_tick_dups:
            persisted_by_ref = {d.source_ref: d for d in persisted}
            for msg, key in within_tick_dups:
                leader_ref = leader_by_key.get(key)
                leader_doc = None
                if leader_ref:
                    leader_doc = persisted_by_ref.get(leader_ref) or dropped_to_canonical.get(
                        leader_ref
                    )
                if leader_doc is not None:
                    mirror_docs.append(self._build_dedup_mirror(msg, leader_doc, key[1]))
                    within_resolved += 1
        persisted_mirrors = await self._persist_dedup_mirrors(mirror_docs)
        self._batch_pre_llm_dedup = len(persisted_mirrors)
        # A within-tick repost whose leader FAILED to persist gets no mirror this
        # tick; it was already excluded from ``to_process`` (never sent to the
        # LLM), so it must be surfaced as DEFERRED (skipped) — not counted as a
        # failure by ``run_processing`` (total − processed − skipped). Otherwise a
        # repost burst with a failing leader could push fail_ratio above 100% and
        # falsely flag the tick degraded. It is retried next tick.
        self._batch_pre_llm_deferred = len(within_tick_dups) - within_resolved

        # Collect already-processed docs for the return value
        results = list(persisted)
        results.extend(persisted_mirrors)
        if not force and skipped > 0:
            for msg in messages:
                if msg.source_ref in existing_refs:
                    doc = await self.processed_doc_repo.get_by_source_ref(msg.source_ref)
                    if doc:
                        results.append(doc)

        elapsed = time.perf_counter() - t0
        logger.info(
            "parallel_batch_complete",
            successful=len(persisted),
            skipped=skipped,
            cooldown_skipped=self._batch_cooldown_skipped,
            pre_llm_dedup=self._batch_pre_llm_dedup,
            failed=len(doc_failures),
            billing_blocked=self._batch_billing_blocked,
            total=len(messages),
            concurrency=concurrency,
            chunk_size=chunk_size,
            elapsed_sec=round(elapsed, 3),
            llm_sec=round(llm_duration, 3),
            db_write_sec=round(db_duration, 3),
            avg_per_msg_sec=round(llm_duration / max(len(to_process), 1), 3),
            input_tokens=self._batch_input_tokens,
            output_tokens=self._batch_output_tokens,
            total_tokens=self._batch_input_tokens + self._batch_output_tokens,
        )

        return results

    def _should_skip_failed(self, record: dict, now: datetime) -> bool:
        """BUG-067 B2b: decide whether a prior-failure doc is still in cooldown.

        - billing (temporary): skip while within ``failure_billing_cooldown_s``.
        - parse (sticky): within budget → short ``failure_default_cooldown_s``
          (≈ one tick, not 3x/tick); once ``failure_parse_max_attempts`` is
          exhausted → long ``failure_parse_cooldown_s``.
        - other/transient: short ``failure_default_cooldown_s``.

        An unparseable/missing ``last_attempt_at`` returns False (never hide a
        doc on bad metadata).
        """
        last = _parse_failure_ts(record.get("last_attempt_at"))
        if last is None:
            return False
        age_s = (now - last).total_seconds()
        # Fix 5: legacy rows wrote last_attempt_at in naive LOCAL time before the
        # UTC switch; parsed-as-UTC on a non-UTC host they can land in the FUTURE
        # → negative age → the doc would stay cooldown-skipped far beyond intent.
        # Treat a future-dated timestamp as expired (do not skip). One-time:
        # affects only pre-UTC-switch rows.
        if age_s < 0:
            return False
        category = _categorize_failure(record.get("error_class"))
        attempts = int(record.get("attempts") or 0)
        if category == _FAILURE_BILLING:
            return age_s < settings.failure_billing_cooldown_s
        if category == _FAILURE_PARSE:
            if attempts >= settings.failure_parse_max_attempts:
                return age_s < settings.failure_parse_cooldown_s
            return age_s < settings.failure_default_cooldown_s
        return age_s < settings.failure_default_cooldown_s


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
