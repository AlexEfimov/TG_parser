"""
Тесты для Pydantic моделей (валидация контрактов).

Покрывает требования:
- TR-IF-1: модели соответствуют JSON Schema
- Валидация через Pydantic
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from tg_parser.domain.models import (
    Anchor,
    MessageType,
    ProcessedDocument,
    RawTelegramMessage,
    TopicCard,
    TopicType,
)


class TestRawTelegramMessage:
    """Тесты для RawTelegramMessage."""

    def test_valid_post(self):
        """Валидное post-сообщение."""
        msg = RawTelegramMessage(
            id="123",
            message_type=MessageType.POST,
            source_ref="tg:ch:post:123",
            channel_id="ch",
            date=datetime(2025, 12, 14, 10, 0, 0),
            text="Test message",
        )
        assert msg.message_type == MessageType.POST
        assert msg.source_ref == "tg:ch:post:123"

    def test_source_ref_pattern_validation(self):
        """source_ref должен соответствовать pattern."""
        with pytest.raises(ValidationError):
            RawTelegramMessage(
                id="123",
                message_type=MessageType.POST,
                source_ref="invalid_ref",  # Не соответствует pattern
                channel_id="ch",
                date=datetime(2025, 12, 14),
                text="Test",
            )

    def test_optional_fields(self):
        """Опциональные поля могут отсутствовать."""
        msg = RawTelegramMessage(
            id="123",
            message_type=MessageType.COMMENT,
            source_ref="tg:ch:comment:123",
            channel_id="ch",
            date=datetime(2025, 12, 14),
            text="Comment",
            # thread_id, parent_message_id, language, raw_payload отсутствуют
        )
        assert msg.thread_id is None
        assert msg.parent_message_id is None


class TestProcessedDocument:
    """Тесты для ProcessedDocument."""

    def test_valid_document(self):
        """Валидный ProcessedDocument."""
        doc = ProcessedDocument(
            id="doc:tg:ch:post:123",
            source_ref="tg:ch:post:123",
            source_message_id="123",
            channel_id="ch",
            processed_at=datetime(2025, 12, 14, 12, 0, 0),
            text_clean="Clean text",
        )
        assert doc.id == "doc:tg:ch:post:123"
        assert doc.topics == []  # default

    def test_topics_can_be_empty(self):
        """topics может быть пустым списком (TR-25)."""
        doc = ProcessedDocument(
            id="doc:tg:ch:post:123",
            source_ref="tg:ch:post:123",
            source_message_id="123",
            channel_id="ch",
            processed_at=datetime(2025, 12, 14),
            text_clean="Text",
            topics=[],
        )
        assert doc.topics == []


class TestTopicCard:
    """Тесты для TopicCard."""

    def test_valid_singleton_topic(self):
        """Валидная singleton тема."""
        card = TopicCard(
            id="topic:tg:ch:post:123",
            title="Topic Title",
            summary="Summary",
            scope_in=["item1"],
            scope_out=["item2"],
            type=TopicType.SINGLETON,
            anchors=[
                Anchor(
                    channel_id="ch",
                    message_id="123",
                    message_type=MessageType.POST,
                    anchor_ref="tg:ch:post:123",
                    score=1.0,
                )
            ],
            sources=["ch"],
            updated_at=datetime(2025, 12, 14),
        )
        assert card.type == TopicType.SINGLETON
        assert len(card.anchors) == 1

    def test_cluster_requires_min_2_anchors(self):
        """Cluster тема требует минимум 2 якоря (TR-35)."""
        with pytest.raises(ValidationError, match="at least 2 anchors"):
            TopicCard(
                id="topic:tg:ch:post:123",
                title="Title",
                summary="Summary",
                scope_in=["a"],
                scope_out=["b"],
                type=TopicType.CLUSTER,
                anchors=[
                    Anchor(
                        channel_id="ch",
                        message_id="123",
                        message_type=MessageType.POST,
                        anchor_ref="tg:ch:post:123",
                        score=0.9,
                    )
                ],  # Только 1 якорь
                sources=["ch"],
                updated_at=datetime(2025, 12, 14),
            )

    def test_cluster_requires_scores(self):
        """Cluster anchors должны иметь score (TR-35)."""
        with pytest.raises(ValidationError, match="must have score"):
            TopicCard(
                id="topic:tg:ch:post:123",
                title="Title",
                summary="Summary",
                scope_in=["a"],
                scope_out=["b"],
                type=TopicType.CLUSTER,
                anchors=[
                    Anchor(
                        channel_id="ch",
                        message_id="123",
                        message_type=MessageType.POST,
                        anchor_ref="tg:ch:post:123",
                        # score отсутствует
                    ),
                    Anchor(
                        channel_id="ch",
                        message_id="456",
                        message_type=MessageType.POST,
                        anchor_ref="tg:ch:post:456",
                        score=0.8,
                    ),
                ],
                sources=["ch"],
                updated_at=datetime(2025, 12, 14),
            )
