"""
Порты (интерфейсы) для слоя хранения.

Реализует ADR-0004: порты не зависят от инфраструктуры.
Конкретные реализации (SQLite/PostgreSQL) будут в `tg_parser.storage.sqlite` и т.п.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from tg_parser.domain.models import (
    ProcessedDocument,
    RawTelegramMessage,
    TopicBundle,
    TopicCard,
)


# ============================================================================
# Job Storage (Phase 2F - Persistent Jobs)
# ============================================================================


class JobType(str, Enum):
    """Type of API job."""
    PROCESSING = "processing"
    EXPORT = "export"


class JobStatus(str, Enum):
    """Status of an API job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Job:
    """
    API Job model for persistent storage.
    
    Stores state of async processing/export jobs.
    """
    job_id: str
    job_type: JobType
    status: JobStatus
    created_at: datetime
    
    # Optional fields
    channel_id: str | None = None
    client: str | None = None  # Authenticated client name
    started_at: datetime | None = None
    completed_at: datetime | None = None
    
    # Progress tracking
    progress: dict[str, Any] = field(default_factory=dict)
    
    # Result/error
    result: dict[str, Any] | None = None
    error: str | None = None
    
    # Export-specific
    file_path: str | None = None
    download_url: str | None = None
    export_format: str | None = None
    
    # Webhook configuration
    webhook_url: str | None = None
    webhook_secret: str | None = None

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
        channel_username: str | None = None,
        history_from: datetime | None = None,
        history_to: datetime | None = None,
        poll_interval_seconds: int | None = None,
        batch_size: int | None = None,
        last_post_id: str | None = None,
        backfill_completed_at: datetime | None = None,
        last_attempt_at: datetime | None = None,
        last_success_at: datetime | None = None,
        fail_count: int = 0,
        last_error: str | None = None,
        rate_limit_until: datetime | None = None,
        comments_unavailable: bool = False,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
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
        self.created_at = created_at or datetime.now(UTC)
        self.updated_at = updated_at or datetime.now(UTC)


