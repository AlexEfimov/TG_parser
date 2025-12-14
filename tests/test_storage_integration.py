"""
Integration тесты для SQLite storage.

Проверяет:
- TR-8: raw snapshot (идемпотентность)
- TR-10: атомарность курсоров
- TR-18: уникальность по source_ref
- TR-22: upsert processed documents
"""

import pytest
from datetime import datetime
from pathlib import Path
import tempfile

from tg_parser.domain.ids import make_processed_document_id, make_source_ref
from tg_parser.domain.models import MessageType, ProcessedDocument, RawTelegramMessage
from tg_parser.storage.sqlite import (
    Database,
    DatabaseConfig,
    SQLiteProcessedDocumentRepo,
    SQLiteRawMessageRepo,
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
