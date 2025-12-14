"""
Unit тесты для TelethonClient.

Проверяет преобразование Telethon Message → RawTelegramMessage.
"""

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from tg_parser.config.settings import Settings
from tg_parser.domain.models import MessageType
from tg_parser.ingestion.telegram import TelethonClient


@pytest.fixture
def test_settings():
    """Создать тестовые настройки."""
    return Settings(
        telegram_api_id=12345,
        telegram_api_hash="test_hash",
        telegram_phone="+1234567890",
    )


class TestTelethonClient:
    """Unit тесты для TelethonClient."""

    def test_client_initialization(self, test_settings):
        """Тест инициализации клиента с credentials."""
        client = TelethonClient(test_settings)
        assert client.settings == test_settings
        assert client.client is None  # Не подключен

    def test_client_initialization_without_credentials(self):
        """Тест что клиент требует credentials."""
        settings = Settings(
            telegram_api_id=None,
            telegram_api_hash=None,
        )

        with pytest.raises(ValueError, match="Missing Telegram API credentials"):
            TelethonClient(settings)

    @pytest.mark.asyncio
    async def test_convert_message_post(self, test_settings):
        """Тест преобразования Telethon Message → RawTelegramMessage (post)."""
        client = TelethonClient(test_settings)

        # Создаём mock Telethon Message для поста
        mock_message = Mock()
        mock_message.id = 123
        mock_message.text = "Test message"
        mock_message.message = "Test message"
        mock_message.date = datetime(2025, 12, 14, 10, 0, 0, tzinfo=UTC)
        mock_message.reply_to = None
        mock_message.views = 100
        mock_message.forwards = 5
        mock_message.replies = None
        mock_message.edit_date = None
        mock_message.post_author = "Test Author"
        mock_message.grouped_id = None
        mock_message.media = None

        # Преобразуем
        raw_msg = await client._convert_message(
            message=mock_message,
            channel_id="test_channel",
            message_type=MessageType.POST,
        )

        # Проверяем результат
        assert raw_msg.id == "123"
        assert raw_msg.message_type == MessageType.POST
        assert raw_msg.source_ref == "tg:test_channel:post:123"
        assert raw_msg.channel_id == "test_channel"
        assert raw_msg.text == "Test message"
        assert raw_msg.date == datetime(2025, 12, 14, 10, 0, 0, tzinfo=UTC)
        assert raw_msg.thread_id == "123"  # Для постов thread_id = id
        assert raw_msg.parent_message_id is None  # Для постов нет parent
        assert raw_msg.language is None  # TR-26: язык определяется на processing
        assert raw_msg.raw_payload is not None

    @pytest.mark.asyncio
    async def test_convert_message_comment(self, test_settings):
        """Тест преобразования комментария (TR-6)."""
        client = TelethonClient(test_settings)

        # Mock reply_to
        mock_reply_to = Mock()
        mock_reply_to.reply_to_msg_id = 100

        # Создаём mock комментария
        mock_message = Mock()
        mock_message.id = 456
        mock_message.text = "Test comment"
        mock_message.message = "Test comment"
        mock_message.date = datetime(2025, 12, 14, 10, 5, 0, tzinfo=UTC)
        mock_message.reply_to = mock_reply_to
        mock_message.views = None
        mock_message.forwards = None
        mock_message.replies = None
        mock_message.edit_date = None
        mock_message.post_author = None
        mock_message.grouped_id = None
        mock_message.media = None

        # Преобразуем
        raw_msg = await client._convert_message(
            message=mock_message,
            channel_id="test_channel",
            message_type=MessageType.COMMENT,
            thread_id="100",
        )

        # Проверяем результат (TR-6)
        assert raw_msg.id == "456"
        assert raw_msg.message_type == MessageType.COMMENT
        assert raw_msg.source_ref == "tg:test_channel:comment:456"
        assert raw_msg.channel_id == "test_channel"
        assert raw_msg.thread_id == "100"  # ID корневого поста
        assert raw_msg.parent_message_id == "100"  # ID сообщения на которое отвечает

    @pytest.mark.asyncio
    async def test_extract_media_metadata(self, test_settings):
        """Тест извлечения метаданных медиа (TR-19)."""
        client = TelethonClient(test_settings)

        # Mock document media
        mock_document = Mock()
        mock_document.mime_type = "application/pdf"
        mock_document.size = 1024000

        mock_media = Mock()
        mock_media.document = mock_document

        mock_message = Mock()
        mock_message.media = mock_media

        # Извлекаем метаданные
        metadata = client._extract_media_metadata(mock_message)

        # Проверяем что НЕ скачали файл (TR-19), только метаданные
        assert metadata is not None
        assert "type" in metadata
        assert metadata.get("has_document") is True
        assert metadata.get("mime_type") == "application/pdf"
        assert metadata.get("size_bytes") == 1024000

    @pytest.mark.asyncio
    async def test_extract_media_metadata_no_media(self, test_settings):
        """Тест что для сообщений без медиа возвращается None."""
        client = TelethonClient(test_settings)

        mock_message = Mock()
        mock_message.media = None

        metadata = client._extract_media_metadata(mock_message)
        assert metadata is None
