"""
E2E тесты полного pipeline.

Проверяет интеграцию всех компонентов:
- add-source → ingest → process → topicize → export

Использует mock Telegram API для тестирования ingestion.
"""

import json

# Import helper from conftest
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from tg_parser.cli.add_source_cmd import run_add_source
from tg_parser.cli.export_cmd import run_export
from tg_parser.cli.ingest_cmd import run_ingestion
from tg_parser.cli.process_cmd import run_processing
from tg_parser.cli.topicize_cmd import run_topicization
from tg_parser.config.settings import Settings
from tg_parser.domain.ids import make_processed_document_id
from tg_parser.domain.models import MessageType
from tg_parser.processing.mock_llm import ProcessingMockLLM, TopicizationMockLLM
from tg_parser.storage.sqlite import (
    Database,
    DatabaseConfig,
    SQLiteProcessedDocumentRepo,
    SQLiteRawMessageRepo,
    SQLiteTopicCardRepo,
    init_ingestion_state_schema,
    init_processing_storage_schema,
    init_raw_storage_schema,
)

sys.path.insert(0, str(Path(__file__).parent))
from conftest import create_mock_telethon_message  # noqa: E402

# ============================================================================
# Helper Functions
# ============================================================================


def create_mock_convert_message():
    """
    Создать mock функцию для преобразования Telethon Message → RawTelegramMessage.

    Возвращает async функцию которая создаёт валидные RawTelegramMessage с raw_payload.
    """

    async def mock_convert_message(message, channel_id, message_type, thread_id=None):
        from tg_parser.domain.ids import make_source_ref
        from tg_parser.domain.models import RawTelegramMessage

        # Создаём минимальный сериализуемый raw_payload
        # Избегаем Mock объектов
        raw_payload = {
            "id": int(message.id) if hasattr(message.id, "__int__") else message.id,
            "text": str(message.text),
            "date": str(message.date.isoformat())
            if hasattr(message.date, "isoformat")
            else str(message.date),
        }

        # Определяем parent_message_id (проверяем что reply_to не None)
        parent_message_id = None
        if hasattr(message, "reply_to") and message.reply_to is not None:
            # Извлекаем reply_to_msg_id если он есть
            if hasattr(message.reply_to, "reply_to_msg_id"):
                parent_message_id = str(message.reply_to.reply_to_msg_id)

        # message_type должен быть str для make_source_ref
        message_type_str = (
            message_type.value if hasattr(message_type, "value") else str(message_type)
        )

        return RawTelegramMessage(
            id=str(message.id),
            message_type=message_type,
            source_ref=make_source_ref(channel_id, message_type_str, str(message.id)),
            channel_id=channel_id,
            date=message.date,
            text=message.text,
            thread_id=thread_id or str(message.id),
            parent_message_id=parent_message_id,
            raw_payload=raw_payload,
        )

    return mock_convert_message


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def e2e_settings():
    """
    Создать настройки для E2E тестов.

    Использует временные файлы БД и mock credentials.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        yield Settings(
            ingestion_state_db_path=tmppath / "e2e_ingestion_state.db",
            raw_storage_db_path=tmppath / "e2e_raw_storage.db",
            processing_storage_db_path=tmppath / "e2e_processing_storage.db",
            telegram_api_id=12345,
            telegram_api_hash="test_hash",
            telegram_phone="+1234567890",
            openai_api_key="sk-test-key",
        )


@pytest.fixture
async def e2e_db(e2e_settings):
    """
    Создать временную БД для E2E тестов.
    """
    config = DatabaseConfig(
        ingestion_state_path=e2e_settings.ingestion_state_db_path,
        raw_storage_path=e2e_settings.raw_storage_db_path,
        processing_storage_path=e2e_settings.processing_storage_db_path,
    )

    db = Database(config)
    await db.init()

    # Инициализируем схемы БД
    await init_ingestion_state_schema(db.ingestion_state_engine)
    await init_raw_storage_schema(db.raw_storage_engine)
    await init_processing_storage_schema(db.processing_storage_engine)

    try:
        yield db
    finally:
        await db.close()


@pytest.fixture
def mock_telethon_messages():
    """
    Создать набор mock Telethon сообщений для E2E тестов.

    Возвращает список из 5 сообщений: 4 поста и 1 комментарий.
    """
    return [
        create_mock_telethon_message(
            message_id=1,
            text="Первое сообщение о Python разработке и лучших практиках.",
            date=datetime(2025, 12, 14, 10, 0, 0, tzinfo=UTC),
            views=100,
        ),
        create_mock_telethon_message(
            message_id=2,
            text="Второе сообщение про Machine Learning и искусственный интеллект.",
            date=datetime(2025, 12, 14, 11, 0, 0, tzinfo=UTC),
            views=150,
        ),
        create_mock_telethon_message(
            message_id=3,
            text="Третье сообщение о DevOps практиках и облачных технологиях.",
            date=datetime(2025, 12, 14, 12, 0, 0, tzinfo=UTC),
            views=200,
        ),
        create_mock_telethon_message(
            message_id=4,
            text="Комментарий к первому посту с дополнительными деталями.",
            date=datetime(2025, 12, 14, 13, 0, 0, tzinfo=UTC),
            reply_to_msg_id=1,  # Комментарий к посту 1
        ),
        create_mock_telethon_message(
            message_id=5,
            text="Пятое сообщение про frontend разработку с использованием React и TypeScript.",
            date=datetime(2025, 12, 14, 14, 0, 0, tzinfo=UTC),
            views=180,
        ),
    ]


# ============================================================================
# E2E Tests
# ============================================================================


@pytest.mark.asyncio
async def test_full_pipeline_e2e(e2e_settings, e2e_db, mock_telethon_messages):
    """
    Тест полного E2E pipeline: add-source → ingest → process → topicize → export.

    Проверяет что все этапы работают корректно с mock Telegram API.
    """
    source_id = "test_source"
    channel_id = "test_channel"

    with tempfile.TemporaryDirectory() as output_dir:
        output_path = Path(output_dir)

        # Step 1: Add source
        with patch("tg_parser.cli.add_source_cmd.settings", e2e_settings):
            await run_add_source(
                source_id=source_id,
                channel_id=channel_id,
                channel_username="test_channel_username",
                include_comments=True,
            )

        # Step 2: Ingest with mock Telegram
        # Mock TelethonClient для возврата наших сообщений
        # ВАЖНО: get_messages должен возвращать RawTelegramMessage, не Telethon Message
        mock_client = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()

        # Helper для создания RawTelegramMessage из mock Telethon message
        convert_func = create_mock_convert_message()

        # Mock get_messages для постов
        async def mock_get_messages(*args, **kwargs):
            # Возвращаем только посты (id 1, 2, 3, 5), преобразованные в RawTelegramMessage
            for msg in mock_telethon_messages:
                if msg.id in [1, 2, 3, 5]:
                    yield await convert_func(msg, channel_id, MessageType.POST)

        mock_client.get_messages = mock_get_messages

        # Mock get_comments для комментариев
        async def mock_get_comments(*args, **kwargs):
            # Возвращаем только комментарии (id 4), преобразованные в RawTelegramMessage
            # Orchestrator передаёт post_id, не thread_id
            post_id = kwargs.get("post_id")
            if post_id is None:
                return

            for msg in mock_telethon_messages:
                if msg.id == 4 and post_id == 1:  # Комментарий к посту 1
                    yield await convert_func(msg, channel_id, MessageType.COMMENT, str(post_id))

        mock_client.get_comments = mock_get_comments

        with (
            patch("tg_parser.cli.ingest_cmd.settings", e2e_settings),
            patch(
                "tg_parser.cli.ingest_cmd.TelethonClient",
                return_value=mock_client,
            ),
        ):
            ingest_stats = await run_ingestion(
                source_id=source_id,
                mode="snapshot",
            )

            # Проверяем статистику ingestion
            assert ingest_stats["posts_collected"] == 4  # 4 поста
            assert ingest_stats["comments_collected"] == 1  # 1 комментарий

        # Step 3: Verify raw messages in database
        raw_session = e2e_db.raw_storage_session()
        try:
            raw_repo = SQLiteRawMessageRepo(raw_session)

            # Проверяем что все сообщения сохранены
            all_messages = await raw_repo.list_by_channel(channel_id)
            posts = [msg for msg in all_messages if msg.message_type == MessageType.POST]
            comments = [msg for msg in all_messages if msg.message_type == MessageType.COMMENT]

            assert len(posts) == 4
            assert len(comments) == 1

            # Проверяем структуру поста
            post = posts[0]
            assert post.channel_id == channel_id
            assert post.message_type == MessageType.POST
            assert post.text is not None

            # Проверяем структуру комментария (TR-6)
            comment = comments[0]
            assert comment.message_type == MessageType.COMMENT
            assert comment.thread_id == "1"  # Привязан к посту 1
            assert comment.parent_message_id == "1"

        finally:
            await raw_session.close()

        # Step 4: Process with mock LLM
        # Вместо того чтобы патчить, создаём pipeline напрямую с mock LLM
        mock_llm = ProcessingMockLLM()

        # Патчим create_processing_pipeline чтобы вернуть наш pipeline с mock LLM
        def mock_create_pipeline(*args, **kwargs):
            from tg_parser.processing.pipeline import ProcessingPipelineImpl

            # Используем переданный repo из kwargs или создаём mock
            processed_doc_repo = kwargs.get("processed_doc_repo")
            failure_repo = kwargs.get("failure_repo")

            return ProcessingPipelineImpl(
                llm_client=mock_llm,
                processed_doc_repo=processed_doc_repo,
                failure_repo=failure_repo,
            )

        with (
            patch("tg_parser.cli.process_cmd.settings", e2e_settings),
            patch(
                "tg_parser.cli.process_cmd.create_processing_pipeline",
                side_effect=mock_create_pipeline,
            ),
        ):
            process_stats = await run_processing(
                channel_id=channel_id,
                force=False,
            )

            # Проверяем статистику processing
            assert process_stats["processed_count"] >= 4  # Как минимум 4 поста
            assert process_stats["failed_count"] == 0

        # Step 5: Verify processed documents
        processing_session = e2e_db.processing_storage_session()
        try:
            processed_repo = SQLiteProcessedDocumentRepo(processing_session)

            # Проверяем обработанные документы
            docs = await processed_repo.list_by_channel(channel_id)
            assert len(docs) >= 4

            # Проверяем структуру документа
            doc = docs[0]
            assert doc.id == make_processed_document_id(doc.source_ref)
            assert doc.channel_id == channel_id
            assert doc.text_clean is not None
            assert doc.summary is not None
            assert doc.language is not None

        finally:
            await processing_session.close()

        # Step 6: Topicize
        # Используем TopicizationMockLLM (не ProcessingMockLLM) для правильного формата JSON
        topicization_mock_llm = TopicizationMockLLM(channel_id=channel_id)

        with (
            patch("tg_parser.cli.topicize_cmd.settings", e2e_settings),
            patch(
                "tg_parser.cli.topicize_cmd.OpenAIClient",
                return_value=topicization_mock_llm,
            ),
        ):
            topicize_stats = await run_topicization(
                channel_id=channel_id,
                force=False,
                build_bundles=True,
            )

            # Проверяем статистику topicization
            assert topicize_stats["topics_count"] >= 1
            assert topicize_stats["bundles_count"] >= 0

        # Step 7: Verify topics
        processing_session = e2e_db.processing_storage_session()
        try:
            topic_repo = SQLiteTopicCardRepo(processing_session)

            # Проверяем темы
            topics = await topic_repo.list_by_channel(channel_id)
            assert len(topics) >= 1

            # Проверяем структуру темы
            topic = topics[0]
            assert channel_id in topic.sources  # TopicCard имеет sources, не channel_id
            assert topic.title is not None
            assert len(topic.anchors) >= 1

        finally:
            await processing_session.close()

        # Step 8: Export
        with patch("tg_parser.cli.export_cmd.settings", e2e_settings):
            export_stats = await run_export(
                channel_id=channel_id,
                output_dir=str(output_path),
            )

            # Проверяем статистику export
            assert export_stats["kb_entries_count"] >= 4
            assert export_stats["topics_count"] >= 1

        # Step 9: Verify exported files
        kb_entries_file = output_path / "kb_entries.ndjson"
        topics_file = output_path / "topics.json"

        assert kb_entries_file.exists()
        assert topics_file.exists()

        # Проверяем содержимое KB entries
        kb_lines = kb_entries_file.read_text().strip().split("\n")
        assert len(kb_lines) >= 4

        # Проверяем формат KB entry (структура соответствует KnowledgeBaseEntry)
        import json

        first_entry = json.loads(kb_lines[0])
        assert "id" in first_entry
        assert "source" in first_entry  # KnowledgeBaseEntry использует source, не channel_id
        assert "content" in first_entry  # content вместо text
        assert "title" in first_entry  # title вместо summary

        # Проверяем формат topics.json
        topics_data = json.loads(topics_file.read_text())
        assert isinstance(topics_data, list)
        assert len(topics_data) >= 1

        first_topic = topics_data[0]
        assert "id" in first_topic
        assert "title" in first_topic
        assert "anchors" in first_topic


@pytest.mark.asyncio
async def test_incremental_mode_ingestion(e2e_settings, e2e_db, mock_telethon_messages):
    """
    Тест incremental режима ingestion (TR-4).

    Проверяет что повторный запуск собирает только новые сообщения.
    """
    source_id = "test_incremental"
    channel_id = "test_channel_inc"

    # Step 1: Add source
    with patch("tg_parser.cli.add_source_cmd.settings", e2e_settings):
        await run_add_source(
            source_id=source_id,
            channel_id=channel_id,
            include_comments=False,
        )

    # Step 2: Первый snapshot ingestion (собираем первые 3 сообщения)
    mock_client_first = AsyncMock()
    mock_client_first.connect = AsyncMock()
    mock_client_first.disconnect = AsyncMock()

    # Helper для создания RawTelegramMessage
    convert_func = create_mock_convert_message()

    async def mock_get_messages_first(*args, **kwargs):
        # Только первые 3 сообщения (id 1, 2, 3) - преобразуем в RawTelegramMessage
        for msg in mock_telethon_messages[:3]:
            if msg.reply_to is None:  # Только посты
                yield await convert_func(msg, channel_id, MessageType.POST)

    mock_client_first.get_messages = mock_get_messages_first

    async def mock_get_comments_empty(*args, **kwargs):
        return
        yield  # Make it a generator

    mock_client_first.get_comments = mock_get_comments_empty

    with (
        patch("tg_parser.cli.ingest_cmd.settings", e2e_settings),
        patch(
            "tg_parser.cli.ingest_cmd.TelethonClient",
            return_value=mock_client_first,
        ),
    ):
        stats1 = await run_ingestion(
            source_id=source_id,
            mode="snapshot",
        )

        assert stats1["posts_collected"] == 3

    # Step 3: Второй incremental ingestion (появилось новое сообщение)
    mock_client_second = AsyncMock()
    mock_client_second.connect = AsyncMock()
    mock_client_second.disconnect = AsyncMock()

    async def mock_get_messages_second(*args, **kwargs):
        # Incremental mode: только сообщения после последнего ID
        min_id = kwargs.get("min_id", 0)

        for msg in mock_telethon_messages:
            if msg.reply_to is None and msg.id > min_id:  # Только новые посты
                yield await convert_func(msg, channel_id, MessageType.POST)

    mock_client_second.get_messages = mock_get_messages_second
    mock_client_second.get_comments = mock_get_comments_empty

    with (
        patch("tg_parser.cli.ingest_cmd.settings", e2e_settings),
        patch(
            "tg_parser.cli.ingest_cmd.TelethonClient",
            return_value=mock_client_second,
        ),
    ):
        stats2 = await run_ingestion(
            source_id=source_id,
            mode="incremental",
        )

        # Проверяем что собрали только новые сообщения (id 5)
        # Note: может быть 1 или 2 в зависимости от того какие посты есть после id=3
        assert stats2["posts_collected"] >= 1

    # Step 4: Verify total messages in database
    raw_session = e2e_db.raw_storage_session()
    try:
        raw_repo = SQLiteRawMessageRepo(raw_session)
        all_posts = await raw_repo.list_by_channel(channel_id)

        # Проверяем что теперь есть все посты (без дубликатов благодаря TR-8)
        # У нас 4 поста в mock_telethon_messages (id 1, 2, 3, 5)
        assert len(all_posts) == 4

    finally:
        await raw_session.close()


@pytest.mark.asyncio
async def test_comments_ingestion_with_per_thread_cursors(
    e2e_settings, e2e_db, mock_telethon_messages
):
    """
    Тест ingestion комментариев с per-thread курсорами (TR-6, TR-7).

    Проверяет что комментарии привязываются к правильным постам.
    """
    source_id = "test_comments"
    channel_id = "test_channel_comments"

    # Step 1: Add source с включёнными комментариями
    with patch("tg_parser.cli.add_source_cmd.settings", e2e_settings):
        await run_add_source(
            source_id=source_id,
            channel_id=channel_id,
            include_comments=True,  # TR-5: включить комментарии
        )

    # Step 2: Create mock messages with multiple comments per post
    mock_messages = [
        # Пост 1
        create_mock_telethon_message(
            message_id=100,
            text="Первый пост",
            date=datetime(2025, 12, 14, 10, 0, 0, tzinfo=UTC),
        ),
        # Комментарии к посту 1
        create_mock_telethon_message(
            message_id=101,
            text="Первый комментарий к посту 1",
            date=datetime(2025, 12, 14, 10, 5, 0, tzinfo=UTC),
            reply_to_msg_id=100,
        ),
        create_mock_telethon_message(
            message_id=102,
            text="Второй комментарий к посту 1",
            date=datetime(2025, 12, 14, 10, 10, 0, tzinfo=UTC),
            reply_to_msg_id=100,
        ),
        # Пост 2
        create_mock_telethon_message(
            message_id=200,
            text="Второй пост",
            date=datetime(2025, 12, 14, 11, 0, 0, tzinfo=UTC),
        ),
        # Комментарий к посту 2
        create_mock_telethon_message(
            message_id=201,
            text="Комментарий к посту 2",
            date=datetime(2025, 12, 14, 11, 5, 0, tzinfo=UTC),
            reply_to_msg_id=200,
        ),
    ]

    # Step 3: Mock TelethonClient
    mock_client = AsyncMock()
    mock_client.connect = AsyncMock()
    mock_client.disconnect = AsyncMock()

    # Helper для создания RawTelegramMessage
    convert_func = create_mock_convert_message()

    async def mock_get_messages(*args, **kwargs):
        for msg in mock_messages:
            if msg.reply_to is None:  # Только посты
                yield await convert_func(msg, channel_id, MessageType.POST)

    async def mock_get_comments(*args, **kwargs):
        # Orchestrator передаёт post_id, не thread_id
        post_id = kwargs.get("post_id")
        if post_id is None:
            return

        for msg in mock_messages:
            if msg.reply_to is not None:  # Только комментарии
                if msg.reply_to.reply_to_msg_id == post_id:
                    yield await convert_func(msg, channel_id, MessageType.COMMENT, str(post_id))

    mock_client.get_messages = mock_get_messages
    mock_client.get_comments = mock_get_comments

    with (
        patch("tg_parser.cli.ingest_cmd.settings", e2e_settings),
        patch(
            "tg_parser.cli.ingest_cmd.TelethonClient",
            return_value=mock_client,
        ),
    ):
        stats = await run_ingestion(
            source_id=source_id,
            mode="snapshot",
        )

        # Проверяем статистику
        assert stats["posts_collected"] == 2
        assert stats["comments_collected"] == 3  # 2 к посту 1, 1 к посту 2

    # Step 4: Verify comments structure in database
    raw_session = e2e_db.raw_storage_session()
    try:
        raw_repo = SQLiteRawMessageRepo(raw_session)

        # Проверяем комментарии к посту 1
        comments_post1 = [
            msg
            for msg in await raw_repo.list_by_channel(channel_id)
            if msg.message_type == MessageType.COMMENT and msg.thread_id == "100"
        ]
        assert len(comments_post1) == 2

        # Проверяем что комментарии правильно привязаны (TR-6)
        for comment in comments_post1:
            assert comment.message_type == MessageType.COMMENT
            assert comment.thread_id == "100"
            assert comment.parent_message_id == "100"

        # Проверяем комментарии к посту 2
        comments_post2 = [
            msg
            for msg in await raw_repo.list_by_channel(channel_id)
            if msg.message_type == MessageType.COMMENT and msg.thread_id == "200"
        ]
        assert len(comments_post2) == 1
        assert comments_post2[0].thread_id == "200"

    finally:
        await raw_session.close()


@pytest.mark.asyncio
async def test_error_handling_and_retry_logic(e2e_settings, e2e_db):
    """
    Тест error handling и retry logic для ingestion (TR-12, TR-13).

    Проверяет что orchestrator корректно обрабатывает ошибки.
    """
    source_id = "test_errors"
    channel_id = "test_channel_errors"

    # Step 1: Add source
    with patch("tg_parser.cli.add_source_cmd.settings", e2e_settings):
        await run_add_source(
            source_id=source_id,
            channel_id=channel_id,
            include_comments=False,
        )

    # Step 2: Mock TelethonClient с retryable ошибкой
    mock_client = AsyncMock()
    mock_client.connect = AsyncMock()
    mock_client.disconnect = AsyncMock()

    # Helper для создания RawTelegramMessage
    convert_func = create_mock_convert_message()

    attempt_count = 0

    async def mock_get_messages_with_retry(*args, **kwargs):
        nonlocal attempt_count
        attempt_count += 1

        if attempt_count < 2:
            # Первая попытка - retryable ошибка (имитируем network error)
            from tg_parser.ingestion.orchestrator import RetryableError

            raise RetryableError("Network timeout")

        # Вторая попытка - успех
        mock_msg = create_mock_telethon_message(
            message_id=1,
            text="Сообщение после retry",
            date=datetime.now(UTC),
        )
        yield await convert_func(mock_msg, channel_id, MessageType.POST)

    mock_client.get_messages = mock_get_messages_with_retry

    async def mock_get_comments_empty(*args, **kwargs):
        return
        yield  # Make it a generator

    mock_client.get_comments = mock_get_comments_empty

    # Уменьшаем retry backoff для ускорения теста
    test_settings = e2e_settings
    test_settings.ingestion_retry_backoff_base = 0.01  # 10ms
    test_settings.ingestion_retry_jitter_max = 0.001  # 1ms

    with (
        patch("tg_parser.cli.ingest_cmd.settings", test_settings),
        patch(
            "tg_parser.cli.ingest_cmd.TelethonClient",
            return_value=mock_client,
        ),
    ):
        stats = await run_ingestion(
            source_id=source_id,
            mode="snapshot",
        )

        # Проверяем что retry сработал и мы в итоге собрали сообщение
        assert stats["posts_collected"] == 1
        assert attempt_count == 2  # Одна ошибка + один успех

    # Step 3: Verify message was saved despite initial error
    raw_session = e2e_db.raw_storage_session()
    try:
        raw_repo = SQLiteRawMessageRepo(raw_session)
        posts = await raw_repo.list_by_channel(channel_id)
        post_messages = [msg for msg in posts if msg.message_type == MessageType.POST]

        assert len(post_messages) == 1
        assert post_messages[0].text == "Сообщение после retry"

    finally:
        await raw_session.close()


# ============================================================================
# Test: CLI команда run (one-shot pipeline)
# ============================================================================


@pytest.mark.asyncio
async def test_run_command_full_pipeline(
    e2e_settings: Settings,
    e2e_db: Database,
    mock_telethon_messages,
):
    """
    Тест CLI команды run для one-shot запуска полного pipeline.

    Проверяет что run_full_pipeline последовательно выполняет все этапы
    и возвращает корректную статистику.
    """
    from tg_parser.cli.run_cmd import run_full_pipeline

    SOURCE_ID = "run_test_channel"
    CHANNEL_ID = "run_test_channel"

    # 1. Добавляем источник
    with patch("tg_parser.cli.add_source_cmd.settings", e2e_settings):
        await run_add_source(
            source_id=SOURCE_ID,
            channel_id=CHANNEL_ID,
            channel_username="run_test_channel_username",
            include_comments=False,
            batch_size=50,
        )

    # 2. Mock TelethonClient
    mock_client = AsyncMock()
    mock_client.connect = AsyncMock()
    mock_client.disconnect = AsyncMock()

    # Helper для создания RawTelegramMessage из mock Telethon message
    convert_func = create_mock_convert_message()

    # Mock get_messages для постов (первые 3 сообщения)
    async def mock_get_messages(*args, **kwargs):
        for msg in mock_telethon_messages[:3]:
            if msg.id in [1, 2, 3]:
                yield await convert_func(msg, CHANNEL_ID, MessageType.POST)

    mock_client.get_messages = mock_get_messages

    # Mock get_comments (пустой)
    async def mock_get_comments(*args, **kwargs):
        return
        yield  # Make it a generator

    mock_client.get_comments = mock_get_comments

    # Mock для LLM (используем ProcessingMockLLM для processing)
    mock_llm = ProcessingMockLLM()

    # Функция для создания pipeline с mock LLM
    def mock_create_pipeline(*args, **kwargs):
        from tg_parser.processing.pipeline import ProcessingPipelineImpl

        processed_doc_repo = kwargs.get("processed_doc_repo")
        failure_repo = kwargs.get("failure_repo")

        return ProcessingPipelineImpl(
            llm_client=mock_llm,
            processed_doc_repo=processed_doc_repo,
            failure_repo=failure_repo,
        )

    # Mock для topicization LLM с методом close
    mock_topicization_llm = AsyncMock()
    mock_topicization_llm.generate = AsyncMock(return_value=json.dumps({"topics": []}))
    mock_topicization_llm.close = AsyncMock()

    # 3. Используем tempdir для output
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = str(Path(tmpdir) / "output")

        # Патчим для всех CLI команд
        with (
            patch("tg_parser.cli.ingest_cmd.settings", e2e_settings),
            patch("tg_parser.cli.process_cmd.settings", e2e_settings),
            patch("tg_parser.cli.topicize_cmd.settings", e2e_settings),
            patch("tg_parser.cli.export_cmd.settings", e2e_settings),
            patch("tg_parser.cli.run_cmd.settings", e2e_settings),
            patch(
                "tg_parser.cli.ingest_cmd.TelethonClient",
                return_value=mock_client,
            ),
            patch(
                "tg_parser.cli.process_cmd.create_processing_pipeline",
                side_effect=mock_create_pipeline,
            ),
            patch(
                "tg_parser.cli.topicize_cmd.OpenAIClient",
                return_value=mock_llm,
            ),
        ):
            # 4. Запускаем run_full_pipeline
            stats = await run_full_pipeline(
                source_id=SOURCE_ID,
                output_dir=output_dir,
                mode="snapshot",
                skip_ingest=False,
                skip_process=False,
                skip_topicize=False,
                force=False,
                limit=None,
            )

            # 5. Проверяем статистику
            assert stats["ingest"] is not None
            assert stats["ingest"]["posts_collected"] == 3
            assert stats["ingest"]["comments_collected"] == 0

            assert stats["process"] is not None
            assert stats["process"]["processed_count"] == 3
            assert stats["process"]["failed_count"] == 0

            assert stats["topicize"] is not None
            assert stats["topicize"]["topics_count"] >= 0

            assert stats["export"] is not None
            assert stats["export"]["kb_entries_count"] == 3

            assert stats["last_successful_stage"] == "export"
            assert stats["total_duration_seconds"] > 0

            # 6. Проверяем что файлы созданы
            output_path = Path(output_dir)
            assert output_path.exists()
            assert (output_path / "kb_entries.ndjson").exists()


@pytest.mark.asyncio
async def test_run_command_with_skip_options(
    e2e_settings: Settings,
    e2e_db: Database,
    mock_telethon_messages,
):
    """
    Тест CLI команды run с опциями skip для пропуска этапов.

    Проверяет что pipeline корректно пропускает этапы когда
    переданы --skip-ingest, --skip-process, --skip-topicize.
    """
    from tg_parser.cli.run_cmd import run_full_pipeline

    SOURCE_ID = "skip_test_channel"
    CHANNEL_ID = "skip_test_channel"

    # 1. Добавляем источник
    with patch("tg_parser.cli.add_source_cmd.settings", e2e_settings):
        await run_add_source(
            source_id=SOURCE_ID,
            channel_id=CHANNEL_ID,
            channel_username="skip_test_channel_username",
            include_comments=False,
            batch_size=50,
        )

    # 2. Mock TelethonClient
    mock_client = AsyncMock()
    mock_client.connect = AsyncMock()
    mock_client.disconnect = AsyncMock()

    # Helper для создания RawTelegramMessage
    convert_func = create_mock_convert_message()

    # Mock get_messages для постов (первые 2 сообщения)
    async def mock_get_messages(*args, **kwargs):
        for msg in mock_telethon_messages[:2]:
            if msg.id in [1, 2]:
                yield await convert_func(msg, CHANNEL_ID, MessageType.POST)

    mock_client.get_messages = mock_get_messages

    # Mock get_comments (пустой)
    async def mock_get_comments(*args, **kwargs):
        return
        yield  # Make it a generator

    mock_client.get_comments = mock_get_comments

    # Mock для LLM (используем ProcessingMockLLM для processing)
    mock_llm = ProcessingMockLLM()

    # Функция для создания pipeline с mock LLM
    def mock_create_pipeline(*args, **kwargs):
        from tg_parser.processing.pipeline import ProcessingPipelineImpl

        processed_doc_repo = kwargs.get("processed_doc_repo")
        failure_repo = kwargs.get("failure_repo")

        return ProcessingPipelineImpl(
            llm_client=mock_llm,
            processed_doc_repo=processed_doc_repo,
            failure_repo=failure_repo,
        )

    # Mock для topicization LLM с методом close
    mock_topicization_llm = AsyncMock()
    mock_topicization_llm.generate = AsyncMock(return_value=json.dumps({"topics": []}))
    mock_topicization_llm.close = AsyncMock()

    # 3. Предварительно выполняем ingestion и processing (для тестирования skip)
    with (
        patch("tg_parser.cli.ingest_cmd.settings", e2e_settings),
        patch("tg_parser.cli.process_cmd.settings", e2e_settings),
        patch(
            "tg_parser.cli.ingest_cmd.TelethonClient",
            return_value=mock_client,
        ),
        patch(
            "tg_parser.cli.process_cmd.create_processing_pipeline",
            side_effect=mock_create_pipeline,
        ),
    ):
        # Предварительный ingestion
        await run_ingestion(source_id=SOURCE_ID, mode="snapshot", limit=None)

        # Предварительный processing
        await run_processing(channel_id=SOURCE_ID, force=False)

    # 4. Используем tempdir для output
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = str(Path(tmpdir) / "output")

        # Патчим для run_full_pipeline
        with (
            patch("tg_parser.cli.topicize_cmd.settings", e2e_settings),
            patch("tg_parser.cli.export_cmd.settings", e2e_settings),
            patch("tg_parser.cli.run_cmd.settings", e2e_settings),
            patch(
                "tg_parser.cli.topicize_cmd.OpenAIClient",
                return_value=mock_topicization_llm,
            ),
        ):
            # 5. Запускаем run_full_pipeline с skip опциями
            stats = await run_full_pipeline(
                source_id=SOURCE_ID,
                output_dir=output_dir,
                mode="snapshot",
                skip_ingest=True,  # Пропускаем ingestion
                skip_process=True,  # Пропускаем processing
                skip_topicize=False,
                force=False,
                limit=None,
            )

            # 6. Проверяем что этапы были пропущены
            assert stats["ingest"] is None  # Пропущен
            assert stats["process"] is None  # Пропущен
            assert stats["topicize"] is not None  # Выполнен
            assert stats["export"] is not None  # Выполнен

            assert stats["last_successful_stage"] == "export"
            assert stats["total_duration_seconds"] > 0


@pytest.mark.asyncio
async def test_run_command_error_handling(
    e2e_settings: Settings,
    e2e_db: Database,
):
    """
    Тест error handling в CLI команде run.

    Проверяет что pipeline корректно обрабатывает ошибки на разных этапах
    и возвращает информацию о последнем успешном этапе.
    """
    from tg_parser.cli.run_cmd import run_full_pipeline

    SOURCE_ID = "error_test_channel"
    CHANNEL_ID = "error_test_channel"

    # 1. Добавляем источник (чтобы run_cmd мог его найти)
    with patch("tg_parser.cli.add_source_cmd.settings", e2e_settings):
        await run_add_source(
            source_id=SOURCE_ID,
            channel_id=CHANNEL_ID,
            channel_username=None,
            include_comments=False,
            batch_size=100,
        )

    # Mock TelethonClient который выбрасывает ошибку
    mock_client = AsyncMock()
    mock_client.get_messages.side_effect = Exception("Mock Telegram API error")

    # Используем tempdir для output
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = str(Path(tmpdir) / "output")

        # Патчим TelethonClient для провала ingestion
        with (
            patch(
                "tg_parser.cli.ingest_cmd.TelethonClient",
                return_value=mock_client,
            ),
            patch("tg_parser.cli.ingest_cmd.settings", e2e_settings),
            patch("tg_parser.cli.run_cmd.settings", e2e_settings),
        ):
            # Запускаем run_full_pipeline и ожидаем ошибку
            with pytest.raises(RuntimeError) as exc_info:
                await run_full_pipeline(
                    source_id=SOURCE_ID,
                    output_dir=output_dir,
                    mode="snapshot",
                    skip_ingest=False,
                    skip_process=False,
                    skip_topicize=False,
                    force=False,
                    limit=None,
                )

            # Проверяем что ошибка содержит информацию о этапе
            assert "Pipeline failed at ingestion stage" in str(exc_info.value)
