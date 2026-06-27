"""
Async wrapper для Telethon.

Реализует TR-4..TR-17: сбор сообщений и комментариев из Telegram.
"""

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import structlog
from telethon import TelegramClient as TelethonTelegramClient
from telethon.errors import RPCError
from telethon.sessions import SQLiteSession
from telethon.tl.types import Message, MessageEntityTextUrl, MessageEntityUrl

from tg_parser.config.settings import Settings
from tg_parser.domain.ids import make_source_ref
from tg_parser.domain.models import MessageType, RawTelegramMessage
from tg_parser.utils.channel_id import normalize_channel_id

logger = structlog.get_logger(__name__)

# BUG-070: process-wide serialization of Telethon session SQLite access.
#
# The scheduler fans sources out ``scheduler_max_concurrent_sources``-wide
# (default 2 since BUG-068 bumped 1 -> 2 in 1ed86ac). Each source builds its
# OWN ``TelethonClient`` whose underlying ``SQLiteSession`` opens the SAME
# session file (``data/sessions/tg_parser_session.session``). Telethon writes
# to that sqlite on ``connect()`` AND throughout the client's lifetime
# (``process_entities`` / ``set_update_state`` while iterating messages). With
# the session in rollback-journal mode and no busy_timeout, two concurrent
# Telethon clients collided instantly with ``sqlite3.OperationalError:
# database is locked``.
#
# This module-level lock lives here (not in ``ingestion_service``) because it
# guards the *Telethon session resource* itself — a Telethon concern owned by
# this module. Callers wrap the whole client lifetime (connect -> use ->
# disconnect) in ``async with telethon_session_lock():`` so ingestion is
# serialized across concurrent sources while the downstream LLM-bound
# processing / topicization stages stay parallel (``scheduler_max_concurrent_
# sources`` is intentionally left at 2). ``asyncio.Lock`` created at import is
# loop-agnostic until first awaited (Python 3.10+), so the single shared
# instance is safe under one event loop per process.
_SESSION_LOCK = asyncio.Lock()


def telethon_session_lock() -> asyncio.Lock:
    """Return the process-wide lock serializing Telethon session SQLite access."""
    return _SESSION_LOCK


class SessionLockContentionError(RuntimeError):
    """BUG-070 (H1): could not acquire the Telethon session lock in time.

    Raised by :func:`telethon_session_lock_guard` when the process-wide session
    lock is not acquired within the configured wait budget — i.e. a SIBLING
    source legitimately held the Telethon session longer than
    ``scheduler_session_lock_wait_timeout_s``.

    This is a BENIGN, retry-next-tick signal — explicitly DISTINCT from a stuck
    pipeline. The scheduler records it as the ``session_lock_contention``
    outcome (not ``pipeline_timeout`` and not a hard failure) so a source merely
    waiting on a busy session is never mislabeled as a wedged tick and never
    penalizes the source's ``fail_count``.

    Subclasses ``RuntimeError`` only so existing broad ``except RuntimeError``
    guards still treat it as a recoverable per-source error; call sites that
    care (``pipeline_service`` ingest stage) re-raise it un-wrapped so the
    scheduler can classify it.
    """


