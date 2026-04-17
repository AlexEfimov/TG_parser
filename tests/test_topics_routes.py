"""
HTTP tests for Topics API routes: GET /api/v1/topics, /topics/{id}, /topics/{id}/bundle.

Mocks processing_repos() to avoid hitting real database.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tg_parser.api.main import create_app
from tg_parser.domain.models import (
    Anchor,
    BundleItem,
    BundleItemRole,
    MessageType,
    TopicBundle,
    TopicCard,
    TopicType,
)

NOW = datetime(2025, 12, 13, 12, 0, 0, tzinfo=UTC)


def _make_topic_card(
    topic_id: str = "topic:tg:ch:post:1",
    title: str = "Test Topic",
    topic_type: TopicType = TopicType.SINGLETON,
    sources: list[str] | None = None,
) -> TopicCard:
    return TopicCard(
        id=topic_id,
        title=title,
        summary="Test summary",
        scope_in=["scope in"],
        scope_out=["scope out"],
        type=topic_type,
        anchors=[
            Anchor(
                channel_id="ch",
                message_id="1",
                message_type=MessageType.POST,
                anchor_ref="tg:ch:post:1",
                score=1.0,
            )
        ],
        sources=sources or ["ch"],
        updated_at=NOW,
    )


def _make_bundle(topic_id: str = "topic:tg:ch:post:1") -> TopicBundle:
    return TopicBundle(
        topic_id=topic_id,
        items=[
            BundleItem(
                channel_id="ch",
                message_id="1",
                message_type=MessageType.POST,
                source_ref="tg:ch:post:1",
                role=BundleItemRole.ANCHOR,
            ),
            BundleItem(
                channel_id="ch",
                message_id="2",
                message_type=MessageType.COMMENT,
                source_ref="tg:ch:comment:2",
                role=BundleItemRole.SUPPORTING,
            ),
        ],
        updated_at=NOW,
    )


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


PATCH_TARGET = "tg_parser.services.db_context.processing_repos"


def _mock_processing_repos(
    topic_cards: list[TopicCard] | None = None,
    bundles: dict[str, TopicBundle] | None = None,
):
    """Create a mock context manager for processing_repos()."""
    topic_cards = topic_cards or []
    bundles = bundles or {}

    proc_repo = MagicMock()
    topic_card_repo = AsyncMock()
    topic_bundle_repo = AsyncMock()
    db = MagicMock()

    topic_card_repo.list_all.return_value = topic_cards
    topic_card_repo.list_by_channel.return_value = topic_cards

    async def get_card_by_id(tid):
        return next((c for c in topic_cards if c.id == tid), None)

    topic_card_repo.get_by_id.side_effect = get_card_by_id

    async def get_bundle(tid):
        return bundles.get(tid)

    topic_bundle_repo.get_by_topic_id.side_effect = get_bundle

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_ctx():
        yield (proc_repo, topic_card_repo, topic_bundle_repo, db)

    return mock_ctx


class TestListTopics:
    """GET /api/v1/topics"""

    async def test_list_topics_empty(self, client):
        ctx = _mock_processing_repos()
        with patch(PATCH_TARGET, ctx):
            resp = await client.get("/api/v1/topics")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["topics"] == []
        assert data["limit"] == 50
        assert data["offset"] == 0

    async def test_list_topics_returns_items(self, client):
        card = _make_topic_card()
        bundle = _make_bundle()
        ctx = _mock_processing_repos(
            topic_cards=[card],
            bundles={card.id: bundle},
        )
        with patch(PATCH_TARGET, ctx):
            resp = await client.get("/api/v1/topics")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        topic = data["topics"][0]
        assert topic["id"] == card.id
        assert topic["title"] == "Test Topic"
        assert topic["type"] == "singleton"
        assert topic["items_count"] == 2
        assert topic["sources"] == ["ch"]

    async def test_list_topics_filter_by_type(self, client):
        card_s = _make_topic_card(topic_id="topic:s", title="Singleton")
        card_c = TopicCard(
            id="topic:c",
            title="Cluster",
            summary="Cluster summary",
            scope_in=["scope in"],
            scope_out=["scope out"],
            type=TopicType.CLUSTER,
            anchors=[
                Anchor(
                    channel_id="ch",
                    message_id="1",
                    message_type=MessageType.POST,
                    anchor_ref="tg:ch:post:1",
                    score=1.0,
                ),
                Anchor(
                    channel_id="ch",
                    message_id="2",
                    message_type=MessageType.POST,
                    anchor_ref="tg:ch:post:2",
                    score=0.9,
                ),
            ],
            sources=["ch"],
            updated_at=NOW,
        )
        ctx = _mock_processing_repos(topic_cards=[card_s, card_c])
        with patch(PATCH_TARGET, ctx):
            resp = await client.get("/api/v1/topics?type=singleton")

        data = resp.json()
        assert data["total"] == 1
        assert data["topics"][0]["title"] == "Singleton"

    async def test_list_topics_pagination(self, client):
        cards = [_make_topic_card(topic_id=f"topic:{i}", title=f"Topic {i}") for i in range(5)]
        ctx = _mock_processing_repos(topic_cards=cards)
        with patch(PATCH_TARGET, ctx):
            resp = await client.get("/api/v1/topics?limit=2&offset=1")

        data = resp.json()
        assert data["total"] == 5
        assert len(data["topics"]) == 2
        assert data["topics"][0]["title"] == "Topic 1"
        assert data["limit"] == 2
        assert data["offset"] == 1


class TestGetTopic:
    """GET /api/v1/topics/{topic_id}"""

    async def test_get_topic_success(self, client):
        card = _make_topic_card()
        ctx = _mock_processing_repos(topic_cards=[card])
        with patch(PATCH_TARGET, ctx):
            resp = await client.get(f"/api/v1/topics/{card.id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == card.id
        assert data["title"] == "Test Topic"
        assert data["scope_in"] == ["scope in"]
        assert data["scope_out"] == ["scope out"]
        assert len(data["anchors"]) == 1
        assert data["anchors"][0]["anchor_ref"] == "tg:ch:post:1"

    async def test_get_topic_not_found(self, client):
        ctx = _mock_processing_repos()
        with patch(PATCH_TARGET, ctx):
            resp = await client.get("/api/v1/topics/nonexistent")

        assert resp.status_code == 404


class TestGetTopicBundle:
    """GET /api/v1/topics/{topic_id}/bundle"""

    async def test_get_bundle_success(self, client):
        bundle = _make_bundle()
        ctx = _mock_processing_repos(bundles={bundle.topic_id: bundle})
        with patch(PATCH_TARGET, ctx):
            resp = await client.get(f"/api/v1/topics/{bundle.topic_id}/bundle")

        assert resp.status_code == 200
        data = resp.json()
        assert data["topic_id"] == bundle.topic_id
        assert data["total_items"] == 2
        assert data["items"][0]["role"] == "anchor"
        assert data["items"][1]["role"] == "supporting"

    async def test_get_bundle_not_found(self, client):
        ctx = _mock_processing_repos()
        with patch(PATCH_TARGET, ctx):
            resp = await client.get("/api/v1/topics/nonexistent/bundle")

        assert resp.status_code == 404
