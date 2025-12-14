"""
Базовые доменные модели, согласованные с JSON-схемами в `docs/contracts/`.

Здесь описаны только структуры данных без бизнес-логики.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, List, Mapping, Optional, Sequence


@dataclass
class RawTelegramMessage:
    """
    Соответствует `RawTelegramMessage` из `docs/contracts/raw_telegram_message.schema.json`.
    """

    id: str
    channel_id: str
    date: datetime
    text: str
    language: Optional[str] = None
    raw_payload: Mapping[str, Any] | None = None


@dataclass
class Entity:
    """
    Сущность, извлечённая из текста (например, человек, организация, объект).
    """

    type: str
    value: str
    confidence: Optional[float] = None


@dataclass
class ProcessedDocument:
    """
    Соответствует `ProcessedDocument` из
    `docs/contracts/processed_document.schema.json`.
    """

    id: str
    source_message_id: str
    channel_id: str
    processed_at: datetime
    text_clean: str
    summary: Optional[str] = None
    topics: List[str] = field(default_factory=list)
    entities: List[Entity] = field(default_factory=list)
    language: Optional[str] = None
    metadata: Mapping[str, Any] | None = None


@dataclass
class KnowledgeBaseEntrySource:
    """
    Информация об источнике записи в базе знаний.
    """

    type: str  # например: "telegram_message"
    channel_id: Optional[str] = None
    message_id: Optional[str] = None


@dataclass
class KnowledgeBaseEntry:
    """
    Соответствует `KnowledgeBaseEntry` из
    `docs/contracts/knowledge_base_entry.schema.json`.
    """

    id: str
    source: KnowledgeBaseEntrySource
    created_at: datetime
    title: str
    content: str
    topics: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    vector: Optional[Sequence[float]] = None
    metadata: Mapping[str, Any] | None = None


# Упрощённые типы для использования в интерфейсах модулей
RawMessages = Iterable[RawTelegramMessage]
ProcessedDocuments = Iterable[ProcessedDocument]
KnowledgeBaseEntries = Iterable[KnowledgeBaseEntry]






