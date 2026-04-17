"""
Конфигурация pytest для TG_parser.

Общие фикстуры и helpers для тестов.
"""

import os

# IMPORTANT: Disable metrics BEFORE any other imports to prevent
# Prometheus registry conflicts when creating multiple test apps
os.environ["METRICS_ENABLED"] = "false"

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

# Load .env file into os.environ for SDKs that don't use pydantic-settings
# (e.g., OpenAI SDK, openai-agents)
from dotenv import load_dotenv

load_dotenv()

# CRITICAL: Force test database name to prevent tests from touching production.
# load_dotenv() imports DB_NAME from .env (pointing at production), which would
# override the "tg_parser_test" defaults in test fixtures.  We always want tests
# to target the dedicated test database unless explicitly overridden via
# TEST_DB_NAME (e.g. in CI).
_TEST_DB_NAME = os.environ.get("TEST_DB_NAME", "tg_parser_test")
os.environ["DB_NAME"] = _TEST_DB_NAME

from tg_parser.config.settings import Settings  # noqa: E402  # must follow os.environ override
from tg_parser.domain.models import MessageType, RawTelegramMessage  # noqa: E402
from tg_parser.storage.sqlalchemy import Database  # noqa: E402

# ============================================================================
# Database Fixtures
# ============================================================================


def _test_pg_settings() -> Settings:
    """Build Settings pointing at the local PostgreSQL test database."""
    return Settings(
        db_host=os.environ.get("DB_HOST", "localhost"),
        db_port=int(os.environ.get("DB_PORT", "5432")),
        db_name=_TEST_DB_NAME,
        db_user=os.environ.get("DB_USER", "tg_parser_user"),
        db_password=os.environ.get("DB_PASSWORD", ""),
        db_pool_size=2,
        db_max_overflow=3,
        telegram_api_id=12345,
        telegram_api_hash="test_hash",
        telegram_phone="+1234567890",
        openai_api_key="sk-test-key",
    )


@pytest.fixture
async def test_db():
    """
    Создать тестовую БД (PostgreSQL).

    Возвращает настроенный Database объект.
    Resets the singleton before and after to isolate integration tests.
    """
    Database.reset_instance()
    s = _test_pg_settings()
    db = Database.get_instance(s)
    await db.init()

    try:
        yield db
    finally:
        await db.close()
        Database.reset_instance()


@pytest.fixture
def test_settings():
    """
    Создать тестовые настройки для приложения.

    Использует PostgreSQL test database и mock Telegram credentials.
    """
    return _test_pg_settings()


@pytest.fixture
def postgres_settings():
    """Settings for PostgreSQL integration tests (requires TEST_POSTGRES=1)."""
    if not os.environ.get("TEST_POSTGRES"):
        pytest.skip("PostgreSQL tests disabled (set TEST_POSTGRES=1 to enable)")
    return _test_pg_settings()


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


@pytest.fixture(autouse=True)
async def cleanup_job_store():
    """
    Автоматически очищает JobStore и Database singleton после каждого теста.

    Предотвращает зависание из-за незакрытых SQLite соединений
    и утечку состояния Database singleton между тестами.
    """
    yield
    # Cleanup after test
    try:
        from tg_parser.api.job_store import JobStore, get_job_store
        store = get_job_store()
        if store.is_initialized:
            await store.close()
        JobStore.reset()
    except Exception:
        pass
    # Reset Database singleton so each test starts fresh
    Database.reset_instance()


@pytest.fixture(autouse=True, scope="session")
def disable_metrics_for_tests():
    """
    Disable Prometheus metrics for tests to prevent registry conflicts.

    Prometheus registry is global, and multiple app creations cause
    'Duplicated timeseries' errors.
    """
    import os

    # Set environment variable BEFORE any imports
    os.environ["METRICS_ENABLED"] = "false"

    # Also directly patch the settings singleton
    try:
        from tg_parser.config import settings
        settings.metrics_enabled = False
    except Exception:
        pass

    yield

    # Cleanup
    os.environ.pop("METRICS_ENABLED", None)


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
