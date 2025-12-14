"""
Канонизация и генерация детерминированных идентификаторов.

Реализует требования:
- TR-IF-5: source_ref = "tg:<channel_id>:<message_type>:<id>"
- TR-41: ProcessedDocument.id = "doc:" + source_ref
- TR-IF-4: TopicCard.id = "topic:" + anchors[0].anchor_ref
- TR-61: KnowledgeBaseEntry.id детерминирован
"""


def make_source_ref(channel_id: str, message_type: str, message_id: str) -> str:
    """
    Создать канонический source_ref для материала.
    
    Формат: tg:<channel_id>:<message_type>:<message_id>
    
    Args:
        channel_id: Идентификатор канала/чата
        message_type: "post" или "comment"
        message_id: Идентификатор сообщения
        
    Returns:
        source_ref в формате tg:<channel_id>:<message_type>:<message_id>
        
    Raises:
        ValueError: если компоненты содержат двоеточия (запрещено схемой)
    """
    if ":" in channel_id or ":" in message_type or ":" in message_id:
        raise ValueError(
            f"Components cannot contain colons: "
            f"channel_id={channel_id}, message_type={message_type}, message_id={message_id}"
        )
    
    if message_type not in ("post", "comment"):
        raise ValueError(f"message_type must be 'post' or 'comment', got: {message_type}")
    
    return f"tg:{channel_id}:{message_type}:{message_id}"


def make_anchor_ref(channel_id: str, message_type: str, message_id: str) -> str:
    """
    Создать anchor_ref (синоним source_ref для якорей тем).
    
    Args:
        channel_id: Идентификатор канала/чата
        message_type: "post" или "comment"
        message_id: Идентификатор сообщения
        
    Returns:
        anchor_ref в формате tg:<channel_id>:<message_type>:<message_id>
    """
    return make_source_ref(channel_id, message_type, message_id)


def make_processed_document_id(source_ref: str) -> str:
    """
    Создать детерминированный id для ProcessedDocument.
    
    TR-41: ProcessedDocument.id = "doc:" + source_ref
    
    Args:
        source_ref: Каноническая ссылка на первоисточник
        
    Returns:
        id в формате doc:<source_ref>
    """
    return f"doc:{source_ref}"


def make_topic_id(primary_anchor_ref: str) -> str:
    """
    Создать детерминированный id для TopicCard.
    
    TR-IF-4: TopicCard.id = "topic:" + anchors[0].anchor_ref
    
    Args:
        primary_anchor_ref: anchor_ref первого (primary) якоря темы
        
    Returns:
        id в формате topic:<anchor_ref>
    """
    return f"topic:{primary_anchor_ref}"


def make_kb_message_id(source_ref: str) -> str:
    """
    Создать детерминированный id для KnowledgeBaseEntry уровня сообщения.
    
    TR-61: id = "kb:msg:" + source_ref
    
    Args:
        source_ref: Каноническая ссылка на первоисточник
        
    Returns:
        id в формате kb:msg:<source_ref>
    """
    return f"kb:msg:{source_ref}"


def make_kb_topic_id(topic_id: str) -> str:
    """
    Создать детерминированный id для KnowledgeBaseEntry уровня темы.
    
    TR-61: id = "kb:topic:" + topic_id
    
    Args:
        topic_id: Идентификатор темы (TopicCard.id)
        
    Returns:
        id в формате kb:topic:<topic_id>
    """
    return f"kb:topic:{topic_id}"
