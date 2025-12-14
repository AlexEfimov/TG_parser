"""
Доменный слой TG_parser: модели (Pydantic v2), идентификаторы, валидация контрактов.

Модели строго соответствуют JSON-схемам из `docs/contracts/`.
"""

from .contract_validation import ContractValidator, validate_contract
from .ids import (
    make_anchor_ref,
    make_kb_message_id,
    make_kb_topic_id,
    make_processed_document_id,
    make_source_ref,
    make_topic_id,
)
from .models import (
    Anchor,
    BundleItem,
    BundleItemRole,
    Entity,
    KnowledgeBaseEntry,
    KnowledgeBaseEntrySource,
    MessageType,
    ProcessedDocument,
    RawTelegramMessage,
    TimeRange,
    TopicBundle,
    TopicCard,
    TopicType,
)

__all__ = [
    # Models
    "RawTelegramMessage",
    "ProcessedDocument",
    "Entity",
    "TopicCard",
    "Anchor",
    "TopicBundle",
    "BundleItem",
    "TimeRange",
    "KnowledgeBaseEntry",
    "KnowledgeBaseEntrySource",
    # Enums
    "MessageType",
    "TopicType",
    "BundleItemRole",
    # ID utilities
    "make_source_ref",
    "make_anchor_ref",
    "make_processed_document_id",
    "make_topic_id",
    "make_kb_message_id",
    "make_kb_topic_id",
    # Validation
    "ContractValidator",
    "validate_contract",
]
