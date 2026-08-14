"""
BUG-100 / F-02 — ``list_topics`` with an explicit foreign ``channel_id``.

The no-``channel_id`` branch already filters by ``allowed_channel_ids``
(``test_exec_list_topics_uses_list_by_channels_for_user``). The explicit-id
branch did not: a non-admin who owns ``own_channel`` and asks for
``foreign_channel`` received that channel's titles. MCP already returns
empty; this file pins the same contract on bot and HTTP.

Red without the guard: bot ``total >= 1`` with title ``Foreign topic``,
HTTP ``GET /topics?channel_id=`` the same. Admin and own-channel paths
must keep working.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tg_parser.api.auth import resolve_current_user
from tg_parser.api.main import create_app
from tg_parser.auth.models import CurrentUser
from tg_parser.domain.models import Anchor, MessageType, TopicCard, TopicType

OWN = "own_channel"
FOREIGN = "foreign_channel"
NOW = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)


def _admin() -> CurrentUser:
    return CurrentUser(
        id="admin-1", name="admin", role="admin", allowed_channel_ids=None, max_channels=100
    )


def _user(channels: list[str] | None = None) -> CurrentUser:
    return CurrentUser(
        id="user-1",
        name="alice",
        role="user",
        allowed_channel_ids=channels if channels is not None else [OWN],
        max_channels=5,
    )


def _card(channel_id: str, title: str) -> TopicCard:
    return TopicCard(
        id=f"topic:tg:{channel_id}:post:1",
        title=title,
        summary="s",
        scope_in=["in"],
        scope_out=["out"],
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
    )


def _repos(cards: list[TopicCard]):
    topic_card_repo = AsyncMock()
    topic_card_repo.list_by_channel.return_value = cards
    topic_card_repo.list_by_channels.return_value = cards
    topic_card_repo.list_all.return_value = cards
    topic_bundle_repo = AsyncMock()
    topic_bundle_repo.list_by_channel.return_value = []
    topic_bundle_repo.list_all.return_value = []
    topic_bundle_repo.get_by_topic_id.return_value = None

    @asynccontextmanager
    async def fake_repos():
        yield (AsyncMock(), topic_card_repo, topic_bundle_repo, MagicMock())

    return fake_repos, topic_card_repo


# ---------------------------------------------------------------------------
# Bot _exec_list_topics
# ---------------------------------------------------------------------------


class TestBotListTopicsExplicitChannelId:
    async def test_foreign_channel_id_returns_empty_without_listing(self):
        foreign = _card(FOREIGN, "Foreign topic")
        fake_repos, topic_card_repo = _repos([foreign])

        with (
            patch("tg_parser.services.db_context.processing_repos", fake_repos),
            patch(
                "tg_parser.bot.tools._build_no_results_suggestion",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            from tg_parser.bot.tools import _exec_list_topics

            result = await _exec_list_topics(
                {"channel_id": FOREIGN},
                current_user=_user([OWN]),
            )

        topic_card_repo.list_by_channel.assert_not_awaited()
        assert result["total"] == 0
        assert result["items"] == []
        titles = [item["title"] for item in result["items"]]
        assert "Foreign topic" not in titles

    async def test_own_channel_id_still_lists(self):
        own = _card(OWN, "Own topic")
        fake_repos, topic_card_repo = _repos([own])

        with patch("tg_parser.services.db_context.processing_repos", fake_repos):
            from tg_parser.bot.tools import _exec_list_topics

            result = await _exec_list_topics(
                {"channel_id": OWN},
                current_user=_user([OWN]),
            )

        topic_card_repo.list_by_channel.assert_awaited_once_with(OWN)
        assert result["total"] == 1
        assert result["items"][0]["title"] == "Own topic"

    async def test_admin_explicit_channel_id_still_lists(self):
        foreign = _card(FOREIGN, "Foreign topic")
        fake_repos, topic_card_repo = _repos([foreign])

        with patch("tg_parser.services.db_context.processing_repos", fake_repos):
            from tg_parser.bot.tools import _exec_list_topics

            result = await _exec_list_topics(
                {"channel_id": FOREIGN},
                current_user=_admin(),
            )

        topic_card_repo.list_by_channel.assert_awaited_once_with(FOREIGN)
        assert result["total"] == 1
        assert result["items"][0]["title"] == "Foreign topic"


# ---------------------------------------------------------------------------
# HTTP GET /api/v1/topics?channel_id=
# ---------------------------------------------------------------------------


class TestHttpListTopicsExplicitChannelId:
    @pytest.fixture
    def app(self):
        return create_app()

    async def _get(self, app, user: CurrentUser, channel_id: str, cards: list[TopicCard]):
        fake_repos, topic_card_repo = _repos(cards)
        app.dependency_overrides[resolve_current_user] = lambda: user
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                with patch("tg_parser.services.db_context.processing_repos", fake_repos):
                    resp = await client.get(f"/api/v1/topics?channel_id={channel_id}")
        finally:
            app.dependency_overrides.clear()
        return resp, topic_card_repo

    async def test_foreign_channel_id_returns_empty_page(self, app):
        resp, topic_card_repo = await self._get(
            app, _user([OWN]), FOREIGN, [_card(FOREIGN, "Foreign topic")]
        )

        assert resp.status_code == 200
        data = resp.json()
        topic_card_repo.list_by_channel.assert_not_awaited()
        assert data["total"] == 0
        assert data["topics"] == []
        assert "Foreign topic" not in [t["title"] for t in data["topics"]]

    async def test_own_channel_id_still_lists(self, app):
        resp, topic_card_repo = await self._get(app, _user([OWN]), OWN, [_card(OWN, "Own topic")])

        assert resp.status_code == 200
        data = resp.json()
        topic_card_repo.list_by_channel.assert_awaited_once_with(OWN)
        assert data["total"] == 1
        assert data["topics"][0]["title"] == "Own topic"

    async def test_admin_explicit_channel_id_still_lists(self, app):
        resp, topic_card_repo = await self._get(
            app, _admin(), FOREIGN, [_card(FOREIGN, "Foreign topic")]
        )

        assert resp.status_code == 200
        data = resp.json()
        topic_card_repo.list_by_channel.assert_awaited_once_with(FOREIGN)
        assert data["total"] == 1
        assert data["topics"][0]["title"] == "Foreign topic"
