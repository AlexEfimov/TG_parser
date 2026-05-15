"""
Порты (интерфейсы) для слоя хранения.

Реализует ADR-0004: порты не зависят от инфраструктуры.
Конкретные реализации (PostgreSQL) — в `tg_parser.storage.sqlalchemy`.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from tg_parser.domain.models import (
    BundleItem,
    DigestFormat,
    DigestSubscription,
    ProcessedDocument,
    RawTelegramMessage,
    TopicBundle,
    TopicCard,
    TopicCardVersion,
    TopicLink,
    WatchInterest,
    WatchMatch,
    Workspace,
)

# ============================================================================
# Job Storage (Phase 2F - Persistent Jobs)
# ============================================================================


class JobType(StrEnum):
    """Type of API job."""

    PROCESSING = "processing"
    EXPORT = "export"


class JobStatus(StrEnum):
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


@dataclass
class User:
    """Multi-tenancy user (F4)."""

    id: str
    name: str
    role: str = "user"
    max_channels: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class UserAuthMapping:
    """Maps an authentication credential to a user (F4)."""

    id: str
    user_id: str
    auth_type: str  # 'api_key' | 'telegram' | 'mcp_token'
    auth_identifier: str
    client_name: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class UserRepo(ABC):
    """Repository for multi-tenancy users (F4)."""

    @abstractmethod
    async def create_user(
        self, name: str, role: str = "user", max_channels: int | None = None
    ) -> User:
        pass

    @abstractmethod
    async def get_by_id(self, user_id: str) -> User | None:
        pass

    @abstractmethod
    async def resolve_auth(self, auth_type: str, auth_identifier: str) -> User | None:
        """Look up a user by auth credential (single JOIN query)."""
        pass

    @abstractmethod
    async def get_owned_channel_ids(self, user_id: str) -> list[str]:
        """Return channel_ids of sources owned by this user."""
        pass

    @abstractmethod
    async def add_auth_mapping(
        self,
        user_id: str,
        auth_type: str,
        auth_identifier: str,
        client_name: str | None = None,
    ) -> UserAuthMapping:
        pass

    @abstractmethod
    async def remove_auth_mapping(self, mapping_id: str) -> bool:
        pass

    @abstractmethod
    async def list_users(self) -> list[User]:
        pass

    @abstractmethod
    async def find_first_by_role(self, role: str) -> User | None:
        """Return the oldest user with the given role, or None if no match.

        Used by migrate-users (DI-11) and add-source (DI-13) to discover the
        admin seeded by migration b2c3d4e5f6a7 without relying on auth
        mappings (which may not exist yet on a fresh DB).
        """
        pass

    @abstractmethod
    async def delete_user(self, user_id: str) -> bool:
        pass

    @abstractmethod
    async def update_user(
        self,
        user_id: str,
        *,
        name: str | None = None,
        role: str | None = None,
        max_channels: Any = ...,
    ) -> User | None:
        """Update user fields. Pass max_channels=None to clear the limit; omit to keep unchanged."""
        pass


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
        owner_id: str | None = None,
        deleted_at: datetime | None = None,
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
        self.owner_id = owner_id
        # BUG-002 M3: when set, the source is soft-deleted and is
        # excluded from default reads (`get_source`, `list_sources`).
        self.deleted_at = deleted_at


class IngestionStateRepo(ABC):
    """
    Репозиторий состояния ingestion (TR-14, TR-15).

    Хранилище: PostgreSQL (таблицы sources, comment_cursors, source_attempts)
    """

    @abstractmethod
    async def get_source(self, source_id: str, *, include_deleted: bool = False) -> Source | None:
        """Получить источник по id.

        BUG-002 mitigation M3: по умолчанию soft-deleted источники
        не возвращаются. Передайте `include_deleted=True` чтобы найти
        в том числе помеченный как удалённый канал (для будущего
        reanimate-tool / админских проверок).
        """
        pass

    @abstractmethod
    async def get_source_by_username(
        self, username: str, *, include_deleted: bool = False
    ) -> "Source | None":
        """Получить источник по channel_username (BUG-010, Session I).

        Fallback-lookup когда пользователь передаёт username вместо
        числового source_id. Без нормализации — вызывающий должен
        передать уже normalize_channel_id()'d значение.
        """
        pass

    @abstractmethod
    async def list_sources(
        self,
        status: str | None = None,
        owner_id: str | None = None,
        *,
        include_deleted: bool = False,
    ) -> list[Source]:
        """Получить список источников (опционально отфильтрованный по статусу и/или владельцу).

        BUG-002 mitigation M3: по умолчанию soft-deleted источники
        исключаются из результата.
        """
        pass

    @abstractmethod
    async def upsert_source(self, source: Source) -> None:
        """Создать или обновить источник.

        BUG-002 mitigation M3: при upsert'е существующего soft-deleted
        канала колонка `deleted_at` сбрасывается в NULL — это даёт
        прозрачное «reanimate via add_channel» поведение, пока
        отдельный admin-tool не реализован.
        """
        pass

    @abstractmethod
    async def find_deleted_source(self, source_id: str) -> Source | None:
        """Найти soft-deleted источник по id (вне дефолтных фильтров).

        Возвращает Source с заполненным `deleted_at`, либо None если
        источник не существует или находится в active-состоянии. Это
        helper для будущего reanimate-tool / админских отчётов.
        """
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
        failed_stage: str | None = None,
        error_class: str | None = None,
        error_message: str | None = None,
        details: dict | None = None,
    ) -> None:
        """Записать попытку ingestion (TR-11, TR-15)."""
        pass

    @abstractmethod
    async def mark_attempt_started(self, source_id: str) -> None:
        """Synchronously commit ``last_attempt_at = now()`` for a source.

        BUG-024: called from the scheduler BEFORE the first pipeline
        ``await`` so the invariant «if the scheduler attempted a source,
        ``last_attempt_at`` is non-null» holds even on per-task crash /
        cancellation / outer-session-close failure. Idempotent — safe
        to call multiple times per tick (the value is monotonically
        advancing). Issues its own commit; caller does not need to.

        Companion to :py:meth:`record_attempt` which is called from the
        per-task ``finally`` and writes both ``last_attempt_at`` (again,
        with a later timestamp) plus the success / failure bookkeeping
        in ``source_attempts``. The two writes are independent: the
        synchronous pre-await write guarantees the invariant; the
        ``record_attempt`` write in ``finally`` updates the rest.
        """
        pass

    @abstractmethod
    async def get_channel_usernames(self) -> dict[str, str | None]:
        """
        Получить маппинг channel_id -> channel_username для всех источников.

        Returns:
            Dict с channel_id как ключом и channel_username как значением
        """
        pass

    @abstractmethod
    async def delete_source(self, source_id: str) -> bool:
        """Delete source and all its cursors/attempts. Returns True if source existed."""
        pass


# ============================================================================
# Raw Storage Repository
# ============================================================================


class RawMessageRepo(ABC):
    """
    Репозиторий raw-сообщений (TR-18, TR-20).

    Хранилище: PostgreSQL (таблица raw_messages)
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
    async def upsert_batch(self, messages: list[RawTelegramMessage]) -> int:
        """
        Batch upsert raw messages with a single COMMIT.

        Returns:
            Number of newly created rows (conflicts are skipped).
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

    @abstractmethod
    async def delete_by_channel(self, channel_id: str) -> int:
        """Delete all raw messages and conflicts for channel. Returns deleted message count."""
        pass

    @abstractmethod
    async def count_by_channel(self, channel_id: str) -> int:
        """Return count of raw messages for channel (without loading rows)."""
        pass


# ============================================================================
# Processing Storage Repository
# ============================================================================


class ProcessedDocumentRepo(ABC):
    """
    Репозиторий ProcessedDocument (TR-22, TR-43).

    Хранилище: PostgreSQL (таблица processed_documents)
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
    async def upsert_batch(self, docs: list[ProcessedDocument]) -> int:
        """
        Batch upsert processed documents with a single COMMIT.

        Returns:
            Number of upserted rows.
        """
        pass

    @abstractmethod
    async def get_by_source_ref(self, source_ref: str) -> ProcessedDocument | None:
        """Получить processed document по source_ref."""
        pass

    @abstractmethod
    async def get_by_source_refs(self, source_refs: list[str]) -> dict[str, ProcessedDocument]:
        """Batch-load documents by source_refs. Returns dict keyed by source_ref."""
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

    @abstractmethod
    async def delete_by_channel(self, channel_id: str) -> int:
        """Delete all processed documents for channel. Returns deleted count."""
        pass

    @abstractmethod
    async def count_by_channel(self, channel_id: str) -> int:
        """Return count of processed documents for channel (without loading rows)."""
        pass

    @abstractmethod
    async def list_source_refs_by_channel(self, channel_id: str) -> list[str]:
        """Return source_refs for channel (lightweight SELECT without full row data)."""
        pass

    @abstractmethod
    async def find_by_content_hash(
        self,
        channel_id: str,
        content_hash: str,
    ) -> "ProcessedDocument | None":
        """Return the first processed document in ``channel_id`` whose
        ``content_hash`` matches exactly, or ``None`` if absent.

        Lookup relies on the composite partial index
        ``idx_pd_channel_content_hash (channel_id, content_hash)
        WHERE content_hash IS NOT NULL`` (F5-A Phase 3).
        """
        pass


