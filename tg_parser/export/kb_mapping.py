"""
Маппинг доменных моделей в KnowledgeBaseEntry.

Реализует TR-57/TR-61: два типа entry (message и topic) с детерминированными правилами.
"""

from datetime import datetime
from typing import Dict, List, Optional

from tg_parser.domain.ids import make_kb_message_id, make_kb_topic_id
from tg_parser.domain.models import (
    KnowledgeBaseEntry,
    KnowledgeBaseEntrySource,
    MessageType,
    ProcessedDocument,
    TopicBundle,
    TopicCard,
)


def map_message_to_kb_entry(
    doc: ProcessedDocument,
    telegram_url: Optional[str] = None,
) -> KnowledgeBaseEntry:
    """
    Создать KnowledgeBaseEntry из ProcessedDocument (TR-61: message-entry).
    
    Правила (TR-61):
    - id = "kb:msg:" + source_ref
    - source.type = "telegram_message"
    - created_at = processed_at
    - content = summary + "\\n\\n" + text_clean (если summary есть), иначе text_clean
    - topics = ProcessedDocument.topics
    - metadata.processing = ProcessedDocument.metadata
    - metadata.telegram_url = вычисленный URL (best-effort)
    
    Args:
        doc: ProcessedDocument
        telegram_url: Опциональный Telegram URL (best-effort)
        
    Returns:
        KnowledgeBaseEntry уровня сообщения
    """
    # Формируем content
    if doc.summary:
        content = f"{doc.summary}\n\n{doc.text_clean}"
    else:
        content = doc.text_clean
    
    # Извлекаем message_type из source_ref (предполагаем формат tg:<channel_id>:<type>:<id>)
    parts = doc.source_ref.split(":")
    message_type_str = parts[2] if len(parts) >= 4 else "post"
    
    # Metadata
    metadata: Dict = {}
    if doc.metadata:
        metadata["processing"] = doc.metadata
    if telegram_url:
        metadata["telegram_url"] = telegram_url
    
    return KnowledgeBaseEntry(
        id=make_kb_message_id(doc.source_ref),
        source=KnowledgeBaseEntrySource(
            type="telegram_message",
            channel_id=doc.channel_id,
            message_id=doc.source_message_id,
            message_type=MessageType(message_type_str),
            source_ref=doc.source_ref,
        ),
        created_at=doc.processed_at,
        title=f"Message {doc.source_message_id}",  # Минимальный title
        content=content,
        topics=doc.topics,
        tags=[],
        metadata=metadata if metadata else None,
    )


def map_topic_to_kb_entry(
    card: TopicCard,
    bundle: Optional[TopicBundle] = None,
    resolved_sources: Optional[List[Dict]] = None,
) -> KnowledgeBaseEntry:
    """
    Создать KnowledgeBaseEntry из TopicCard (TR-61: topic-entry).
    
    Правила (TR-61):
    - id = "kb:topic:" + topic_id
    - source.type = "topic"
    - created_at = TopicCard.updated_at
    - title = TopicCard.title
    - content = компактный: summary + scope_in/scope_out (без полного списка источников)
    - topics = [TopicCard.id] (для стабильного фильтра "по теме")
    - tags = TopicCard.tags
    - metadata.resolved_sources = таблица резолюции источников
    
    Args:
        card: TopicCard
        bundle: Опциональный TopicBundle (для метаданных)
        resolved_sources: Опциональная таблица резолюции источников
        
    Returns:
        KnowledgeBaseEntry уровня темы
    """
    # Формируем компактный content
    scope_in_str = ", ".join(card.scope_in)
    scope_out_str = ", ".join(card.scope_out)
    content = (
        f"{card.summary}\n\n"
        f"**Scope In:** {scope_in_str}\n"
        f"**Scope Out:** {scope_out_str}"
    )
    
    # Metadata
    metadata: Dict = {}
    if resolved_sources:
        metadata["resolved_sources"] = resolved_sources
    if card.metadata:
        metadata["topic_card"] = card.metadata
    if bundle and bundle.metadata:
        metadata["topic_bundle"] = bundle.metadata
    
    return KnowledgeBaseEntry(
        id=make_kb_topic_id(card.id),
        source=KnowledgeBaseEntrySource(
            type="topic",
            topic_id=card.id,
        ),
        created_at=card.updated_at,
        title=card.title,
        content=content,
        topics=[card.id],  # TR-61: для стабильного фильтра по теме
        tags=card.tags or [],
        metadata=metadata if metadata else None,
    )