class IngestionStateRepo(ABC):
    """
    Репозиторий состояния ingestion (TR-14, TR-15).

    Хранилище: ingestion_state.sqlite
    """

    @abstractmethod
    async def get_source(self, source_id: str) -> Source | None:
        """Получить источник по id."""
        pass

    @abstractmethod
    async def list_sources(self, status: str | None = None) -> list[Source]:
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
        last_post_id: str | None = None,
        comment_cursors: dict[str, str] | None = None,  # thread_id -> last_comment_id
    ) -> None:
        """
        Обновить курсоры источника (TR-7, TR-10).

        TR-10: курсоры обновляются только после успешной записи raw.
        """
        pass

    @abstractmethod
    async def get_comment_cursor(self, source_id: str, thread_id: str) -> str | None:
        """Получить last_comment_id для треда."""
        pass

    @abstractmethod
    async def record_attempt(
        self,
        source_id: str,
        success: bool,
        error_class: str | None = None,
        error_message: str | None = None,
        details: dict | None = None,
    ) -> None:
        """Записать попытку ingestion (TR-11, TR-15)."""
        pass

    @abstractmethod
    async def get_channel_usernames(self) -> dict[str, str | None]:
        """
        Получить маппинг channel_id -> channel_username для всех источников.

        Returns:
            Dict с channel_id как ключом и channel_username как значением
        """
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
    async def get_by_source_ref(self, source_ref: str) -> RawTelegramMessage | None:
        """Получить raw-сообщение по source_ref."""
        pass

    @abstractmethod
    async def list_by_channel(
        self,
        channel_id: str,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int | None = None,
    ) -> list[RawTelegramMessage]:
        """Получить raw-сообщения канала (опционально с фильтрами)."""
        pass

    @abstractmethod
    async def record_conflict(
        self,
        source_ref: str,
        reason: str,
        new_payload: dict | None = None,
        new_text: str | None = None,
        new_date: datetime | None = None,
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
    async def get_by_source_ref(self, source_ref: str) -> ProcessedDocument | None:
        """Получить processed document по source_ref."""
        pass

    @abstractmethod
    async def list_by_channel(
        self,
        channel_id: str,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[ProcessedDocument]:
        """Получить processed documents канала."""
        pass

    @abstractmethod
    async def exists(self, source_ref: str) -> bool:
        """
        Проверить наличие processed document (TR-48).

        Для инкрементальной обработки.
        """
        pass

    @abstractmethod
    async def list_all(
        self,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int | None = None,
    ) -> list[ProcessedDocument]:
        """
        Получить все processed documents (для экспорта всех каналов).

        Args:
            from_date: Фильтр по дате "от" (опционально)
            to_date: Фильтр по дате "до" (опционально)
            limit: Максимальное количество документов (опционально)

        Returns:
            Список ProcessedDocument
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
        error_details: dict | None = None,
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
        channel_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
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
    async def get_by_id(self, topic_id: str) -> TopicCard | None:
        """Получить topic card по id."""
        pass

    @abstractmethod
    async def list_by_channel(self, channel_id: str) -> list[TopicCard]:
        """Получить topic cards канала."""
        pass

    @abstractmethod
    async def list_all(self) -> list[TopicCard]:
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
    async def get_by_topic_id(self, topic_id: str) -> TopicBundle | None:
        """Получить topic bundle по topic_id."""
        pass

    @abstractmethod
    async def list_by_channel(self, channel_id: str) -> list[TopicBundle]:
        """Получить topic bundles канала (через TopicCard.sources)."""
        pass


# ============================================================================
# Job Storage Repository (Phase 2F)
# ============================================================================


class JobRepo(ABC):
    """
    Repository for API jobs (Phase 2F - Persistent Job Storage).
    
    Stores processing and export job state persistently.
    """

    @abstractmethod
    async def create(self, job: Job) -> None:
        """Create a new job."""
        pass

    @abstractmethod
    async def get(self, job_id: str) -> Job | None:
        """Get job by ID."""
        pass

    @abstractmethod
    async def update(self, job: Job) -> None:
        """Update existing job."""
        pass

    @abstractmethod
    async def list_jobs(
        self,
        job_type: JobType | None = None,
        status: JobStatus | None = None,
        limit: int = 50,
    ) -> list[Job]:
        """
        List jobs with optional filters.
        
        Returns most recent first.
        """
        pass

    @abstractmethod
    async def delete_old_jobs(self, older_than: datetime) -> int:
        """
        Delete jobs older than specified date.
        
        Returns number of deleted jobs.
        """
        pass


# ============================================================================
# Agent State Persistence (Phase 3B)
# ============================================================================


@dataclass
class AgentState:
    """
    Persistent state of an agent.
    
    Stores metadata and accumulated statistics for recovery after restart.
    """
    name: str
    agent_type: str
    version: str = "1.0.0"
    description: str = ""
    capabilities: list[str] = field(default_factory=list)
    model: str | None = None
    provider: str | None = None
    is_active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    
    # Statistics
    total_tasks_processed: int = 0
    total_errors: int = 0
    avg_processing_time_ms: float = 0.0
    last_used_at: datetime | None = None
    
    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class TaskRecord:
    """
    Record of a task execution.
    
    Stores full input/output with TTL for archival.
    """
    id: str
    agent_name: str
    task_type: str
    input_data: dict[str, Any]
    output_data: dict[str, Any] | None = None
    source_ref: str | None = None
    channel_id: str | None = None
    success: bool = True
    error: str | None = None
    processing_time_ms: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None


@dataclass
class AgentDailyStats:
    """
    Aggregated daily statistics for an agent.
    
    Persists even after task history cleanup.
    """
    agent_name: str
    date: str  # YYYY-MM-DD
    task_type: str
    total_tasks: int = 0
    successful_tasks: int = 0
    failed_tasks: int = 0
    total_processing_time_ms: int = 0
    min_processing_time_ms: int | None = None
    max_processing_time_ms: int | None = None
    
    @property
    def avg_processing_time_ms(self) -> float:
        """Calculate average processing time."""
        if self.total_tasks == 0:
            return 0.0
        return self.total_processing_time_ms / self.total_tasks
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.total_tasks == 0:
            return 0.0
        return self.successful_tasks / self.total_tasks


@dataclass
class HandoffRecord:
    """
    Record of a handoff between agents.
    """
    id: str
    source_agent: str
    target_agent: str
    task_type: str
    status: str  # pending, accepted, in_progress, completed, failed, rejected
    priority: int = 5
    payload: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    processing_time_ms: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    accepted_at: datetime | None = None
    completed_at: datetime | None = None


class AgentStateRepo(ABC):
    """
    Repository for agent state persistence (Phase 3B).
    
    Stores agent metadata and statistics for recovery after restart.
    """

    @abstractmethod
    async def save(self, state: AgentState) -> None:
        """Save or update agent state."""
        pass

    @abstractmethod
    async def get(self, name: str) -> AgentState | None:
        """Get agent state by name."""
        pass

    @abstractmethod
    async def list_all(self, agent_type: str | None = None) -> list[AgentState]:
        """List all agent states, optionally filtered by type."""
        pass

    @abstractmethod
    async def delete(self, name: str) -> bool:
        """Delete agent state. Returns True if deleted."""
        pass

    @abstractmethod
    async def update_statistics(
        self,
        name: str,
        processing_time_ms: float,
        success: bool,
    ) -> None:
        """
        Update agent statistics after task completion.
        
        Updates: total_tasks_processed, total_errors, avg_processing_time_ms, last_used_at
        """
        pass


class TaskHistoryRepo(ABC):
    """
    Repository for task execution history (Phase 3B).
    
    Stores full input/output with TTL for archival.
    """

    @abstractmethod
    async def record(
        self,
        agent_name: str,
        task_type: str,
        input_data: dict[str, Any],
        output_data: dict[str, Any] | None = None,
        success: bool = True,
        error: str | None = None,
        processing_time_ms: int | None = None,
        source_ref: str | None = None,
        channel_id: str | None = None,
        retention_days: int | None = None,
    ) -> str:
        """
        Record a task execution.
        
        Returns: Task ID
        """
        pass

    @abstractmethod
    async def get(self, task_id: str) -> TaskRecord | None:
        """Get task record by ID."""
        pass

    @abstractmethod
    async def list_by_agent(
        self,
        agent_name: str,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int = 100,
    ) -> list[TaskRecord]:
        """List task records for an agent."""
        pass

    @abstractmethod
    async def list_by_channel(
        self,
        channel_id: str,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int = 100,
    ) -> list[TaskRecord]:
        """List task records for a channel."""
        pass

    @abstractmethod
    async def cleanup_expired(self) -> int:
        """
        Delete expired records.
        
        Returns: Number of deleted records
        """
        pass

    @abstractmethod
    async def get_expired_for_archive(
        self,
        limit: int = 1000,
    ) -> list[TaskRecord]:
        """Get expired records for archiving before deletion."""
        pass


class AgentStatsRepo(ABC):
    """
    Repository for aggregated agent statistics (Phase 3B).
    
    Daily statistics persist even after task history cleanup.
    """

    @abstractmethod
    async def record(
        self,
        agent_name: str,
        task_type: str,
        success: bool,
        processing_time_ms: int,
    ) -> None:
        """Record a task in daily statistics (upsert)."""
        pass

    @abstractmethod
    async def get_daily(
        self,
        agent_name: str,
        date: str,
        task_type: str | None = None,
    ) -> list[AgentDailyStats]:
        """Get daily statistics for an agent."""
        pass

    @abstractmethod
    async def get_range(
        self,
        agent_name: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[AgentDailyStats]:
        """Get statistics for a date range."""
        pass

    @abstractmethod
    async def get_summary(
        self,
        agent_name: str,
        days: int = 30,
    ) -> dict[str, Any]:
        """
        Get summary statistics for an agent.
        
        Returns aggregated stats over the specified number of days.
        """
        pass


class HandoffHistoryRepo(ABC):
    """
    Repository for handoff history between agents (Phase 3B).
    """

    @abstractmethod
    async def record(
        self,
        source_agent: str,
        target_agent: str,
        task_type: str,
        handoff_id: str,
        priority: int = 5,
        payload: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Record a new handoff request."""
        pass

    @abstractmethod
    async def update_status(
        self,
        handoff_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        processing_time_ms: int | None = None,
    ) -> None:
        """Update handoff status and result."""
        pass

    @abstractmethod
    async def get(self, handoff_id: str) -> HandoffRecord | None:
        """Get handoff record by ID."""
        pass

    @abstractmethod
    async def list_by_agent(
        self,
        agent_name: str,
        as_source: bool = True,
        status: str | None = None,
        limit: int = 100,
    ) -> list[HandoffRecord]:
        """List handoffs for an agent (as source or target)."""
        pass

    @abstractmethod
    async def get_statistics(
        self,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> dict[str, Any]:
        """Get handoff statistics."""
        pass
