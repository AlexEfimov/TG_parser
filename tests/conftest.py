"""
Конфигурация pytest для TG_parser.

Общие фикстуры и helpers для тестов.
"""

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from tg_parser.config.settings import Settings
from tg_parser.domain.models import MessageType, RawTelegramMessage
from tg_parser.storage.sqlite import Database, DatabaseConfig


# ============================================================================
# Database Fixtures
# ============================================================================


@pytest.fixture
async def test_db():
    """
    Создать временную тестовую БД.

    Возвращает настроенный Database объект с временными файлами.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        config = DatabaseConfig(
            ingestion_state_path=tmppath / "test_ingestion_state.db",
            raw_storage_path=tmppath / "test_raw_storage.db",
            processing_storage_path=tmppath / "test_processing_storage.db",
        )

        db = Database(config)
        await db.init()

        try:
            yield db
        finally:
            await db.close()


@pytest.fixture
def test_settings():
    """
    Создать тестовые настройки для приложения.

    Использует временные файлы БД и mock Telegram credentials.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        return Settings(
            ingestion_state_db_path=tmppath / "test_ingestion_state.db",
            raw_storage_db_path=tmppath / "test_raw_storage.db",
            processing_storage_db_path=tmppath / "test_processing_storage.db",
            telegram_api_id=12345,
            telegram_api_hash="test_hash",
            telegram_phone="+1234567890",
            openai_api_key="sk-test-key",
        )


# ============================================================================
# Telethon Mock Helpers
# ============================================================================


def create_mock_telethon_message(
    message_id: int,
    text: str,
    date: datetime | None = None,
    reply_to_msg_id: int | None = None,
    views: int | None = None,
    forwards: int | None = None,
    media: Mock | None = None,
) -> Mock:
    """
    Создать mock Telethon Message.

    Args:
        message_id: ID сообщения
        text: Текст сообщения
        date: Дата сообщения (по умолчанию UTC now)
        reply_to_msg_id: ID сообщения на которое отвечает (для комментариев)
        views: Количество просмотров
        forwards: Количество пересылок
        media: Mock медиа объект

    Returns:
        Mock объект имитирующий Telethon Message
    """
    mock_message = Mock()
    mock_message.id = message_id
    mock_message.text = text
    mock_message.message = text  # Telethon использует оба атрибута
    mock_message.date = date or datetime.now(UTC)
    mock_message.views = views
    mock_message.forwards = forwards
    mock_message.edit_date = None
    mock_message.post_author = None
    mock_message.grouped_id = None
    mock_message.media = media

    # Reply_to для комментариев
    if reply_to_msg_id is not None:
        mock_reply_to = Mock()
        mock_reply_to.reply_to_msg_id = reply_to_msg_id
        mock_message.reply_to = mock_reply_to
    else:
        mock_message.reply_to = None

    # Replies для постов с комментариями
    mock_message.replies = None

    return mock_message


@pytest.fixture
def mock_telethon_client():
    """
    Создать mock TelethonClient для E2E тестов.

    Mock автоматически подключается и возвращает предопределённые сообщения.
    """
    mock_client = AsyncMock()

    # Mock методы подключения
    mock_client.connect = AsyncMock()
    mock_client.disconnect = AsyncMock()

    # Mock get_messages возвращает async generator
    async def mock_get_messages(*args, **kwargs):
        # По умолчанию возвращаем пустой список
        # Тесты могут переопределить это через mock_client.get_messages.side_effect
        for msg in []:
            yield msg

    mock_client.get_messages = mock_get_messages

    # Mock get_comments возвращает async generator
    async def mock_get_comments(*args, **kwargs):
        for msg in []:
            yield msg

    mock_client.get_comments = mock_get_comments

    return mock_client


@pytest.fixture
def sample_raw_messages():
    """
    Создать набор тестовых RawTelegramMessage для E2E тестов.

    Возвращает список из 5 сообщений с разными характеристиками.
    """
    return [
        RawTelegramMessage(
            id="1",
            message_type=MessageType.POST,
            source_ref="tg:test_channel:post:1",
            channel_id="test_channel",
            date=datetime(2025, 12, 14, 10, 0, 0, tzinfo=UTC),
            text="Первое тестовое сообщение о Python разработке.",
        ),
        RawTelegramMessage(
            id="2",
            message_type=MessageType.POST,
            source_ref="tg:test_channel:post:2",
            channel_id="test_channel",
            date=datetime(2025, 12, 14, 11, 0, 0, tzinfo=UTC),
            text="Второе сообщение про Machine Learning и AI.",
        ),
        RawTelegramMessage(
            id="3",
            message_type=MessageType.POST,
            source_ref="tg:test_channel:post:3",
            channel_id="test_channel",
            date=datetime(2025, 12, 14, 12, 0, 0, tzinfo=UTC),
            text="Третье сообщение о DevOps и облачных технологиях.",
        ),
        RawTelegramMessage(
            id="4",
            message_type=MessageType.COMMENT,
            source_ref="tg:test_channel:comment:4",
            channel_id="test_channel",
            thread_id="1",
            parent_message_id="1",
            date=datetime(2025, 12, 14, 13, 0, 0, tzinfo=UTC),
            text="Комментарий к первому посту.",
        ),
        RawTelegramMessage(
            id="5",
            message_type=MessageType.POST,
            source_ref="tg:test_channel:post:5",
            channel_id="test_channel",
            date=datetime(2025, 12, 14, 14, 0, 0, tzinfo=UTC),
            text="Пятое сообщение про frontend разработку и React.",
        ),
    ]
