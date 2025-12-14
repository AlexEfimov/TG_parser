"""
Порты (интерфейсы) для слоя хранения.

Реализует ADR-0004: порты не зависят от инфраструктуры.
Конкретные реализации (SQLite/PostgreSQL) будут в `tg_parser.storage.sqlite` и т.п.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from tg_parser.domain.models import (
    ProcessedDocument,
    RawTelegramMessage,
    TopicBundle,
    TopicCard,
)


# ============================================================================
# Ingestion State Repository
# ============================================================================

class Source:
    """
    Модель состояния источника ingestion (TR-15).
    
    Не доменная модель (не экспортируется), а внутренний state ingestion.
    """
    
    def __init__(
        self,
        source_id: str,
        channel_id: str,
        status: str,  # active|paused|error
        include_comments: bool,
        channel_username: Optional[str] = None,
        history_from: Optional[datetime] = None,
        history_to: Optional[datetime] = None,
        poll_interval_seconds: Optional[int] = None,
        batch_size: Optional[int] = None,
        last_post_id: Optional[str] = None,
        backfill_completed_at: Optional[datetime] = None,
        last_attempt_at: Optional[datetime] = None,
        last_success_at: Optional[datetime] = None,
        fail_count: int = 0,
        last_error: Optional[str] = None,
        rate_limit_until: Optional[datetime] = None,
        comments_unavailable: bool = False,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.source_id = source_id
        self.channel_id = channel_id
        self.channel_username = channel_username
        self.status = status
        self.include_comments = include_comments
        self.history_from = history_from
        self.history_to = history_to
        self.poll_interval_seconds = poll_interval_seconds
        self.batch_size = batch_size
        self.last_post_id = last_post_id
        self.backfill_completed_at = backfill_completed_at
        self.last_attempt_at = last_attempt_at
        self.last_success_at = last_success_at
        self.fail_count = fail_count
        self.last_error = last_error
        self.rate_limit_until = rate_limit_until
        self.comments_unavailable = comments_unavailable
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()


class IngestionStateRepo(ABC):
    """
    Репозиторий состояния ingestion (TR-14, TR-15).
    
    Хранилище: ingestion_state.sqlite
    """
    
    @abstractmethod
    async def get_source(self, source_id: str) -> Optional[Source]:
        """Получить источник по id."""
        pass
    
    @abstractmethod
    async def list_sources(self, status: Optional[str] = None) -> List[Source]:
        """Получить список источников (опционально отфильтрованный по статусу)."""
        pass
    
    @abstractmethod
    async def upsert_source(self, source: Source) -> None:
        """Создать или обновить источник."""
        pass
    
    @abstractmethod
    async def update_cursors(
        self,
        source_id: str,
        last_post_id: Optional[str] = None,
        comment_cursors: Optional[dict[str, str]] = None,  # thread_id -> last_comment_id
    ) -> None:
        """
        Обновить курсоры источника (TR-7, TR-10).
        
        TR-10: курсоры обновляются только после успешной записи raw.
        """
        pass
    
    @abstractmethod
    async def get_comment_cursor(self, source_id: str, thread_id: str) -> Optional[str]:
        """Получить last_comment_id для треда."""
        pass
    
    @abstractmethod
    async def record_attempt(
        self,
        source_id: str,
        success: bool,
        error_class: Optional[str] = None,
        error_message: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> None:
        """Записать попытку ingestion (TR-11, TR-15)."""
        pass


# ============================================================================
# Raw Storage Repository
# ============================================================================

class RawMessageRepo(ABC):
    """
    Репозиторий raw-сообщений (TR-18, TR-20).
    
    Хранилище: raw_storage.sqlite
    """
    
    @abstractmethod
    async def upsert(self, message: RawTelegramMessage) -> bool:
        """
        Сохранить raw-сообщение с идемпотентностью по source_ref.
        
        TR-8: при конфликте не перезаписывать text/date ("snapshot").
        TR-18: уникальность по source_ref.
        
        Returns:
            True если запись создана/обновлена, False если был конфликт (snapshot).
        """
        pass
    
    @abstractmethod
    async def get_by_source_ref(self, source_ref: str) -> Optional[RawTelegramMessage]:
        """Получить raw-сообщение по source_ref."""
        pass
    
    @abstractmethod
    async def list_by_channel(
        self,
        channel_id: str,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[RawTelegramMessage]:
        """Получить raw-сообщения канала (опционально с фильтрами)."""
        pass
    
    @abstractmethod
    async def record_conflict(
        self,
        source_ref: str,
        reason: str,
        new_payload: Optional[dict] = None,
        new_text: Optional[str] = None,
        new_date: Optional[datetime] = None,
    ) -> None:
        """
        Записать коллизию/наблюдение при повторном ingestion (TR-8).
        
        Таблица: raw_conflicts
        """
        pass


# ============================================================================
# Processing Storage Repository
# ============================================================================

class ProcessedDocumentRepo(ABC):
    """
    Репозиторий ProcessedDocument (TR-22, TR-43).
    
    Хранилище: processing_storage.sqlite
    """
    
    @abstractmethod
    async def upsert(self, doc: ProcessedDocument) -> None:
        """
        Сохранить processed document с идемпотентностью по source_ref.
        
        TR-22: одно актуальное состояние на source_ref.
        TR-43: upsert/replace по source_ref.
        """
        pass
    
    @abstractmethod
    async def get_by_source_ref(self, source_ref: str) -> Optional[ProcessedDocument]:
        """Получить processed document по source_ref."""
        pass
    
    @abstractmethod
    async def list_by_channel(
        self,
        channel_id: str,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> List[ProcessedDocument]:
        """Получить processed documents канала."""
        pass
    
    @abstractmethod
    async def exists(self, source_ref: str) -> bool:
        """
        Проверить наличие processed document (TR-48).
        
        Для инкрементальной обработки.
        """
        pass


class ProcessingFailureRepo(ABC):
    """
    Репозиторий неудачной обработки (TR-47).
    
    Хранилище: processing_storage.sqlite (таблица processing_failures)
    """
    
    @abstractmethod
    async def record_failure(
        self,
        source_ref: str,
        channel_id: str,
        attempts: int,
        error_class: str,
        error_message: str,
        error_details: Optional[dict] = None,
    ) -> None:
        """Записать неудачную обработку сообщения."""
        pass
    
    @abstractmethod
    async def delete_failure(self, source_ref: str) -> None:
        """
        Удалить запись о неудаче (при успешной обработке).
        
        TR-47: при успехе processed должна исчезать запись в failures.
        """
        pass
    
    @abstractmethod
    async def list_failures(
        self,
        channel_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[dict]:
        """Получить список неудачных обработок (для CLI-отчётов)."""
        pass


# ============================================================================
# Topic Storage Repository
# ============================================================================

class TopicCardRepo(ABC):
    """
    Репозиторий TopicCard (TR-43).
    
    Хранилище: processing_storage.sqlite
    """
    
    @abstractmethod
    async def upsert(self, card: TopicCard) -> None:
        """
        Сохранить topic card с идемпотентностью по id.
        
        TR-43: upsert/replace по id.
        TR-IF-4: id детерминирован.
        """
        pass
    
    @abstractmethod
    async def get_by_id(self, topic_id: str) -> Optional[TopicCard]:
        """Получить topic card по id."""
        pass
    
    @abstractmethod
    async def list_by_channel(self, channel_id: str) -> List[TopicCard]:
        """Получить topic cards канала."""
        pass
    
    @abstractmethod
    async def list_all(self) -> List[TopicCard]:
        """Получить все topic cards (для экспорта topics.json)."""
        pass


class TopicBundleRepo(ABC):
    """
    Репозиторий TopicBundle (TR-43, TR-IF-5).
    
    Хранилище: processing_storage.sqlite
    """
    
    @abstractmethod
    async def upsert(self, bundle: TopicBundle) -> None:
        """
        Сохранить topic bundle с идемпотентностью по topic_id.
        
        TR-43: upsert/replace по topic_id (одна актуальная подборка в MVP).
        TR-IF-5: для MVP time_range не используется.
        """
        pass
    
    @abstractmethod
    async def get_by_topic_id(self, topic_id: str) -> Optional[TopicBundle]:
        """Получить topic bundle по topic_id."""
        pass
    
    @abstractmethod
    async def list_by_channel(self, channel_id: str) -> List[TopicBundle]:
        """Получить topic bundles канала (через TopicCard.sources)."""
        pass