@contextlib.asynccontextmanager
async def telethon_session_lock_guard(wait_timeout_s: float | None = None):
    """Acquire the process-wide Telethon session lock with an explicit budget.

    BUG-070 (H1): the in-process lock serializes Telethon session SQLite access
    across concurrent sources, but it is acquired DEEP inside the per-source
    pipeline run that the scheduler already wraps in a watchdog
    (``asyncio.wait_for(..., timeout=scheduler_source_timeout_s)``). Plain
    ``async with lock`` would let lock-WAIT time burn that watchdog budget, so a
    sibling merely waiting for a busy session could be cancelled and mislabeled
    ``pipeline_timeout`` even though nothing is stuck.

    This guard instead bounds the *acquire* with its own ``wait_timeout_s``
    budget (via ``asyncio.wait_for(lock.acquire(), ...)``). On timeout it raises
    a dedicated :class:`SessionLockContentionError` (benign, retry-next-tick)
    rather than letting the generic watchdog fire — so lock contention is
    classified distinctly. The wait duration is logged and observed on the
    ``tg_telethon_session_lock_wait_seconds`` histogram (``outcome`` ∈
    {``acquired``, ``contention``}) so contention is observable post-deploy.

    ``wait_timeout_s`` <= 0 / ``None`` falls back to an unbounded wait (legacy
    behaviour), still emitting the wait-duration telemetry.
    """
    lock = _SESSION_LOCK
    start = time.monotonic()
    try:
        if wait_timeout_s is not None and wait_timeout_s > 0:
            # asyncio.Lock.acquire() releases the lock on its own if it is
            # cancelled right after acquiring (CPython 3.10+), so wait_for's
            # cancellation on timeout cannot leak a held lock here.
            await asyncio.wait_for(lock.acquire(), timeout=wait_timeout_s)
        else:
            await lock.acquire()
    except TimeoutError as exc:
        waited = time.monotonic() - start
        logger.warning(
            "telethon_session_lock_contention",
            waited_s=round(waited, 3),
            wait_timeout_s=wait_timeout_s,
        )
        _record_session_lock_wait(waited_s=waited, outcome="contention")
        raise SessionLockContentionError(
            "Timed out waiting for the Telethon session lock after "
            f"{wait_timeout_s}s (a sibling source held the session longer)."
        ) from exc

    waited = time.monotonic() - start
    if waited >= 1.0:
        logger.info("telethon_session_lock_acquired", waited_s=round(waited, 3))
    _record_session_lock_wait(waited_s=waited, outcome="acquired")
    try:
        yield lock
    finally:
        lock.release()


def _record_session_lock_wait(*, waited_s: float, outcome: str) -> None:
    """Observe the session-lock wait duration; never let metrics break ingestion."""
    try:
        from tg_parser.api.metrics import record_session_lock_wait

        record_session_lock_wait(waited_s=waited_s, outcome=outcome)
    except Exception:  # noqa: BLE001 — observability must not break the pipeline
        pass


class _WALSQLiteSession(SQLiteSession):
    """``SQLiteSession`` that enables WAL + busy_timeout on its connection.

    BUG-070 (Part 2, defense-in-depth): Telethon's ``SQLiteSession`` opens its
    own sqlite connection lazily in ``_cursor()`` with default settings
    (rollback journal, no busy_timeout). We override ``_cursor()`` to apply
    ``PRAGMA journal_mode=WAL`` (persisted in the DB header) and
    ``PRAGMA busy_timeout`` (per-connection) the first time each connection is
    created, so a brief concurrent writer waits up to ``busy_timeout`` instead
    of erroring instantly. This also partially mitigates the latent
    cross-container shared-session risk (bot / mcp share the same volume).
    """

    def __init__(self, session_id=None, *, busy_timeout_ms: int = 5000):
        # Set before super().__init__(): the parent constructor calls
        # self._cursor() (our override), which reads _busy_timeout_ms.
        self._busy_timeout_ms = max(0, int(busy_timeout_ms))
        super().__init__(session_id)

    def _cursor(self):
        conn_existed = self._conn is not None
        cursor = super()._cursor()
        # Apply PRAGMAs once per connection (covers initial open and any
        # reopen after close(), where busy_timeout — a per-connection setting —
        # must be re-applied).
        if not conn_existed and self._conn is not None:
            self._conn.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
            self._conn.execute("PRAGMA journal_mode=WAL")
        return cursor


