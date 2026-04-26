"""
Доменные модели TG_parser (Pydantic v2), согласованные с JSON-схемами в `docs/contracts/`.

Реализует требования TR-IF-1: обмен между модулями через структуры из контрактов.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ============================================================================
# Enums
# ============================================================================


class MessageType(StrEnum):
    """Тип сообщения Telegram."""

    POST = "post"
    COMMENT = "comment"


class TopicType(StrEnum):
    """Тип темы."""

    SINGLETON = "singleton"
    CLUSTER = "cluster"


class BundleItemRole(StrEnum):
    """Роль материала в тематической подборке."""

    ANCHOR = "anchor"
    SUPPORTING = "supporting"


# ============================================================================
# RawTelegramMessage
# ============================================================================


class RawTelegramMessage(BaseModel):
    """
    Сырое сообщение из Telegram с минимальной нормализацией.

    Соответствует `docs/contracts/raw_telegram_message.schema.json`.

    Требования:
    - TR-6: связи комментариев (thread_id, parent_message_id)
    - TR-IF-5: source_ref = "tg:<channel_id>:<message_type>:<id>"
    - TR-20: raw_payload может быть усечён (256KB)
    """

    id: str = Field(description="Уникальный идентификатор сообщения (message_id как строка)")
    message_type: MessageType = Field(description="Тип сообщения: пост канала или комментарий")
    source_ref: str = Field(
        pattern=r"^tg:[^:]+:(post|comment):[^:]+$",
        description="Каноническая ссылка на материал (ключ идемпотентности)",
    )
    channel_id: str = Field(description="Идентификатор канала/чата")
    date: datetime = Field(description="Время отправки сообщения (UTC)")
    text: str = Field(description="Основной текст сообщения")

    # Optional fields
    parent_message_id: str | None = Field(
        None, description="Для комментария: id родительского сообщения"
    )
    thread_id: str | None = Field(None, description="Идентификатор треда/обсуждения")
    language: str | None = Field(None, description="Определённый язык сообщения")
    raw_payload: dict[str, Any] | None = Field(
        None, description="Объект из Telegram-клиента для отладки (может быть усечён до 256KB)"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "987",
                    "message_type": "post",
                    "source_ref": "tg:channel_123:post:987",
                    "channel_id": "channel_123",
                    "date": "2025-12-13T10:00:00Z",
                    "text": "Пост с полезной информацией...",
                }
            ]
        }
    )


# ============================================================================
# ProcessedDocument
# ============================================================================


class Entity(BaseModel):
    """Сущность, извлечённая из текста."""

    type: str = Field(description="Тип сущности (person, organization, etc.)")
    value: str = Field(description="Значение/название сущности")
    confidence: float | None = Field(None, ge=0.0, le=1.0, description="Уверенность")


class ProcessedDocument(BaseModel):
    """
    Результат обработки RawTelegramMessage: очищенный текст и извлечённая структура.

    Соответствует `docs/contracts/processed_document.schema.json`.

    Требования:
    - TR-21: 1 raw → 1 processed
    - TR-22: идемпотентность по source_ref
    - TR-41: id = "doc:" + source_ref
    - TR-23: metadata должен содержать pipeline_version, model_id, prompt_id
    """

    id: str = Field(description="Уникальный id (детерминированный от source_ref)")
    source_ref: str = Field(
        pattern=r"^tg:[^:]+:(post|comment):[^:]+$",
        description="Каноническая ссылка на первоисточник",
    )
    source_message_id: str = Field(description="Ссылка на исходный RawTelegramMessage.id")
    channel_id: str = Field(description="Идентификатор канала/чата")
    processed_at: datetime = Field(description="Время последнего успешного формирования/обновления")
    text_clean: str = Field(description="Очищенный и нормализованный текст")

    # Optional fields
    summary: str | None = Field(None, description="Краткое резюме, сгенерированное ИИ")
    topics: list[str] = Field(
        default_factory=list, description="Основные темы/категории (может быть пустым)"
    )
    entities: list[Entity] = Field(default_factory=list, description="Извлечённые сущности")
    language: str | None = Field(
        None, description="Определённый язык (вычисляется на этапе processing)"
    )
    metadata: dict[str, Any] | None = Field(
        None, description="Метаданные обработки (pipeline_version, model_id, prompt_id, parameters)"
    )
    content_hash: str | None = Field(
        None,
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 hex digest of normalized text_clean for exact-dedup (F5-A Phase 3)",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "doc:tg:channel_123:post:987",
                    "source_ref": "tg:channel_123:post:987",
                    "source_message_id": "987",
                    "channel_id": "channel_123",
                    "processed_at": "2025-12-13T12:00:00Z",
                    "text_clean": "Очищенный текст...",
                    "summary": "Краткое резюме",
                    "topics": ["тема1", "тема2"],
                    "language": "ru",
                }
            ]
        }
    )


# ============================================================================
# TopicCard
# ============================================================================


class Anchor(BaseModel):
    """
    Якорный первоисточник темы.

    Требования:
    - TR-IF-4: anchors уникальны по anchor_ref
    - TR-IF-4: для cluster сортируются по (score desc, anchor_ref asc)
    """

    channel_id: str
    message_id: str
    message_type: MessageType
    anchor_ref: str = Field(
        pattern=r"^tg:[^:]+:(post|comment):[^:]+$", description="Каноническая ссылка на материал"
    )
    score: float | None = Field(None, ge=0.0, le=1.0, description="Оценка релевантности/якорности")
    parent_message_id: str | None = None
    thread_id: str | None = None


class TopicCard(BaseModel):
    """
    Карточка темы: описание темы и ссылки на якорные первоисточники.

    Соответствует `docs/contracts/topic_card.schema.json`.

    Требования:
    - TR-IF-4: id = "topic:" + anchors[0].anchor_ref (детерминированный)
    - TR-35: критерии качества тем
    - TR-32: детерминизм тематизации
    """

    id: str = Field(description="Устойчивый id темы (topic:<primary_anchor_ref>)")
    title: str = Field(description="Название темы")
    summary: str = Field(description="Краткое описание темы (1–3 предложения)")
    scope_in: list[str] = Field(min_length=1, description="Что относится к теме")
    scope_out: list[str] = Field(min_length=1, description="Что не относится к теме")
    type: TopicType = Field(
        description="Тип темы: singleton (тема-статья) или cluster (тема-кластер)"
    )
    anchors: list[Anchor] = Field(
        min_length=1, description="Якорные первоисточники (уникальны по anchor_ref)"
    )
    sources: list[str] = Field(min_length=1, description="Список источников (каналов)")
    updated_at: datetime = Field(description="Момент последнего обновления карточки")

    # Optional fields
    tags: list[str] | None = Field(None, description="Теги/ключевые слова")
    related_topics: list[str] | None = Field(None, description="Ссылки на близкие темы (по id)")
    status: str | None = Field(None, description="Статус темы для workflow")
    metadata: dict[str, Any] | None = Field(
        None,
        description="Метаданные тематизации (topicization_run_id, pipeline_version, algorithm, parameters)",
    )

    # F5-C Evolving Topic Summaries (a4b5c6d7e8f9)
    last_summarized_at: datetime | None = Field(
        None,
        description="Wall-clock of the last successful F5-C re-summarize (NULL = pre-F5-C row)",
    )
    summary_version: int = Field(
        default=1,
        ge=1,
        description="Per-topic monotonic version counter; +=1 on each commit_resummary",
    )
    new_items_since_last_summary: int = Field(
        default=0,
        ge=0,
        description="F5-C trigger counter; ResummarizationService resets to 0 on success",
    )

    @field_validator("anchors")
    @classmethod
    def validate_cluster_anchors(cls, v: list[Anchor], info) -> list[Anchor]:
        """
        Для cluster-темы проверить, что anchors >= 2 и имеют score.

        TR-35: cluster должен иметь минимум 2 якоря с score.
        """
        topic_type = info.data.get("type")
        if topic_type == TopicType.CLUSTER:
            if len(v) < 2:
                raise ValueError("Cluster topic must have at least 2 anchors")
            for anchor in v:
                if anchor.score is None:
                    raise ValueError("Cluster topic anchors must have score")
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "topic:tg:channel_123:post:987",
                    "title": "Анализ X: подготовка, показания, интерпретация",
                    "summary": "Кратко о том, когда назначают анализ X и как интерпретировать результаты.",
                    "scope_in": ["Показания", "Подготовка", "Интерпретация результатов"],
                    "scope_out": ["Лечение", "Сравнение с анализом Y"],
                    "type": "singleton",
                    "anchors": [
                        {
                            "channel_id": "channel_123",
                            "message_id": "987",
                            "message_type": "post",
                            "anchor_ref": "tg:channel_123:post:987",
                            "score": 1.0,
                        }
                    ],
                    "sources": ["channel_123"],
                    "updated_at": "2025-12-13T12:00:00Z",
                }
            ]
        }
    )


# ============================================================================
# TopicBundle
# ============================================================================


class TimeRange(BaseModel):
    """Диапазон дат для snapshot подборки."""

    from_: datetime = Field(alias="from", description="Начало диапазона")
    to: datetime = Field(description="Конец диапазона")


class BundleItem(BaseModel):
    """
    Материал в тематической подборке.

    Требования:
    - TR-36: дедупликация по source_ref
    - TR-36: anchors включаются с role="anchor"
    """

    channel_id: str
    message_id: str
    message_type: MessageType
    source_ref: str = Field(
        pattern=r"^tg:[^:]+:(post|comment):[^:]+$",
        description="Каноническая ссылка на материал (для дедупликации)",
    )
    role: BundleItemRole = Field(description="Роль материала: якорный или поддерживающий")

    # Optional fields
    parent_message_id: str | None = None
    thread_id: str | None = None
    score: float | None = Field(None, ge=0.0, le=1.0)
    justification: str | None = Field(None, description="Объяснение, почему материал включён")


class TopicAssignment(BaseModel):
    """
    Result of assigning a document to an existing topic (Phase 1 incremental topicization).

    Session 35: programmatic keyword matching assigns new docs to existing topics
    without LLM calls.
    """

    source_ref: str = Field(
        pattern=r"^tg:[^:]+:(post|comment):[^:]+$",
        description="Source ref of the assigned document",
    )
    topic_id: str = Field(description="ID of the topic the document was assigned to")
    score: float = Field(ge=0.0, le=1.0, description="Match score")
    method: str = Field(description="Assignment method: 'keyword' or 'llm'")


class IncrementalTopicizeResult(BaseModel):
    """
    Result of an incremental topicization run (Session 35).

    Captures assignments from Phase 1 (keyword) and Phase 2 (LLM, future),
    plus coverage metrics for monitoring.
    """

    assigned_keyword: list[TopicAssignment] = Field(default_factory=list)
    assigned_llm: list[TopicAssignment] = Field(default_factory=list)
    new_topics: list["TopicCard"] = Field(default_factory=list)
    unassignable: list[str] = Field(default_factory=list)
    tokens_used: int = 0
    coverage_before: float = 0.0
    coverage_after: float = 0.0
    cross_channel_links_created: int = 0


class TopicBundle(BaseModel):
    """
    Тематическая подборка: связь темы с релевантными материалами.

    Соответствует `docs/contracts/topic_bundle.schema.json`.

    Требования:
    - TR-43/TR-IF-5: upsert по topic_id (одна актуальная подборка в MVP)
    - TR-36: формирование из anchors + supporting
    """

    topic_id: str = Field(description="Ссылка на TopicCard.id")
    items: list[BundleItem] = Field(min_length=1, description="Материалы, входящие в подборку")
    updated_at: datetime = Field(description="Момент последнего обновления подборки")

    # Optional fields
    time_range: TimeRange | None = Field(
        None, description="Опциональный диапазон дат (для snapshot)"
    )
    channels: list[str] | None = Field(
        None, description="Список каналов, материалы которых вошли в подборку"
    )
    metadata: dict[str, Any] | None = Field(
        None,
        description="Метаданные (topicization_run_id, pipeline_version, algorithm, parameters)",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "topic_id": "topic:tg:channel_123:post:987",
                    "items": [
                        {
                            "channel_id": "channel_123",
                            "message_id": "987",
                            "message_type": "post",
                            "source_ref": "tg:channel_123:post:987",
                            "role": "anchor",
                            "score": 1.0,
                        }
                    ],
                    "updated_at": "2025-12-13T12:05:00Z",
                }
            ]
        }
    )


# ============================================================================
# TopicCardVersion (F5-C Evolving Topic Summaries — append-only audit log)
# ============================================================================


class TopicCardVersion(BaseModel):
    """
    Snapshot of a TopicCard's summary + scope at a given version.

    Persisted into ``topic_card_versions`` (one row per successful
    re-summarize).  The first version is **never** materialised — version 1
    is the initial summary that came out of topicization, and we only start
    writing rows on the second-and-later resummaries.
    """

    id: int = Field(ge=1, description="Surrogate primary key (BIGSERIAL)")
    topic_id: str = Field(description="FK -> topic_cards.id (ON DELETE CASCADE)")
    version_no: int = Field(ge=1, description="Per-topic monotonic version number")
    summary: str = Field(description="Snapshot of TopicCard.summary at this version")
    scope_in: list[str] = Field(min_length=1, description="Snapshot of scope_in")
    scope_out: list[str] = Field(min_length=1, description="Snapshot of scope_out")
    supporting_items_count_at_time: int = Field(
        ge=0,
        description="bundle.items count at the moment of re-summarize",
    )
    llm_provider: str | None = Field(None, description="openai|anthropic|gemini|ollama")
    llm_model: str | None = Field(None, description="LLM model id")
    prompt_version: str | None = Field(
        None, description="prompts/resummarize.yaml metadata.version"
    )
    created_at: datetime = Field(description="When the version row was inserted")


# ============================================================================
# TopicLink (Cross-dev 3: cross-channel topic linking)
# ============================================================================


class TopicLink(BaseModel):
    """Link between two topics from different channels based on semantic similarity."""

    topic_id_a: str = Field(description="ID of the first topic")
    topic_id_b: str = Field(description="ID of the second topic")
    similarity_score: float = Field(ge=0.0, le=1.0, description="Combined similarity score")
    shared_keywords: list[str] = Field(
        default_factory=list, description="Keywords shared by both topics"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(), description="Link creation time"
    )


# ============================================================================
# KnowledgeBaseEntry
# ============================================================================


class KnowledgeBaseEntrySource(BaseModel):
    """
    Информация об источнике записи в базе знаний.

    TR-57: поддержка типов telegram_message и topic
    """

    type: str = Field(description="Тип источника: 'telegram_message' или 'topic'")

    # For telegram_message type
    channel_id: str | None = None
    message_id: str | None = None
    message_type: MessageType | None = None
    source_ref: str | None = Field(None, pattern=r"^tg:[^:]+:(post|comment):[^:]+$")

    # For topic type
    topic_id: str | None = None


class KnowledgeBaseEntry(BaseModel):
    """
    Единица информации в базе знаний.

    Соответствует `docs/contracts/knowledge_base_entry.schema.json`.

    Требования:
    - TR-57: два типа entry (message и topic)
    - TR-61: детерминированные правила маппинга
    """

    id: str = Field(
        description="Устойчивый id записи (kb:msg:<source_ref> или kb:topic:<topic_id>)"
    )
    source: KnowledgeBaseEntrySource = Field(description="Информация об источнике")
    created_at: datetime = Field(description="Время создания записи в базе знаний")
    title: str = Field(description="Краткий заголовок/название")
    content: str = Field(description="Основное содержимое")

    # Optional fields
    topics: list[str] = Field(default_factory=list, description="Темы/категории для фильтрации")
    tags: list[str] = Field(default_factory=list, description="Дополнительные теги")
    vector: list[float] | None = Field(None, description="Опциональное векторное представление")
    metadata: dict[str, Any] | None = Field(None, description="Произвольные дополнительные данные")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "kb:msg:tg:channel_123:post:987",
                    "source": {
                        "type": "telegram_message",
                        "channel_id": "channel_123",
                        "message_id": "987",
                        "message_type": "post",
                        "source_ref": "tg:channel_123:post:987",
                    },
                    "created_at": "2025-12-13T12:00:00Z",
                    "title": "Пост 987",
                    "content": "Очищенный текст поста",
                    "topics": ["тема1"],
                }
            ]
        }
    )


# ============================================================================
# DigestSubscription (F6 Scheduled Digests)
# ============================================================================


class DigestFormat(StrEnum):
    """Output style for a scheduled digest."""

    SUMMARY = "summary"
    BULLETS = "bullets"
    DETAILED = "detailed"


class DigestSubscription(BaseModel):
    """
    User subscription to a scheduled digest of new ProcessedDocument-s.

    Persisted in `digest_subscriptions` (ingestion DB). The scheduler picks up
    active subscriptions and triggers `DigestService.run_for_subscription` per
    subscription on the configured cron. Owner of the subscription must own
    every channel in `channel_ids` (admins exempt).
    """

    id: str = Field(description="Subscription UUID")
    owner_id: str = Field(description="User UUID owning the subscription")
    chat_id: int = Field(description="Telegram chat_id where the digest is delivered")
    name: str = Field(min_length=1, max_length=200, description="Human label")
    channel_ids: list[str] = Field(min_length=1, description="Channels included in the digest")
    cron_expression: str = Field(
        default="0 9 * * *",
        max_length=100,
        description="Cron expression evaluated in `timezone`",
    )
    timezone: str = Field(default="UTC", max_length=50, description="IANA timezone name")
    format: DigestFormat = Field(default=DigestFormat.SUMMARY)
    language: str = Field(default="ru", max_length=10)
    is_active: bool = Field(default=True)
    last_sent_at: datetime | None = Field(
        default=None,
        description="Last delivery attempt (also set on suppressed empty digests)",
    )
    last_digest_cursor: datetime | None = Field(
        default=None,
        description="processed_at of the last document included; strict-`>` filter on next run",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now())
    updated_at: datetime = Field(default_factory=lambda: datetime.now())

    @field_validator("channel_ids")
    @classmethod
    def _channel_ids_nonempty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("channel_ids must contain at least one channel")
        return value

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "00000000-0000-0000-0000-000000000001",
                    "owner_id": "00000000-0000-0000-0000-000000000002",
                    "chat_id": 12345,
                    "name": "Daily morning brief",
                    "channel_ids": ["durov", "telegram"],
                    "cron_expression": "0 9 * * *",
                    "timezone": "Europe/Moscow",
                    "format": "summary",
                    "language": "ru",
                    "is_active": True,
                }
            ]
        }
    )


# ============================================================================
# WatchInterest / WatchMatch (F11 Topic Watchlist)
# ============================================================================


class NotifyMode(StrEnum):
    """Delivery mode for a watchlist match.

    MVP supports only ``INSTANT``; ``BATCH`` and ``SILENT`` are reserved for
    Phase 2 (digest-style aggregation and journal-only modes).
    """

    INSTANT = "instant"
    BATCH = "batch"
    SILENT = "silent"


class WatchInterest(BaseModel):
    """Persistent user-defined interest used by the F11 watchlist hook.

    Persisted in ``watch_interests`` (ingestion DB). Each tick of the
    incremental scheduler scores new ``ProcessedDocument`` against active
    interests via a hybrid keyword + cosine similarity check; matches above
    ``threshold`` are stored in ``watch_matches`` and dispatched through the
    bot to ``chat_id``.

    The ``embedding`` field caches the description (or canonical
    ``title + keywords`` fallback) embedding to avoid re-computation per
    pipeline tick.
    """

    id: str = Field(description="Interest UUID")
    user_id: str = Field(description="User UUID owning the interest")
    chat_id: int = Field(description="Telegram chat_id where notifications are delivered")
    title: str = Field(min_length=1, max_length=300, description="Short human label")
    description: str | None = Field(
        default=None,
        description="Free-form description; primary input for semantic embedding",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="Positive keywords for keyword-score (Jaccard-like over normalized tokens)",
    )
    exclude_keywords: list[str] = Field(
        default_factory=list,
        description="Negative filter; any match zeroes the interest for that document",
    )
    channel_ids: list[str] = Field(
        min_length=1,
        description="Channel IDs to watch; non-empty (DB constraint mirrors this)",
    )
    threshold: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Combined score required to record a match (MVP default 0.6)",
    )
    notify_mode: NotifyMode = Field(default=NotifyMode.INSTANT)
    is_active: bool = Field(default=True)
    embedding: list[float] | None = Field(
        default=None,
        description="Cached 1536-dim embedding of the canonical interest text",
    )
    last_checked_at: datetime | None = Field(
        default=None,
        description="Timestamp of the most recent ``check_interests`` call",
    )
    last_match_at: datetime | None = Field(
        default=None,
        description="Timestamp of the most recent recorded match",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now())
    updated_at: datetime = Field(default_factory=lambda: datetime.now())

    @field_validator("channel_ids")
    @classmethod
    def _channel_ids_nonempty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("channel_ids must contain at least one channel")
        return value

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "00000000-0000-0000-0000-000000000010",
                    "user_id": "00000000-0000-0000-0000-000000000002",
                    "chat_id": 12345,
                    "title": "MiCA / EU crypto regulation",
                    "description": "Regulatory news about cryptocurrency in the EU",
                    "keywords": ["MiCA", "crypto regulation", "EU"],
                    "exclude_keywords": ["meme", "shitcoin"],
                    "channel_ids": ["@crypto_news", "@eu_policy"],
                    "threshold": 0.6,
                    "notify_mode": "instant",
                    "is_active": True,
                }
            ]
        }
    )


class WatchMatch(BaseModel):
    """Evidence record for a single document/interest match.

    Persisted in ``watch_matches`` with ``UNIQUE(interest_id, source_ref)`` —
    re-runs of the pipeline on the same document do not duplicate
    notifications.

    Scores are kept separately for observability (a future
    ``tg_watchlist_matches_total{score_bucket=...}`` metric will read
    ``combined_score``) and for tuning the default threshold.
    """

    id: int = Field(description="Match BIGSERIAL id")
    interest_id: str = Field(description="WatchInterest UUID")
    source_ref: str = Field(
        pattern=r"^tg:[^:]+:(post|comment):[^:]+$",
        description="Canonical source ref of the matched ProcessedDocument",
    )
    channel_id: str = Field(description="Channel ID of the matched document")
    keyword_score: float = Field(ge=0.0, le=1.0, description="Keyword-overlap component")
    semantic_score: float = Field(ge=0.0, le=1.0, description="Cosine-similarity component")
    combined_score: float = Field(ge=0.0, le=1.0, description="Final hybrid score")
    notified: bool = Field(default=False, description="Set after successful Bot.send_message")
    created_at: datetime = Field(default_factory=lambda: datetime.now())

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": 1,
                    "interest_id": "00000000-0000-0000-0000-000000000010",
                    "source_ref": "tg:crypto_news:post:512",
                    "channel_id": "crypto_news",
                    "keyword_score": 0.5,
                    "semantic_score": 0.8,
                    "combined_score": 0.68,
                    "notified": True,
                }
            ]
        }
    )