class ProcessingFailureRepo(ABC):
    """
    Репозиторий неудачной обработки (TR-47).

    Хранилище: PostgreSQL (таблица processing_failures)
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

    @abstractmethod
    async def delete_by_channel(self, channel_id: str) -> int:
        """Delete all processing failures for channel. Returns deleted count."""
        pass


# ============================================================================
# Topic Storage Repository
# ============================================================================


class TopicCardRepo(ABC):
    """
    Репозиторий TopicCard (TR-43).

    Хранилище: PostgreSQL (таблица topic_cards)
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

    @abstractmethod
    async def list_by_channels(self, channel_ids: list[str]) -> list[TopicCard]:
        """List topic cards visible to a user with these channels (F4 scoped access)."""
        pass

    @abstractmethod
    async def delete_by_channel(self, channel_id: str) -> int:
        """Delete all topic cards for a channel. Returns count of deleted rows."""
        pass

    # ------------------------------------------------------------------
    # F5-C Evolving Topic Summaries (a4b5c6d7e8f9)
    # ------------------------------------------------------------------

    @abstractmethod
    async def increment_resummary_counter(self, topic_id: str, by: int = 1) -> None:
        """Atomically bump ``new_items_since_last_summary`` for *topic_id*.

        Called from ``_update_bundles_for_assignments`` once per
        successfully-added BundleItem batch (F5-C trigger).  No-op if the
        topic does not exist (caller is expected to guard via add_items).
        """
        pass

    @abstractmethod
    async def list_resummarize_candidates(
        self, channel_id: str | None = None, *, threshold: int
    ) -> list[TopicCard]:
        """Return cards with ``new_items_since_last_summary >= threshold``.

        Backed by the partial index ``idx_topic_cards_resummarize_candidates``.
        When ``channel_id`` is None — return candidates across all channels.
        When given — filter to topics whose ``sources`` contains *channel_id*.
        """
        pass

    @abstractmethod
    async def commit_resummary(
        self,
        topic_id: str,
        *,
        summary: str,
        scope_in: list[str],
        scope_out: list[str],
        prev_summary_version: int,
        summarized_at: datetime,
        metadata_extras: dict[str, Any] | None = None,
    ) -> bool:
        """Atomically commit a fresh summary with optimistic version-check.

        Single ``UPDATE`` that simultaneously:
          * replaces ``summary`` / ``scope_in_json`` / ``scope_out_json``,
          * increments ``summary_version`` by 1 (guarded by
            ``WHERE summary_version = :prev_summary_version``),
          * resets ``new_items_since_last_summary`` to 0,
          * sets ``last_summarized_at`` and ``updated_at``,
          * COALESCEs ``metadata_json`` with *metadata_extras* (when given).

        Returns ``True`` on success, ``False`` if the optimistic check
        failed (another worker won the race) — the caller should treat
        the latter as a no-op and skip the version-snapshot write.

        This method intentionally REPLACES the older ``upsert + reset_after_resummary``
        pair, which had a no-op race window between the two statements.
        """
        pass


