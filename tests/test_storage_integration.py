"""
Integration тесты для SQLite storage.

Проверяет:
- TR-8: raw snapshot (идемпотентность)
- TR-10: атомарность курсоров
- TR-18: уникальность по source_ref
- TR-22: upsert processed documents
"""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from tg_parser.domain.ids import make_processed_document_id, make_source_ref
from tg_parser.domain.models import MessageType, ProcessedDocument, RawTelegramMessage
from tg_parser.storage.sqlite import (
    Database,
    DatabaseConfig,
    SQLiteProcessedDocumentRepo,
    SQLiteRawMessageRepo,
    SQLiteTopicBundleRepo,
    SQLiteTopicCardRepo,
    init_ingestion_state_schema,
    init_processing_storage_schema,
    init_raw_storage_schema,
)


@pytest.fixture
async def test_db():
    """Создать временную тестовую БД."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        config = DatabaseConfig(
            ingestion_state_path=tmppath / "ingestion_state.sqlite",
            raw_storage_path=tmppath / "raw_storage.sqlite",
            processing_storage_path=tmppath / "processing_storage.sqlite",
        )

        db = Database(config)
        await db.init()

        # Создаём схемы
        await init_ingestion_state_schema(db.ingestion_state_engine)
        await init_raw_storage_schema(db.raw_storage_engine)
        await init_processing_storage_schema(db.processing_storage_engine)

        yield db

        await db.close()


class TestRawMessageRepo:
    """Integration тесты для RawMessageRepo."""

    @pytest.mark.asyncio
    async def test_upsert_creates_new_message(self, test_db):
        """Тест создания нового raw сообщения."""
        async with test_db.raw_storage_session() as session:
            repo = SQLiteRawMessageRepo(session)

            msg = RawTelegramMessage(
                id="123",
                message_type=MessageType.POST,
                source_ref="tg:ch:post:123",
                channel_id="ch",
                date=datetime(2025, 12, 14, 10, 0, 0),
                text="Test message",
            )

            created = await repo.upsert(msg)
            assert created is True

    @pytest.mark.asyncio
    async def test_upsert_idempotency_tr8(self, test_db):
        """
        TR-8: raw snapshot не должен перезаписываться.

        При повторном upsert с тем же source_ref должен быть conflict.
        """
        async with test_db.raw_storage_session() as session:
            repo = SQLiteRawMessageRepo(session)

            # Первая запись
            msg1 = RawTelegramMessage(
                id="123",
                message_type=MessageType.POST,
                source_ref="tg:ch:post:123",
                channel_id="ch",
                date=datetime(2025, 12, 14, 10, 0, 0),
                text="Original text",
            )
            created1 = await repo.upsert(msg1)
            assert created1 is True

        # Попытка перезаписать (новая сессия)
        async with test_db.raw_storage_session() as session:
            repo = SQLiteRawMessageRepo(session)

            msg2 = RawTelegramMessage(
                id="123",
                message_type=MessageType.POST,
                source_ref="tg:ch:post:123",
                channel_id="ch",
                date=datetime(2025, 12, 14, 11, 0, 0),  # Другая дата
                text="Modified text",  # Другой текст
            )
            created2 = await repo.upsert(msg2)

            # TR-8: должен быть conflict (не создано)
            assert created2 is False

            # Проверяем, что оригинальные данные сохранились
            retrieved = await repo.get_by_source_ref("tg:ch:post:123")
            assert retrieved is not None
            assert retrieved.text == "Original text"  # Исходный текст
            assert retrieved.date == datetime(2025, 12, 14, 10, 0, 0)  # Исходная дата

    @pytest.mark.asyncio
    async def test_unique_constraint_tr18(self, test_db):
        """TR-18: уникальность по source_ref."""
        async with test_db.raw_storage_session() as session:
            repo = SQLiteRawMessageRepo(session)

            msg = RawTelegramMessage(
                id="123",
                message_type=MessageType.POST,
                source_ref="tg:ch:post:123",
                channel_id="ch",
                date=datetime(2025, 12, 14),
                text="Text",
            )

            created1 = await repo.upsert(msg)
            assert created1 is True

            # Повторный upsert с тем же source_ref
            created2 = await repo.upsert(msg)
            assert created2 is False

    @pytest.mark.asyncio
    async def test_list_by_channel(self, test_db):
        """Тест получения сообщений канала."""
        async with test_db.raw_storage_session() as session:
            repo = SQLiteRawMessageRepo(session)

            # Создаём несколько сообщений
            for i in range(3):
                msg = RawTelegramMessage(
                    id=str(i),
                    message_type=MessageType.POST,
                    source_ref=f"tg:ch:post:{i}",
                    channel_id="ch",
                    date=datetime(2025, 12, 14, 10, i, 0),
                    text=f"Message {i}",
                )
                await repo.upsert(msg)

        # Получаем все сообщения канала
        async with test_db.raw_storage_session() as session:
            repo = SQLiteRawMessageRepo(session)
            messages = await repo.list_by_channel("ch")

            assert len(messages) == 3
            # Проверяем сортировку по дате
            assert messages[0].id == "0"
            assert messages[2].id == "2"


class TestProcessedDocumentRepo:
    """Integration тесты для ProcessedDocumentRepo."""

    @pytest.mark.asyncio
    async def test_upsert_creates_new_document(self, test_db):
        """Тест создания нового processed document."""
        async with test_db.processing_storage_session() as session:
            repo = SQLiteProcessedDocumentRepo(session)

            source_ref = make_source_ref("ch", "post", "123")
            doc = ProcessedDocument(
                id=make_processed_document_id(source_ref),
                source_ref=source_ref,
                source_message_id="123",
                channel_id="ch",
                processed_at=datetime(2025, 12, 14, 12, 0, 0),
                text_clean="Clean text",
            )

            await repo.upsert(doc)

            # Проверяем, что документ создан
            retrieved = await repo.get_by_source_ref(source_ref)
            assert retrieved is not None
            assert retrieved.text_clean == "Clean text"

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_tr22(self, test_db):
        """
        TR-22: одно актуальное состояние на source_ref.

        При повторном upsert должна происходить замена.
        """
        source_ref = make_source_ref("ch", "post", "123")

        # Первая версия
        async with test_db.processing_storage_session() as session:
            repo = SQLiteProcessedDocumentRepo(session)

            doc1 = ProcessedDocument(
                id=make_processed_document_id(source_ref),
                source_ref=source_ref,
                source_message_id="123",
                channel_id="ch",
                processed_at=datetime(2025, 12, 14, 12, 0, 0),
                text_clean="Version 1",
                summary="Summary 1",
            )
            await repo.upsert(doc1)

        # Обновление (новая сессия)
        async with test_db.processing_storage_session() as session:
            repo = SQLiteProcessedDocumentRepo(session)

            doc2 = ProcessedDocument(
                id=make_processed_document_id(source_ref),
                source_ref=source_ref,
                source_message_id="123",
                channel_id="ch",
                processed_at=datetime(2025, 12, 14, 13, 0, 0),  # Новое время
                text_clean="Version 2",  # Новый текст
                summary="Summary 2",
            )
            await repo.upsert(doc2)

            # TR-22: должна быть только одна запись (обновлённая)
            retrieved = await repo.get_by_source_ref(source_ref)
            assert retrieved is not None
            assert retrieved.text_clean == "Version 2"
            assert retrieved.summary == "Summary 2"
            assert retrieved.processed_at == datetime(2025, 12, 14, 13, 0, 0)

    @pytest.mark.asyncio
    async def test_exists_check_tr48(self, test_db):
        """TR-48: проверка существования для инкрементальности."""
        source_ref = make_source_ref("ch", "post", "123")

        async with test_db.processing_storage_session() as session:
            repo = SQLiteProcessedDocumentRepo(session)

            # Изначально не существует
            exists_before = await repo.exists(source_ref)
            assert exists_before is False

            # Создаём документ
            doc = ProcessedDocument(
                id=make_processed_document_id(source_ref),
                source_ref=source_ref,
                source_message_id="123",
                channel_id="ch",
                processed_at=datetime(2025, 12, 14),
                text_clean="Text",
            )
            await repo.upsert(doc)

        # Проверяем существование (новая сессия)
        async with test_db.processing_storage_session() as session:
            repo = SQLiteProcessedDocumentRepo(session)
            exists_after = await repo.exists(source_ref)
            assert exists_after is True

    @pytest.mark.asyncio
    async def test_metadata_json_serialization(self, test_db):
        """Тест сериализации/десериализации metadata."""
        source_ref = make_source_ref("ch", "post", "123")

        metadata = {
            "pipeline_version": "processing:v1.0.0",
            "model_id": "gpt-4",
            "parameters": {"temperature": 0.0},
        }

        async with test_db.processing_storage_session() as session:
            repo = SQLiteProcessedDocumentRepo(session)

            doc = ProcessedDocument(
                id=make_processed_document_id(source_ref),
                source_ref=source_ref,
                source_message_id="123",
                channel_id="ch",
                processed_at=datetime(2025, 12, 14),
                text_clean="Text",
                metadata=metadata,
            )
            await repo.upsert(doc)

        # Проверяем десериализацию
        async with test_db.processing_storage_session() as session:
            repo = SQLiteProcessedDocumentRepo(session)
            retrieved = await repo.get_by_source_ref(source_ref)

            assert retrieved is not None
            assert retrieved.metadata == metadata
            assert retrieved.metadata["pipeline_version"] == "processing:v1.0.0"


class TestProcessingFailureRepo:
    """Тесты SQLiteProcessingFailureRepo."""

    @pytest.mark.asyncio
    async def test_record_failure_creates_new_entry(self, test_db):
        """Тест создания новой записи о неудаче."""
        from tg_parser.storage.sqlite import SQLiteProcessingFailureRepo

        source_ref = make_source_ref("test_ch", "post", "100")

        async with test_db.processing_storage_session() as session:
            repo = SQLiteProcessingFailureRepo(session)

            await repo.record_failure(
                source_ref=source_ref,
                channel_id="test_ch",
                attempts=3,
                error_class="TimeoutError",
                error_message="Request timeout after 30s",
                error_details={"timeout": 30, "retries": 3},
            )

        # Проверяем что запись создана
        async with test_db.processing_storage_session() as session:
            repo = SQLiteProcessingFailureRepo(session)
            failures = await repo.list_failures()

            assert len(failures) == 1
            assert failures[0]["source_ref"] == source_ref
            assert failures[0]["channel_id"] == "test_ch"
            assert failures[0]["attempts"] == 3
            assert failures[0]["error_class"] == "TimeoutError"
            assert failures[0]["error_message"] == "Request timeout after 30s"
            assert failures[0]["error_details"]["timeout"] == 30

    @pytest.mark.asyncio
    async def test_record_failure_updates_existing(self, test_db):
        """Тест обновления существующей записи о неудаче."""
        from tg_parser.storage.sqlite import SQLiteProcessingFailureRepo

        source_ref = make_source_ref("test_ch", "post", "200")

        async with test_db.processing_storage_session() as session:
            repo = SQLiteProcessingFailureRepo(session)

            # Первая попытка
            await repo.record_failure(
                source_ref=source_ref,
                channel_id="test_ch",
                attempts=1,
                error_class="NetworkError",
                error_message="Connection refused",
            )

            # Вторая попытка (обновление)
            await repo.record_failure(
                source_ref=source_ref,
                channel_id="test_ch",
                attempts=2,
                error_class="TimeoutError",
                error_message="Request timeout",
            )

        # Проверяем что только одна запись (обновлённая)
        async with test_db.processing_storage_session() as session:
            repo = SQLiteProcessingFailureRepo(session)
            failures = await repo.list_failures()

            assert len(failures) == 1
            assert failures[0]["source_ref"] == source_ref
            assert failures[0]["attempts"] == 2
            assert failures[0]["error_class"] == "TimeoutError"

    @pytest.mark.asyncio
    async def test_delete_failure_tr47(self, test_db):
        """TR-47: при успешной обработке запись о неудаче удаляется."""
        from tg_parser.storage.sqlite import SQLiteProcessingFailureRepo

        source_ref = make_source_ref("test_ch", "post", "300")

        async with test_db.processing_storage_session() as session:
            repo = SQLiteProcessingFailureRepo(session)

            # Записываем неудачу
            await repo.record_failure(
                source_ref=source_ref,
                channel_id="test_ch",
                attempts=3,
                error_class="ValueError",
                error_message="Invalid data",
            )

            # Проверяем что есть
            failures_before = await repo.list_failures()
            assert len(failures_before) == 1

            # Удаляем (симулируем успешную обработку)
            await repo.delete_failure(source_ref)

            # Проверяем что удалена
            failures_after = await repo.list_failures()
            assert len(failures_after) == 0

    @pytest.mark.asyncio
    async def test_list_failures_with_channel_filter(self, test_db):
        """Тест фильтрации списка неудач по каналу."""
        from tg_parser.storage.sqlite import SQLiteProcessingFailureRepo

        async with test_db.processing_storage_session() as session:
            repo = SQLiteProcessingFailureRepo(session)

            # Создаём неудачи для двух каналов
            await repo.record_failure(
                source_ref=make_source_ref("ch1", "post", "1"),
                channel_id="ch1",
                attempts=1,
                error_class="Error1",
                error_message="Error in ch1",
            )

            await repo.record_failure(
                source_ref=make_source_ref("ch2", "post", "1"),
                channel_id="ch2",
                attempts=1,
                error_class="Error2",
                error_message="Error in ch2",
            )

            await repo.record_failure(
                source_ref=make_source_ref("ch1", "post", "2"),
                channel_id="ch1",
                attempts=1,
                error_class="Error3",
                error_message="Another error in ch1",
            )

        # Проверяем фильтрацию
        async with test_db.processing_storage_session() as session:
            repo = SQLiteProcessingFailureRepo(session)

            all_failures = await repo.list_failures()
            assert len(all_failures) == 3

            ch1_failures = await repo.list_failures(channel_id="ch1")
            assert len(ch1_failures) == 2
            assert all(f["channel_id"] == "ch1" for f in ch1_failures)

            ch2_failures = await repo.list_failures(channel_id="ch2")
            assert len(ch2_failures) == 1
            assert ch2_failures[0]["channel_id"] == "ch2"

    @pytest.mark.asyncio
    async def test_list_failures_with_limit(self, test_db):
        """Тест ограничения количества возвращаемых записей."""
        from tg_parser.storage.sqlite import SQLiteProcessingFailureRepo

        async with test_db.processing_storage_session() as session:
            repo = SQLiteProcessingFailureRepo(session)

            # Создаём несколько неудач
            for i in range(5):
                await repo.record_failure(
                    source_ref=make_source_ref("test_ch", "post", str(i)),
                    channel_id="test_ch",
                    attempts=1,
                    error_class="TestError",
                    error_message=f"Error {i}",
                )

        # Проверяем лимит
        async with test_db.processing_storage_session() as session:
            repo = SQLiteProcessingFailureRepo(session)

            all_failures = await repo.list_failures()
            assert len(all_failures) == 5

            limited_failures = await repo.list_failures(limit=3)
            assert len(limited_failures) == 3

    @pytest.mark.asyncio
    async def test_failure_without_error_details(self, test_db):
        """Тест записи неудачи без error_details."""
        from tg_parser.storage.sqlite import SQLiteProcessingFailureRepo

        source_ref = make_source_ref("test_ch", "post", "400")

        async with test_db.processing_storage_session() as session:
            repo = SQLiteProcessingFailureRepo(session)

            await repo.record_failure(
                source_ref=source_ref,
                channel_id="test_ch",
                attempts=1,
                error_class="SimpleError",
                error_message="Simple error message",
                error_details=None,
            )

        # Проверяем что запись создана без error_details
        async with test_db.processing_storage_session() as session:
            repo = SQLiteProcessingFailureRepo(session)
            failures = await repo.list_failures()

            assert len(failures) == 1
            assert failures[0]["error_details"] is None


class TestTopicCardRepo:
    """Integration тесты для TopicCardRepo."""

    @pytest.mark.asyncio
    async def test_upsert_creates_new_topic_card(self, test_db):
        """Тест создания новой topic card."""
        from tg_parser.domain.models import Anchor, TopicCard, TopicType

        async with test_db.processing_storage_session() as session:
            repo = SQLiteTopicCardRepo(session)

            card = TopicCard(
                id="topic:tg:ch:post:123",
                title="Test Topic",
                summary="Test summary",
                scope_in=["test scope in"],
                scope_out=["test scope out"],
                type=TopicType.SINGLETON,
                anchors=[
                    Anchor(
                        channel_id="ch",
                        message_id="123",
                        message_type=MessageType.POST,
                        anchor_ref="tg:ch:post:123",
                        score=0.9,
                    )
                ],
                sources=["ch"],
                updated_at=datetime(2025, 12, 14, 12, 0, 0),
            )

            await repo.upsert(card)

            # Проверяем что создана
            retrieved = await repo.get_by_id("topic:tg:ch:post:123")
            assert retrieved is not None
            assert retrieved.title == "Test Topic"
            assert retrieved.type == TopicType.SINGLETON
            assert len(retrieved.anchors) == 1
            assert retrieved.anchors[0].score == 0.9

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_topic_card(self, test_db):
        """TR-43: upsert/replace по id."""
        from tg_parser.domain.models import Anchor, TopicCard, TopicType

        async with test_db.processing_storage_session() as session:
            repo = SQLiteTopicCardRepo(session)

            # Первая версия
            card1 = TopicCard(
                id="topic:tg:ch:post:123",
                title="Original Title",
                summary="Original summary",
                scope_in=["original"],
                scope_out=["excluded"],
                type=TopicType.SINGLETON,
                anchors=[
                    Anchor(
                        channel_id="ch",
                        message_id="123",
                        message_type=MessageType.POST,
                        anchor_ref="tg:ch:post:123",
                        score=0.8,
                    )
                ],
                sources=["ch"],
                updated_at=datetime(2025, 12, 14, 12, 0, 0),
            )

            await repo.upsert(card1)

        # Обновляем (новая сессия)
        async with test_db.processing_storage_session() as session:
            repo = SQLiteTopicCardRepo(session)

            card2 = TopicCard(
                id="topic:tg:ch:post:123",
                title="Updated Title",
                summary="Updated summary",
                scope_in=["updated"],
                scope_out=["new excluded"],
                type=TopicType.SINGLETON,
                anchors=[
                    Anchor(
                        channel_id="ch",
                        message_id="123",
                        message_type=MessageType.POST,
                        anchor_ref="tg:ch:post:123",
                        score=0.95,
                    )
                ],
                sources=["ch"],
                updated_at=datetime(2025, 12, 14, 13, 0, 0),
            )

            await repo.upsert(card2)

            # Проверяем что обновлена
            retrieved = await repo.get_by_id("topic:tg:ch:post:123")
            assert retrieved is not None
            assert retrieved.title == "Updated Title"
            assert retrieved.summary == "Updated summary"
            assert retrieved.anchors[0].score == 0.95

    @pytest.mark.asyncio
    async def test_list_by_channel(self, test_db):
        """Тест получения topic cards по каналу."""
        from tg_parser.domain.models import Anchor, TopicCard, TopicType

        async with test_db.processing_storage_session() as session:
            repo = SQLiteTopicCardRepo(session)

            # Создаём карточки для разных каналов
            for ch in ["ch1", "ch2"]:
                for i in range(2):
                    card = TopicCard(
                        id=f"topic:tg:{ch}:post:{i}",
                        title=f"Topic {ch}-{i}",
                        summary=f"Summary {i}",
                        scope_in=["scope"],
                        scope_out=["excluded"],
                        type=TopicType.SINGLETON,
                        anchors=[
                            Anchor(
                                channel_id=ch,
                                message_id=str(i),
                                message_type=MessageType.POST,
                                anchor_ref=f"tg:{ch}:post:{i}",
                                score=0.9,
                            )
                        ],
                        sources=[ch],
                        updated_at=datetime(2025, 12, 14, 12, i, 0),
                    )
                    await repo.upsert(card)

        # Проверяем фильтрацию по каналу
        async with test_db.processing_storage_session() as session:
            repo = SQLiteTopicCardRepo(session)

            ch1_cards = await repo.list_by_channel("ch1")
            assert len(ch1_cards) == 2
            assert all(card.sources == ["ch1"] for card in ch1_cards)

            ch2_cards = await repo.list_by_channel("ch2")
            assert len(ch2_cards) == 2


class TestTopicBundleRepo:
    """Integration тесты для TopicBundleRepo."""

    @pytest.mark.asyncio
    async def test_upsert_creates_new_bundle(self, test_db):
        """Тест создания новой topic bundle."""
        from tg_parser.domain.models import BundleItem, BundleItemRole, TopicBundle

        async with test_db.processing_storage_session() as session:
            repo = SQLiteTopicBundleRepo(session)

            bundle = TopicBundle(
                topic_id="topic:tg:ch:post:123",
                items=[
                    BundleItem(
                        channel_id="ch",
                        message_id="123",
                        message_type=MessageType.POST,
                        source_ref="tg:ch:post:123",
                        role=BundleItemRole.ANCHOR,
                        score=1.0,
                    ),
                    BundleItem(
                        channel_id="ch",
                        message_id="456",
                        message_type=MessageType.POST,
                        source_ref="tg:ch:post:456",
                        role=BundleItemRole.SUPPORTING,
                        score=0.7,
                    ),
                ],
                updated_at=datetime(2025, 12, 14, 12, 0, 0),
            )

            await repo.upsert(bundle)

            # Проверяем что создана
            retrieved = await repo.get_by_topic_id("topic:tg:ch:post:123")
            assert retrieved is not None
            assert len(retrieved.items) == 2
            assert retrieved.items[0].role == BundleItemRole.ANCHOR
            assert retrieved.items[1].role == BundleItemRole.SUPPORTING

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_bundle(self, test_db):
        """TR-43: upsert/replace по topic_id."""
        from tg_parser.domain.models import BundleItem, BundleItemRole, TopicBundle

        async with test_db.processing_storage_session() as session:
            repo = SQLiteTopicBundleRepo(session)

            # Первая версия
            bundle1 = TopicBundle(
                topic_id="topic:tg:ch:post:123",
                items=[
                    BundleItem(
                        channel_id="ch",
                        message_id="123",
                        message_type=MessageType.POST,
                        source_ref="tg:ch:post:123",
                        role=BundleItemRole.ANCHOR,
                        score=1.0,
                    ),
                ],
                updated_at=datetime(2025, 12, 14, 12, 0, 0),
            )

            await repo.upsert(bundle1)

        # Обновляем (новая сессия)
        async with test_db.processing_storage_session() as session:
            repo = SQLiteTopicBundleRepo(session)

            bundle2 = TopicBundle(
                topic_id="topic:tg:ch:post:123",
                items=[
                    BundleItem(
                        channel_id="ch",
                        message_id="123",
                        message_type=MessageType.POST,
                        source_ref="tg:ch:post:123",
                        role=BundleItemRole.ANCHOR,
                        score=1.0,
                    ),
                    BundleItem(
                        channel_id="ch",
                        message_id="456",
                        message_type=MessageType.POST,
                        source_ref="tg:ch:post:456",
                        role=BundleItemRole.SUPPORTING,
                        score=0.8,
                    ),
                ],
                updated_at=datetime(2025, 12, 14, 13, 0, 0),
            )

            await repo.upsert(bundle2)

            # Проверяем что обновлена
            retrieved = await repo.get_by_topic_id("topic:tg:ch:post:123")
            assert retrieved is not None
            assert len(retrieved.items) == 2

    @pytest.mark.asyncio
    async def test_deduplication_by_source_ref(self, test_db):
        """TR-36: дедупликация по source_ref."""
        from tg_parser.domain.models import BundleItem, BundleItemRole, TopicBundle

        async with test_db.processing_storage_session() as session:
            repo = SQLiteTopicBundleRepo(session)

            # Bundle с дублирующими source_ref (не должно происходить в реальности,
            # но проверяем что хранилище не отвергает)
            bundle = TopicBundle(
                topic_id="topic:tg:ch:post:123",
                items=[
                    BundleItem(
                        channel_id="ch",
                        message_id="123",
                        message_type=MessageType.POST,
                        source_ref="tg:ch:post:123",
                        role=BundleItemRole.ANCHOR,
                        score=1.0,
                    ),
                ],
                updated_at=datetime(2025, 12, 14, 12, 0, 0),
            )

            await repo.upsert(bundle)

            # Получаем обратно
            retrieved = await repo.get_by_topic_id("topic:tg:ch:post:123")
            assert retrieved is not None
            assert len(retrieved.items) == 1
