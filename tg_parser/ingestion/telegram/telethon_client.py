"""
Async wrapper для Telethon.

Реализует TR-4..TR-17: сбор сообщений и комментариев из Telegram.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from telethon import TelegramClient as TelethonTelegramClient
from telethon.tl.types import Message

from tg_parser.config.settings import Settings
from tg_parser.domain.ids import make_source_ref
from tg_parser.domain.models import MessageType, RawTelegramMessage


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

        self.client = TelethonTelegramClient(
            session=self.settings.telegram_session_name,
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
        async for message in self.client.iter_messages(
            channel_id,
            limit=limit,
            min_id=min_id,
            max_id=max_id,
            reverse=True,  # От старых к новым (для инкрементального режима)
        ):
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
            async for message in self.client.iter_messages(
                channel_id,
                reply_to=post_id,
                limit=limit,
                min_id=min_id,
                reverse=True,
            ):
                # Преобразуем в RawTelegramMessage
                raw_msg = await self._convert_message(
                    message,
                    channel_id,
                    MessageType.COMMENT,
                    thread_id=str(post_id),
                )
                yield raw_msg

        except Exception as e:
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
        source_ref = make_source_ref(channel_id, message_type.value, msg_id)

        # Текст сообщения
        text = message.text or message.message or ""

        # Дата
        date = (
            message.date.replace(tzinfo=UTC)
            if message.date
            else datetime.now(UTC)
        )

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

        return RawTelegramMessage(
            id=msg_id,
            message_type=message_type,
            source_ref=source_ref,
            channel_id=channel_id,
            date=date,
            text=text,
            thread_id=thread_id_final,
            parent_message_id=parent_message_id,
            language=None,  # TR-26: язык определяется на этапе processing
            raw_payload=raw_payload,
        )

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
