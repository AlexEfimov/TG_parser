"""
Tests for cross-channel topic linking service (Cross-dev 3).
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_parser.domain.models import (
    Anchor,
    MessageType,
    TopicCard,
    TopicLink,
    TopicType,
)
from tg_parser.services.topic_linking_service import (
    _cosine_similarity,
    _jaccard_similarity,
    get_related_topics_for,
    link_topics,
)
from tg_parser.storage.ports import DocumentEmbedding

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)


def _make_topic_card(
    topic_id: str,
    channel_id: str,
    title: str = "Test Topic",
    tags: list[str] | None = None,
    scope_in: list[str] | None = None,
) -> TopicCard:
    return TopicCard(
        id=topic_id,
        title=title,
        summary="Summary",
        scope_in=scope_in or ["генетика", "днк-тесты"],
        scope_out=["не относится"],
        type=TopicType.SINGLETON,
        anchors=[
            Anchor(
                channel_id=channel_id,
                message_id="1",
                message_type=MessageType.POST,
                anchor_ref=f"tg:{channel_id}:post:1",
                score=1.0,
            )
        ],
        sources=[channel_id],
        updated_at=NOW,
        tags=tags,
    )


def _make_embedding(source_ref: str, vector: list[float]) -> DocumentEmbedding:
    return DocumentEmbedding(
        source_ref=source_ref,
        embedding=vector,
        model="text-embedding-3-small",
        created_at=NOW,
    )


# ---------------------------------------------------------------------------
# Unit tests for similarity functions
# ---------------------------------------------------------------------------


class TestJaccardSimilarity:
    def test_identical_sets(self):
        score, shared = _jaccard_similarity({"a", "b", "c"}, {"a", "b", "c"})
        assert score == 1.0
        assert shared == ["a", "b", "c"]

    def test_disjoint_sets(self):
        score, shared = _jaccard_similarity({"a", "b"}, {"c", "d"})
        assert score == 0.0
        assert shared == []

    def test_partial_overlap(self):
        score, shared = _jaccard_similarity({"a", "b", "c"}, {"b", "c", "d"})
        assert score == pytest.approx(2 / 4)
        assert shared == ["b", "c"]

    def test_empty_sets(self):
        score, shared = _jaccard_similarity(set(), {"a"})
        assert score == 0.0
        score2, _ = _jaccard_similarity(set(), set())
        assert score2 == 0.0


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 0.0, 1.0]
        assert _cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        v1 = [1.0, 0.0, 0.0]
        v2 = [0.0, 1.0, 0.0]
        assert _cosine_similarity(v1, v2) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        v1 = [1.0, 0.0]
        v2 = [-1.0, 0.0]
        assert _cosine_similarity(v1, v2) == pytest.approx(-1.0)

    def test_empty_vectors(self):
        assert _cosine_similarity([], [1.0]) == 0.0
        assert _cosine_similarity([], []) == 0.0

    def test_zero_vector(self):
        assert _cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


# ---------------------------------------------------------------------------
# Integration tests (mocked DB)
# ---------------------------------------------------------------------------


class TestLinkTopics:
    async def test_links_created_for_similar_topics(self):
        cards = [
            _make_topic_card("t:1", "ch1", tags=["витамины", "кровь"]),
            _make_topic_card("t:2", "ch2", tags=["витамины", "генетика"]),
            _make_topic_card("t:3", "ch2", tags=["спорт", "бег"]),
        ]

        emb1 = _make_embedding("tg:ch1:post:1", [1.0, 0.0, 0.0])
        emb2 = _make_embedding("tg:ch2:post:1", [0.9, 0.1, 0.0])
        emb3 = _make_embedding("tg:ch2:post:1", [0.0, 0.0, 1.0])

        topic_card_repo = AsyncMock()
        topic_card_repo.list_all.return_value = cards
        topic_card_repo.get_by_id.side_effect = lambda tid: next(
            (c for c in cards if c.id == tid), None,
        )

        topic_bundle_repo = AsyncMock()

        topic_link_repo = AsyncMock()
        topic_link_repo.delete_all.return_value = 0
        topic_link_repo.upsert_batch.return_value = 1

        embedding_repo = AsyncMock()

        def get_emb(ref):
            mapping = {
                "tg:ch1:post:1": emb1,
                "tg:ch2:post:1": emb2,
            }
            return mapping.get(ref)

        embedding_repo.get_by_source_ref.side_effect = get_emb

        db = MagicMock()

        @asynccontextmanager
        async def mock_topic_linking_repos():
            yield (topic_card_repo, topic_bundle_repo, topic_link_repo, embedding_repo, db)

        with patch(
            "tg_parser.services.topic_linking_service.topic_linking_repos",
            mock_topic_linking_repos,
        ):
            result = await link_topics(threshold=0.1)

        assert result.total_pairs_evaluated == 2
        assert result.links_above_threshold >= 1
        topic_link_repo.upsert_batch.assert_called_once()
        saved_links = topic_link_repo.upsert_batch.call_args[0][0]
        assert len(saved_links) >= 1
        assert all(isinstance(l, TopicLink) for l in saved_links)

    async def test_no_links_for_single_channel(self):
        cards = [
            _make_topic_card("t:1", "ch1", tags=["витамины"]),
            _make_topic_card("t:2", "ch1", tags=["генетика"]),
        ]

        topic_card_repo = AsyncMock()
        topic_card_repo.list_all.return_value = cards
        topic_bundle_repo = AsyncMock()
        topic_link_repo = AsyncMock()
        topic_link_repo.delete_all.return_value = 0
        embedding_repo = AsyncMock()
        db = MagicMock()

        @asynccontextmanager
        async def mock_topic_linking_repos():
            yield (topic_card_repo, topic_bundle_repo, topic_link_repo, embedding_repo, db)

        with patch(
            "tg_parser.services.topic_linking_service.topic_linking_repos",
            mock_topic_linking_repos,
        ):
            result = await link_topics()

        assert result.links_created == 0
        assert result.total_pairs_evaluated == 0


class TestGetRelatedTopics:
    async def test_returns_related_topics(self):
        card = _make_topic_card("t:2", "ch2", title="Related Topic")

        link = TopicLink(
            topic_id_a="t:1",
            topic_id_b="t:2",
            similarity_score=0.75,
            shared_keywords=["витамины"],
            created_at=NOW,
        )

        topic_card_repo = AsyncMock()
        topic_card_repo.get_by_id.return_value = card

        topic_bundle_repo = AsyncMock()
        topic_link_repo = AsyncMock()
        topic_link_repo.get_by_topic_id.return_value = [link]
        embedding_repo = AsyncMock()
        db = MagicMock()

        @asynccontextmanager
        async def mock_topic_linking_repos():
            yield (topic_card_repo, topic_bundle_repo, topic_link_repo, embedding_repo, db)

        with patch(
            "tg_parser.services.topic_linking_service.topic_linking_repos",
            mock_topic_linking_repos,
        ):
            result = await get_related_topics_for("t:1")

        assert len(result) == 1
        assert result[0]["topic_id"] == "t:2"
        assert result[0]["title"] == "Related Topic"
        assert result[0]["channel_id"] == "ch2"
        assert result[0]["similarity_score"] == 0.75
        assert result[0]["shared_keywords"] == ["витамины"]

    async def test_no_links(self):
        topic_card_repo = AsyncMock()
        topic_bundle_repo = AsyncMock()
        topic_link_repo = AsyncMock()
        topic_link_repo.get_by_topic_id.return_value = []
        embedding_repo = AsyncMock()
        db = MagicMock()

        @asynccontextmanager
        async def mock_topic_linking_repos():
            yield (topic_card_repo, topic_bundle_repo, topic_link_repo, embedding_repo, db)

        with patch(
            "tg_parser.services.topic_linking_service.topic_linking_repos",
            mock_topic_linking_repos,
        ):
            result = await get_related_topics_for("t:1")

        assert result == []
