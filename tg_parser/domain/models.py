"""
Доменные модели TG_parser (Pydantic v2), согласованные с JSON-схемами в `docs/contracts/`.

Реализует требования TR-IF-1: обмен между модулями через структуры из контрактов.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ============================================================================
# Enums
# ============================================================================


class MessageType(str, Enum):
    """Тип сообщения Telegram."""

    POST = "post"
    COMMENT = "comment"


class TopicType(str, Enum):
    """Тип темы."""

    SINGLETON = "singleton"
    CLUSTER = "cluster"


class BundleItemRole(str, Enum):
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
    score: float | None = Field(
        None, ge=0.0, le=1.0, description="Оценка релевантности/якорности"
    )
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
    metadata: dict[str, Any] | None = Field(
        None, description="Произвольные дополнительные данные"
    )

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
