"""
Тесты для канонизации идентификаторов и детерминизма.

Покрывает требования:
- TR-IF-5: формат source_ref
- TR-41: ProcessedDocument.id
- TR-IF-4: TopicCard.id
- TR-61: KnowledgeBaseEntry.id
"""

import pytest

from tg_parser.domain.ids import (
    make_anchor_ref,
    make_kb_message_id,
    make_kb_topic_id,
    make_processed_document_id,
    make_source_ref,
    make_topic_id,
)


class TestSourceRef:
    """Тесты для source_ref (TR-IF-5)."""
    
    def test_make_source_ref_post(self):
        """TR-IF-5: формат tg:<channel_id>:post:<message_id>"""
        ref = make_source_ref("channel_123", "post", "987")
        assert ref == "tg:channel_123:post:987"
    
    def test_make_source_ref_comment(self):
        """TR-IF-5: формат tg:<channel_id>:comment:<message_id>"""
        ref = make_source_ref("channel_123", "comment", "4551")
        assert ref == "tg:channel_123:comment:4551"
    
    def test_make_source_ref_rejects_colons(self):
        """source_ref не должен содержать двоеточия в компонентах."""
        with pytest.raises(ValueError, match="cannot contain colons"):
            make_source_ref("channel:123", "post", "987")
        
        with pytest.raises(ValueError, match="cannot contain colons"):
            make_source_ref("channel_123", "post", "98:7")
    
    def test_make_source_ref_rejects_invalid_type(self):
        """message_type должен быть post или comment."""
        with pytest.raises(ValueError, match="must be 'post' or 'comment'"):
            make_source_ref("channel_123", "invalid", "987")


class TestAnchorRef:
    """Тесты для anchor_ref (синоним source_ref для якорей)."""
    
    def test_make_anchor_ref_same_as_source_ref(self):
        """anchor_ref идентичен source_ref."""
        ref1 = make_source_ref("channel_123", "post", "987")
        ref2 = make_anchor_ref("channel_123", "post", "987")
        assert ref1 == ref2


class TestProcessedDocumentId:
    """Тесты для ProcessedDocument.id (TR-41)."""
    
    def test_make_processed_document_id(self):
        """TR-41: id = 'doc:' + source_ref"""
        source_ref = "tg:channel_123:post:987"
        doc_id = make_processed_document_id(source_ref)
        assert doc_id == "doc:tg:channel_123:post:987"


class TestTopicId:
    """Тесты для TopicCard.id (TR-IF-4)."""
    
    def test_make_topic_id(self):
        """TR-IF-4: id = 'topic:' + primary_anchor_ref"""
        anchor_ref = "tg:channel_123:post:987"
        topic_id = make_topic_id(anchor_ref)
        assert topic_id == "topic:tg:channel_123:post:987"


class TestKbEntryId:
    """Тесты для KnowledgeBaseEntry.id (TR-61)."""
    
    def test_make_kb_message_id(self):
        """TR-61: message-entry id = 'kb:msg:' + source_ref"""
        source_ref = "tg:channel_123:post:987"
        kb_id = make_kb_message_id(source_ref)
        assert kb_id == "kb:msg:tg:channel_123:post:987"
    
    def test_make_kb_topic_id(self):
        """TR-61: topic-entry id = 'kb:topic:' + topic_id"""
        topic_id = "topic:tg:channel_123:post:987"
        kb_id = make_kb_topic_id(topic_id)
        assert kb_id == "kb:topic:topic:tg:channel_123:post:987"


class TestDeterminism:
    """Тесты детерминизма: повторные вызовы дают те же результаты."""
    
    def test_source_ref_deterministic(self):
        """Повторные вызовы с теми же аргументами дают тот же результат."""
        ref1 = make_source_ref("ch", "post", "123")
        ref2 = make_source_ref("ch", "post", "123")
        assert ref1 == ref2
    
    def test_all_ids_deterministic(self):
        """Все id детерминированы от входов."""
        source_ref = make_source_ref("ch", "post", "123")
        
        doc_id1 = make_processed_document_id(source_ref)
        doc_id2 = make_processed_document_id(source_ref)
        assert doc_id1 == doc_id2
        
        topic_id1 = make_topic_id(source_ref)
        topic_id2 = make_topic_id(source_ref)
        assert topic_id1 == topic_id2
        
        kb_msg_id1 = make_kb_message_id(source_ref)
        kb_msg_id2 = make_kb_message_id(source_ref)
        assert kb_msg_id1 == kb_msg_id2