class TelethonClient:
    """
    Async wrapper для Telethon.

    Преобразует Telethon Message → RawTelegramMessage (доменная модель).
    """

    def __init__(self, settings: Settings):
        """
        Инициализировать клиент.

        Args:
            settings: Настройки приложения (включая Telegram API credentials)

        Raises:
            ValueError: если отсутствуют необходимые credentials
        """
        if not settings.telegram_api_id or not settings.telegram_api_hash:
            raise ValueError(
                "Missing Telegram API credentials. "
                "Please set TELEGRAM_API_ID and TELEGRAM_API_HASH in environment or .env file."
            )

        self.settings = settings
        self.client: TelethonTelegramClient | None = None

    async def connect(self) -> None:
        """
        Подключиться к Telegram API.

        Инициализирует Telethon клиент и выполняет авторизацию.
        """
        if self.client:
            return  # Уже подключены

        # BUG-070: use a WAL + busy_timeout session so brief concurrent writers
        # wait instead of erroring with "database is locked". Telethon accepts a
        # Session instance in place of the bare filename string.
        session = _WALSQLiteSession(
            self.settings.telegram_session_name,
            busy_timeout_ms=self.settings.telegram_session_busy_timeout_ms,
        )

        self.client = TelethonTelegramClient(
            session=session,
            api_id=self.settings.telegram_api_id,
            api_hash=self.settings.telegram_api_hash,
        )

        await self.client.start(phone=self.settings.telegram_phone)

    async def disconnect(self) -> None:
        """Отключиться от Telegram API."""
        if self.client:
            await self.client.disconnect()
            self.client = None

    async def get_messages(
        self,
        channel_id: str,
        limit: int | None = None,
        min_id: int | None = None,
        max_id: int | None = None,
    ) -> AsyncIterator[RawTelegramMessage]:
        """
        Получить сообщения канала (посты).

        Args:
            channel_id: ID канала (например "my_channel" или "-1001234567890")
            limit: Максимальное количество сообщений (None = все)
            min_id: Начальный ID сообщения (для incremental mode)
            max_id: Конечный ID сообщения (для ограничения диапазона)

        Yields:
            RawTelegramMessage для каждого поста

        Raises:
            RuntimeError: если клиент не подключен
        """
        if not self.client:
            raise RuntimeError("Client not connected. Call await client.connect() first.")

        # Получаем сообщения через Telethon
        # Логика:
        # - min_id задан (incremental): reverse=True для получения новых после курсора
        # - min_id не задан (snapshot): reverse=False для получения последних N
        use_reverse = min_id is not None

        # Строим kwargs динамически, исключая None (Telethon не принимает None)
        iter_kwargs: dict = {"limit": limit, "reverse": use_reverse}
        if min_id is not None:
            iter_kwargs["min_id"] = min_id
        if max_id is not None:
            iter_kwargs["max_id"] = max_id

        async for message in self.client.iter_messages(channel_id, **iter_kwargs):
            # Фильтруем только обычные сообщения (не service messages)
            if not message.text and not message.message:
                continue

            # Преобразуем в RawTelegramMessage
            raw_msg = await self._convert_message(message, channel_id, MessageType.POST)
            yield raw_msg

    async def get_comments(
        self,
        channel_id: str,
        post_id: int,
        limit: int | None = None,
        min_id: int | None = None,
    ) -> AsyncIterator[RawTelegramMessage]:
        """
        Получить комментарии к посту (TR-7).

        Args:
            channel_id: ID канала
            post_id: ID поста (thread_id)
            limit: Максимальное количество комментариев
            min_id: Начальный ID комментария (для incremental)

        Yields:
            RawTelegramMessage для каждого комментария

        Raises:
            RuntimeError: если клиент не подключен
        """
        if not self.client:
            raise RuntimeError("Client not connected. Call await client.connect() first.")

        try:
            # Получаем комментарии к посту
            # Логика та же: reverse=True только при наличии min_id
            use_reverse = min_id is not None

            # Строим kwargs динамически, исключая None
            iter_kwargs: dict = {
                "reply_to": post_id,
                "limit": limit,
                "reverse": use_reverse,
            }
            if min_id is not None:
                iter_kwargs["min_id"] = min_id

            async for message in self.client.iter_messages(channel_id, **iter_kwargs):
                # Преобразуем в RawTelegramMessage
                raw_msg = await self._convert_message(
                    message,
                    channel_id,
                    MessageType.COMMENT,
                    thread_id=str(post_id),
                )
                yield raw_msg

        except (OSError, RPCError, RuntimeError, ValueError) as e:
            # TR-11: различаем retryable и non-retryable ошибки
            # Если комментарии недоступны для канала, это non-retryable
            if (
                "comments are disabled" in str(e).lower()
                or "discussion not found" in str(e).lower()
            ):
                # Логируем и продолжаем (комментарии недоступны для этого канала)
                return
            else:
                # Проброс других ошибок для retry logic на уровне orchestrator
                raise

    async def _convert_message(
        self,
        message: Message,
        channel_id: str,
        message_type: MessageType,
        thread_id: str | None = None,
    ) -> RawTelegramMessage:
        """
        Преобразовать Telethon Message → RawTelegramMessage.

        Args:
            message: Telethon Message object
            channel_id: ID канала
            message_type: Тип сообщения (post/comment)
            thread_id: ID треда (для комментариев)

        Returns:
            RawTelegramMessage
        """
        # Нормализуем channel_id: убираем @ / кавычки / пробелы (BUG-003 / Session F).
        normalized_channel_id = normalize_channel_id(channel_id) or channel_id

        # ID сообщения
        msg_id = str(message.id)

        # Определяем thread_id и parent_message_id (TR-6)
        if message_type == MessageType.POST:
            # Для постов: thread_id = id, parent_message_id = None
            thread_id_final = msg_id
            parent_message_id = None
        else:
            # Для комментариев: thread_id от поста, parent_message_id от reply
            thread_id_final = thread_id or msg_id
            if message.reply_to and message.reply_to.reply_to_msg_id:
                parent_message_id = str(message.reply_to.reply_to_msg_id)
            else:
                # Если reply недоступен, используем thread_id (TR-6)
                parent_message_id = thread_id_final

        # source_ref (канонический идентификатор)
        source_ref = make_source_ref(normalized_channel_id, message_type.value, msg_id)

        # Текст сообщения
        text = message.text or message.message or ""

        # Дата
        date = message.date.replace(tzinfo=UTC) if message.date else datetime.now(UTC)

        # raw_payload (полный Telethon объект в dict)
        # TR-19: не скачиваем медиа, только метаданные
        raw_payload = {
            "id": message.id,
            "date": message.date.isoformat() if message.date else None,
            "message": message.message,
            "views": message.views,
            "forwards": message.forwards,
            "replies": message.replies.replies if message.replies else None,
            "edit_date": message.edit_date.isoformat() if message.edit_date else None,
            "post_author": message.post_author,
            "grouped_id": message.grouped_id,
            # Медиа метаданные (без скачивания файлов, TR-19)
            "media": self._extract_media_metadata(message) if message.media else None,
        }

        urls = self._extract_urls(message)
        if urls:
            raw_payload["urls"] = urls

        return RawTelegramMessage(
            id=msg_id,
            message_type=message_type,
            source_ref=source_ref,
            channel_id=normalized_channel_id,
            date=date,
            text=text,
            thread_id=thread_id_final,
            parent_message_id=parent_message_id,
            language=None,  # TR-26: язык определяется на этапе processing
            raw_payload=raw_payload,
        )

    @staticmethod
    def _slice_message_text(text: str, offset: int, length: int) -> str:
        """Slice message text by Telegram entity offset/length (UTF-16 code units)."""
        if not text or length <= 0:
            return ""
        utf16 = text.encode("utf-16-le")
        start = offset * 2
        end = (offset + length) * 2
        return utf16[start:end].decode("utf-16-le")

    def _extract_urls(self, message: Message) -> list[dict]:
        """
        Extract external URLs from Telegram message entities.

        Returns list of {"url", "text", "type"} where type is "text_url" or "url".
        """
        if not message.entities:
            return []

        text = message.message or ""
        urls: list[dict] = []
        seen_urls: set[str] = set()

        for entity in message.entities:
            if isinstance(entity, MessageEntityTextUrl):
                visible_text = self._slice_message_text(text, entity.offset, entity.length)
                entry = {"url": entity.url, "text": visible_text, "type": "text_url"}
            elif isinstance(entity, MessageEntityUrl):
                url_text = self._slice_message_text(text, entity.offset, entity.length)
                entry = {"url": url_text, "text": url_text, "type": "url"}
            else:
                continue

            if entry["url"] in seen_urls:
                continue
            seen_urls.add(entry["url"])
            urls.append(entry)

        return urls

    def _extract_media_metadata(self, message: Message) -> dict | None:
        """
        Извлечь метаданные медиа без скачивания файлов (TR-19).

        Args:
            message: Telethon Message

        Returns:
            Dict с метаданными медиа или None
        """
        if not message.media:
            return None

        # Базовая информация о типе медиа
        media_type = type(message.media).__name__

        metadata = {
            "type": media_type,
        }

        # Добавляем дополнительные метаданные в зависимости от типа
        # (без скачивания файлов)
        if hasattr(message.media, "photo"):
            metadata["has_photo"] = True
        if hasattr(message.media, "document"):
            metadata["has_document"] = True
            if hasattr(message.media.document, "mime_type"):
                metadata["mime_type"] = message.media.document.mime_type
            if hasattr(message.media.document, "size"):
                metadata["size_bytes"] = message.media.document.size

        return metadata