class TopicCardVersionRepo(ABC):
    """F5-C audit log repository for ``topic_card_versions``.

    Append-only.  ``list_by_topic`` is the only read path expected
    (MCP tool ``get_topic_versions``); the table is sized for low write
    rate (one row per re-summarize) and indexed on
    ``(topic_id, created_at DESC)``.
    """

    @abstractmethod
    async def insert(self, version: TopicCardVersion) -> int:
        """Insert a version snapshot. Returns the surrogate ``id``."""
        pass

    @abstractmethod
    async def list_by_topic(self, topic_id: str, limit: int = 50) -> list[TopicCardVersion]:
        """List versions for a topic ordered by ``created_at DESC``."""
        pass


class TopicBundleRepo(ABC):
    """
    Репозиторий TopicBundle (TR-43, TR-IF-5).

    Хранилище: PostgreSQL (таблица topic_bundles)
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

    @abstractmethod
    async def list_all(self) -> list[TopicBundle]:
        """Получить все актуальные topic bundles."""
        pass

    @abstractmethod
    async def add_items(self, topic_id: str, new_items: list[BundleItem]) -> TopicBundle:
        """Add items to an existing bundle, dedupe by source_ref.

        Session 35: incremental bundle update — appends new supporting items
        without rebuilding the entire bundle.
        """
        pass

    @abstractmethod
    async def delete_by_channel(self, channel_id: str) -> int:
        """Delete all topic bundles for a channel. Returns count of deleted rows."""
        pass


# ============================================================================
# Topic Link Repository (Cross-dev 3)
# ============================================================================


class TopicLinkRepo(ABC):
    """Repository for cross-channel topic links."""

    @abstractmethod
    async def upsert(self, link: TopicLink) -> None:
        """Create or update a topic link."""
        pass

    @abstractmethod
    async def upsert_batch(self, links: list[TopicLink]) -> int:
        """Batch upsert topic links. Returns count of upserted rows."""
        pass

    @abstractmethod
    async def get_by_topic_id(self, topic_id: str) -> list[TopicLink]:
        """Get all links for a given topic (as either side)."""
        pass

    @abstractmethod
    async def list_all(self) -> list[TopicLink]:
        """Get all topic links."""
        pass

    @abstractmethod
    async def delete_all(self) -> int:
        """Delete all links (for rebuild). Returns deleted count."""
        pass

    @abstractmethod
    async def count(self) -> int:
        """Return total count of topic links."""
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

    @abstractmethod
    async def delete_by_channel(self, channel_id: str) -> int:
        """Delete all jobs for a channel. Returns deleted count."""
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


# ============================================================================
# Embedding Repository (P5 RAG)
# ============================================================================


@dataclass
class DocumentEmbedding:
    """A stored embedding for a processed document or topic."""

    source_ref: str
    embedding: list[float]
    model: str
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
    entry_type: str = "message"
    topic_id: str | None = None
    channel_ids: list[str] = field(default_factory=list)


@dataclass
class SimilarityResult:
    """Result of a vector similarity search."""

    source_ref: str
    score: float
    entry_type: str = "message"
    topic_id: str | None = None


class EmbeddingRepo(ABC):
    """Repository for document embeddings (P5 RAG)."""

    @abstractmethod
    async def save(
        self,
        source_ref: str,
        embedding: list[float],
        model: str,
        metadata: dict[str, Any] | None = None,
        entry_type: str = "message",
        topic_id: str | None = None,
        channel_ids: list[str] | None = None,
    ) -> None:
        """Upsert an embedding for a document or topic."""
        pass

    @abstractmethod
    async def get_by_source_ref(self, source_ref: str) -> DocumentEmbedding | None:
        """Get embedding by source_ref."""
        pass

    @abstractmethod
    async def similarity_search(
        self,
        query_embedding: list[float],
        limit: int = 10,
        threshold: float = 0.0,
        entry_types: list[str] | None = None,
        channel_ids: list[str] | None = None,
    ) -> list[SimilarityResult]:
        """Find documents most similar to query_embedding (cosine similarity).

        Args:
            entry_types: Filter by entry type(s), e.g. ["message"], ["topic"],
                         or ["message", "topic"] for hybrid search.
                         None means no filter (all types).
            channel_ids: Filter to embeddings belonging to these channels.
                         None means no filter (admin = all channels).
        """
        pass

    @abstractmethod
    async def keyword_search(
        self,
        query: str,
        limit: int = 10,
        entry_types: list[str] | None = None,
        channel_ids: list[str] | None = None,
        min_rank: float = 0.0,
    ) -> list[SimilarityResult]:
        """Full-text (FTS) search over processed_documents and topic_cards.

        Implementation uses ``plainto_tsquery('simple', query)`` against the
        STORED ``search_vector`` columns and ranks with ``ts_rank_cd``.
        ``source_ref`` is the processed-document source ref for messages and
        the topic id for topics (mirroring ``similarity_search``).

        Args:
            query: Natural-language query; tokenized via
                ``plainto_tsquery('simple', ...)``.  Multi-language matching
                is supported because the generated ``search_vector`` columns
                blend simple + russian + english configurations.
            limit: Max rows fetched from the UNION result.
            entry_types: Post-fetch Python filter by ``entry_type`` (
                ``"message"`` / ``"topic"``).  ``None`` means no filter.
            channel_ids: SQL filter for ``processed_documents.channel_id``.
                Topic-card channel filtering happens downstream in
                ``retrieval_service`` via ``card.sources`` (Phase 1 does not
                add a GIN index for ``topic_cards.channel_ids``).
            min_rank: Python-side cutoff on the ``ts_rank_cd`` score.
        """
        pass

    @abstractmethod
    async def count(self) -> int:
        """Return total number of stored embeddings."""
        pass

    @abstractmethod
    async def list_missing(self, channel_id: str) -> list[str]:
        """Return source_refs from processed_documents that lack embeddings."""
        pass

    @abstractmethod
    async def delete_by_channel(self, channel_id: str) -> int:
        """Delete all embeddings for documents of a channel. Returns deleted count."""
        pass


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
    async def delete_by_channel(self, channel_id: str) -> int:
        """Delete all task records for a channel. Returns deleted count."""
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


# ============================================================================
# Digest Subscriptions (F6 Scheduled Digests)
# ============================================================================


class DigestSubscriptionRepo(ABC):
    """
    Repository for scheduled-digest subscriptions (F6).

    Storage: PostgreSQL (`digest_subscriptions` in ingestion DB).
    """

    @abstractmethod
    async def create(self, sub: DigestSubscription) -> DigestSubscription:
        """Persist a new subscription. Returns the row with server-side defaults populated."""
        pass

    @abstractmethod
    async def get(self, subscription_id: str) -> DigestSubscription | None:
        """Look up a subscription by id; returns None if absent."""
        pass

    @abstractmethod
    async def update(
        self,
        subscription_id: str,
        *,
        is_active: bool | None = None,
        last_sent_at: datetime | None = None,
        last_digest_cursor: datetime | None = None,
        cron_expression: str | None = None,
        timezone: str | None = None,
        format: DigestFormat | None = None,
        language: str | None = None,
        chat_id: int | None = None,
        name: str | None = None,
        channel_ids: list[str] | None = None,
    ) -> DigestSubscription | None:
        """
        Partial update. Pass only fields that should change; omitted fields retain their value.

        Note: ``last_sent_at`` and ``last_digest_cursor`` are nullable in the schema, but this
        method does NOT support setting them back to NULL — pass non-None values to update or
        omit to keep unchanged. (No use case for un-setting cursors today.)
        """
        pass

    @abstractmethod
    async def delete(self, subscription_id: str) -> bool:
        """Delete a subscription. Returns True if a row was removed."""
        pass

    @abstractmethod
    async def list_by_owner(self, owner_id: str) -> list[DigestSubscription]:
        """All subscriptions owned by ``owner_id``, ordered by created_at."""
        pass

    @abstractmethod
    async def list_all(self) -> list[DigestSubscription]:
        """Every subscription regardless of active state (admin views)."""
        pass

    @abstractmethod
    async def list_active(self) -> list[DigestSubscription]:
        """All ``is_active = true`` subscriptions (used by scheduler bootstrap + reconciliation)."""
        pass


# ============================================================================
# Watchlist (F11 Topic Watchlist)
# ============================================================================


class WatchInterestRepo(ABC):
    """Repository for persistent user-defined interests (F11).

    Storage: PostgreSQL (``watch_interests`` in ingestion DB).
    """

    @abstractmethod
    async def create(self, interest: WatchInterest) -> WatchInterest:
        """Persist a new interest. Returns the row with server-side defaults populated."""
        pass

    @abstractmethod
    async def get(self, interest_id: str) -> WatchInterest | None:
        """Look up an interest by id; returns None if absent."""
        pass

    @abstractmethod
    async def list_for_user(self, user_id: str) -> list[WatchInterest]:
        """Return all interests for ``user_id`` regardless of active state."""
        pass

    @abstractmethod
    async def list_all(self) -> list[WatchInterest]:
        """Return every interest in the system (admin scope).

        Includes inactive (soft-deleted) rows so admin tooling can audit the
        full history. Sorting is implementation-defined; the SA repo orders
        by ``created_at`` ascending for deterministic CLI / MCP output.
        """
        pass

    @abstractmethod
    async def list_active_for_channel(self, channel_id: str) -> list[WatchInterest]:
        """Return active interests whose ``channel_ids`` includes ``channel_id``.

        The watchlist scheduler hook calls this once per source per tick to
        scope interests to the channel that produced ``new_doc_refs``.
        """
        pass

    @abstractmethod
    async def update_embedding(self, interest_id: str, embedding: list[float]) -> None:
        """Persist or refresh the cached embedding for an interest.

        Decoupled from ``create`` so the embedding can be recomputed lazily
        (e.g. after model upgrade) without touching scoring code.
        """
        pass

    @abstractmethod
    async def soft_delete(self, interest_id: str) -> bool:
        """Mark an interest as ``is_active = false``. Returns True if a row changed.

        Hard delete is intentionally not exposed: ``watch_matches`` carries
        provenance that must survive unsubscribe.
        """
        pass

    @abstractmethod
    async def touch_checked(self, interest_id: str, at: datetime) -> None:
        """Record the timestamp of the most recent ``check_interests`` call."""
        pass

    @abstractmethod
    async def touch_match(self, interest_id: str, at: datetime) -> None:
        """Record the timestamp of the most recent recorded match."""
        pass


class WatchMatchRepo(ABC):
    """Repository for the per-interest match log (F11).

    Storage: PostgreSQL (``watch_matches`` in ingestion DB).
    """

    @abstractmethod
    async def upsert_many(self, matches: list[WatchMatch]) -> list[WatchMatch]:
        """Idempotent batch insert.

        Uses ``INSERT ... ON CONFLICT (interest_id, source_ref) DO NOTHING``.
        Returns only freshly inserted rows so callers can ``notify`` exactly
        once even when the same pipeline tick is replayed.
        """
        pass

    @abstractmethod
    async def list_for_interest(
        self, interest_id: str, since: datetime | None = None
    ) -> list[WatchMatch]:
        """Return matches for an interest ordered by ``created_at`` ascending.

        ``since`` is a strict-``>`` filter on ``created_at`` for cursor-style
        reads (CLI ``watchlist matches --since ...``).
        """
        pass

    @abstractmethod
    async def mark_notified(self, match_ids: list[int]) -> None:
        """Flip ``notified = true`` for the given match ids (post-send)."""
        pass


# ============================================================================
# Workspaces (F4-B Core)
# ============================================================================


class WorkspaceRepo(ABC):
    """Repository for thematic workspace collections (F4-B Core).

    Storage: PostgreSQL (``workspaces`` + ``workspace_sources`` in
    ingestion DB). Each workspace is owned by exactly one user
    (``owner_id``); the M2M ``workspace_sources`` table holds channel
    membership with composite PK ``(workspace_id, source_id)``.
    """

    @abstractmethod
    async def create(
        self,
        *,
        owner_id: str,
        name: str,
        description: str | None = None,
    ) -> Workspace:
        """Insert a new workspace. Raises on UNIQUE (owner_id, name) conflict."""
        pass

    @abstractmethod
    async def get(self, workspace_id: str) -> Workspace | None:
        """Look up a workspace by id; returns None if absent."""
        pass

    @abstractmethod
    async def list_by_owner(self, owner_id: str) -> list[Workspace]:
        """All workspaces owned by ``owner_id`` ordered by ``created_at``."""
        pass

    @abstractmethod
    async def list_all(self, owner_id: str | None = None) -> list[Workspace]:
        """Every workspace in the system (admin scope), optional owner filter.

        Sorted by ``created_at`` ascending for deterministic CLI / MCP output.
        """
        pass

    @abstractmethod
    async def rename(self, workspace_id: str, new_name: str) -> Workspace | None:
        """Update the workspace name. Returns the refreshed row, or None if absent."""
        pass

    @abstractmethod
    async def delete(self, workspace_id: str) -> bool:
        """Delete the workspace. Returns True if a row was removed.

        ON DELETE CASCADE on ``workspace_sources.workspace_id`` cleans up M2M
        rows automatically; the underlying ``sources`` are preserved.
        """
        pass

    @abstractmethod
    async def add_source(self, workspace_id: str, source_id: str) -> bool:
        """Attach a channel to a workspace.

        Returns True when a new M2M row was inserted, False when the channel
        was already in the workspace (``ON CONFLICT DO NOTHING``).
        """
        pass

    @abstractmethod
    async def remove_source(self, workspace_id: str, source_id: str) -> bool:
        """Detach a channel from a workspace. Returns True if a row existed."""
        pass

    @abstractmethod
    async def list_source_ids(self, workspace_id: str) -> list[str]:
        """Return the ``source_id`` list for a workspace (sorted).

        Powers introspection / MCP ``list_workspace_sources`` — kept
        lightweight (single SELECT on the M2M table).
        """
        pass

    @abstractmethod
    async def list_channel_ids(self, workspace_id: str) -> list[str]:
        """Return ``sources.channel_id`` list for a workspace (sorted).

        Joins ``workspace_sources`` → ``sources`` so that the result lives
        in the same identifier space as ``CurrentUser.allowed_channel_ids``
        (which is a list of ``channel_id``s, not ``source_id``s). Soft-deleted
        sources are excluded — they no longer participate in F4-A scope and
        F4-B mirrors that contract. Powers the ``effective_channel_ids``
        resolver in ``WorkspaceService``.
        """
        pass

    @abstractmethod
    async def resolve_source_id_for_channel(
        self,
        *,
        owner_id: str | None,
        channel_id: str,
    ) -> str | None:
        """Translate a user-facing ``channel_id`` to the underlying ``source_id``.

        Looks up an **active** (``deleted_at IS NULL``) row in ``sources``
        matching ``channel_id``. When ``owner_id`` is provided the lookup
        is scoped to that owner — required by the F4-B surface so that two
        users with the same ``channel_id`` (legacy F4-A behavior) never
        clash. ``owner_id=None`` means admin scope.

        Returns ``None`` when no matching source exists; the service layer
        translates that to a :class:`WorkspaceSourceNotFound`.
        """
        pass
