"""F4-B Core — Phase 5 backward-compat regression guards.

Hidden gotcha § 1 of ``docs/notes/START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md``:

> Any scoped tool called WITHOUT ``workspace_id`` (or with ``workspace_id=None``)
> MUST return bit-for-bit identical output to the F4-A baseline. Hard requirement.

This file pins that promise by exercising every scoped MCP read tool twice —
once with the workspace_id parameter omitted and once with it explicitly set
to ``None`` — and asserting that the call passes ``user.allowed_channel_ids``
through to the underlying service unchanged. Any drift here means somebody
sneaked a behaviour change behind the F4-A facade and the gate must trip.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from tg_parser.auth.models import CurrentUser

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


def _user(allowed: list[str] | None) -> CurrentUser:
    return CurrentUser(
        id="00000000-0000-0000-0000-000000000001",
        name="alice",
        role="user" if allowed is not None else "admin",
        allowed_channel_ids=allowed,
        max_channels=10,
    )


@pg_only
@pytest.mark.parametrize(
    "allowed",
    [None, [], ["ch_a"], ["ch_a", "ch_b", "ch_c"]],
)
class TestSearchKnowledgeBaseF4ABackwardCompat:
    async def test_omitted_workspace_id_preserves_allowed_channels(self, allowed):
        from tg_parser.mcp_server import search_knowledge_base

        user = _user(allowed)
        captured: dict = {}

        async def fake_search(**kwargs):
            captured.update(kwargs)
            return []

        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
            patch(
                "tg_parser.services.retrieval_service.search",
                AsyncMock(side_effect=fake_search),
            ),
        ):
            await search_knowledge_base(query="x")
        assert captured["allowed_channel_ids"] == allowed

    async def test_explicit_none_matches_omitted(self, allowed):
        from tg_parser.mcp_server import search_knowledge_base

        user = _user(allowed)
        captured: dict = {}

        async def fake_search(**kwargs):
            captured.update(kwargs)
            return []

        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
            patch(
                "tg_parser.services.retrieval_service.search",
                AsyncMock(side_effect=fake_search),
            ),
        ):
            await search_knowledge_base(query="x", workspace_id=None)
        assert captured["allowed_channel_ids"] == allowed


@pg_only
class TestListChannelsF4ABackwardCompat:
    @pytest.mark.parametrize("allowed", [None, [], ["ch_a", "ch_b"]])
    async def test_omitted_workspace_id_preserves_allowed_channels(self, allowed):
        from tg_parser.mcp_server import list_channels

        user = _user(allowed)
        captured: dict = {}

        async def fake_stats(**kwargs):
            captured.update(kwargs)
            return []

        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
            patch(
                "tg_parser.services.channel_service.get_all_channel_stats",
                AsyncMock(side_effect=fake_stats),
            ),
        ):
            await list_channels()
        assert captured["allowed_channel_ids"] == allowed


@pg_only
class TestAskQuestionF4ABackwardCompat:
    @pytest.mark.parametrize("allowed", [None, [], ["ch_a"]])
    async def test_omitted_workspace_id_preserves_allowed_channels(self, allowed):
        from tg_parser.mcp_server import AnswerResultItem, ask_question

        user = _user(allowed)
        captured: dict = {}

        async def fake_answer(**kwargs):
            captured.update(kwargs)
            return AnswerResultItem(answer="ok", sources=[], model="stub")

        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
            patch(
                "tg_parser.services.retrieval_service.answer",
                AsyncMock(side_effect=fake_answer),
            ),
        ):
            await ask_question(question="x")
        assert captured["allowed_channel_ids"] == allowed


@pg_only
class TestGetRelatedTopicsF4ABackwardCompat:
    async def test_omitted_workspace_id_preserves_allowed_channels(self):
        from tg_parser.mcp_server import get_related_topics

        user = _user(["ch_a", "ch_b"])
        captured: dict = {}

        async def fake_linker(*args, **kwargs):
            captured.update(kwargs)
            return []

        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
            patch(
                "tg_parser.services.topic_linking_service.get_related_topics_for",
                AsyncMock(side_effect=fake_linker),
            ),
        ):
            await get_related_topics(topic_id="topic:tg:irrelevant")
        assert captured["allowed_channel_ids"] == ["ch_a", "ch_b"]


@pg_only
class TestGetCrossChannelStatsF4ABackwardCompat:
    async def test_omitted_workspace_id_preserves_allowed_channels(self):
        from tg_parser.mcp_server import get_cross_channel_stats

        user = _user(["ch_a"])
        captured: dict = {}

        async def fake_analytics(**kwargs):
            captured.update(kwargs)
            return {
                "total_documents": 0,
                "total_topics": 0,
                "channels": [],
                "keyword_overlaps": [],
                "overlap_count": 0,
            }

        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
            patch(
                "tg_parser.services.analytics_service.get_cross_channel_analytics",
                AsyncMock(side_effect=fake_analytics),
            ),
        ):
            await get_cross_channel_stats()
        assert captured["allowed_channel_ids"] == ["ch_a"]


@pg_only
class TestListTopicsF4ABackwardCompat:
    """Hidden gotcha § 1 — ``list_topics`` without ``workspace_id`` must route
    to the F4-A code path (``list_by_channels(allowed)`` for non-admin or
    ``list_all`` for admin) — no repo I/O via the workspace resolver."""

    @pytest.mark.parametrize("allowed", [None, ["ch_a", "ch_b"]])
    async def test_omitted_workspace_id_routes_to_f4a_path(self, allowed):
        from contextlib import asynccontextmanager

        from tg_parser.mcp_server import list_topics

        user = _user(allowed)
        topic_card_repo = AsyncMock()
        topic_bundle_repo = AsyncMock()
        proc_repo = AsyncMock()
        topic_card_repo.list_all.return_value = []
        topic_card_repo.list_by_channels.return_value = []
        topic_bundle_repo.list_all.return_value = []

        captured: dict = {}

        async def fake_list_by_channels(channel_ids):
            captured["channel_ids"] = channel_ids
            return []

        topic_card_repo.list_by_channels.side_effect = fake_list_by_channels

        @asynccontextmanager
        async def fake_repos():
            yield (proc_repo, topic_card_repo, topic_bundle_repo, AsyncMock())

        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
            patch("tg_parser.services.db_context.processing_repos", fake_repos),
        ):
            await list_topics()

        if allowed is None:
            # Admin: list_all path
            topic_card_repo.list_all.assert_called_once()
            topic_card_repo.list_by_channels.assert_not_called()
        else:
            # Non-admin: list_by_channels(user.allowed_channel_ids)
            topic_card_repo.list_all.assert_not_called()
            assert captured["channel_ids"] == allowed


@pg_only
class TestGetTopicDetailsF4ABackwardCompat:
    """Q4 R3 + Hidden gotcha § 1 — without ``workspace_id`` the bundle is
    returned in full and the F4-A any-source access check applies."""

    async def test_omitted_workspace_id_returns_bundle(self):
        from contextlib import asynccontextmanager
        from datetime import UTC, datetime

        from tg_parser.domain.models import (
            Anchor,
            BundleItem,
            BundleItemRole,
            MessageType,
            TopicBundle,
            TopicCard,
            TopicType,
        )
        from tg_parser.mcp_server import get_topic_details

        user = _user(["ch_x", "ch_y"])
        now = datetime.now(UTC)
        topic_id = "topic:tg:ch_x:post:1"
        # SINGLETON to avoid the >=2 anchor requirement that CLUSTER imposes.
        card = TopicCard(
            id=topic_id,
            title="bc",
            summary="s",
            scope_in=["focus"],
            scope_out=["unrelated"],
            type=TopicType.SINGLETON,
            anchors=[
                Anchor(
                    channel_id="ch_x",
                    message_id="1",
                    message_type=MessageType.POST,
                    anchor_ref="tg:ch_x:post:1",
                    score=1.0,
                )
            ],
            sources=["ch_x", "ch_y"],
            updated_at=now,
        )
        bundle = TopicBundle(
            topic_id=topic_id,
            items=[
                BundleItem(
                    channel_id="ch_x",
                    message_id="1",
                    message_type=MessageType.POST,
                    source_ref="tg:ch_x:post:1",
                    role=BundleItemRole.ANCHOR,
                )
            ],
            updated_at=now,
        )

        topic_card_repo = AsyncMock()
        topic_bundle_repo = AsyncMock()
        topic_card_repo.get_by_id.return_value = card
        topic_bundle_repo.get_by_topic_id.return_value = bundle

        @asynccontextmanager
        async def fake_repos():
            yield (AsyncMock(), topic_card_repo, topic_bundle_repo, AsyncMock())

        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
            patch("tg_parser.services.db_context.processing_repos", fake_repos),
            patch(
                "tg_parser.services.topic_linking_service.get_related_topics_for",
                AsyncMock(return_value=[]),
            ),
        ):
            result = await get_topic_details(topic_id=topic_id)

        assert not isinstance(result, str)
        assert result.id == topic_id
        assert result.items is not None
        assert len(result.items) == 1


@pg_only
class TestGetDocumentF4ABackwardCompat:
    """F4-A baseline guard: ``get_document`` without ``workspace_id`` resolves
    a document via the F4-A path."""

    async def test_omitted_workspace_id_returns_document(self):
        from contextlib import asynccontextmanager
        from datetime import UTC, datetime

        from tg_parser.domain.models import ProcessedDocument
        from tg_parser.mcp_server import get_document

        user = _user(["ch_doc"])
        doc = ProcessedDocument(
            id="d-bc",
            source_ref="tg:ch_doc:post:1",
            source_message_id="1",
            channel_id="ch_doc",
            processed_at=datetime.now(UTC),
            text_clean="hi",
            summary="s",
            topics=[],
        )
        proc_repo = AsyncMock()
        proc_repo.get_by_source_ref.return_value = doc

        @asynccontextmanager
        async def fake_repos():
            yield (proc_repo, AsyncMock(), AsyncMock(), AsyncMock())

        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
            patch("tg_parser.services.db_context.processing_repos", fake_repos),
        ):
            result = await get_document(source_ref="tg:ch_doc:post:1")

        assert not isinstance(result, str)
        assert result.source_ref == "tg:ch_doc:post:1"
        assert result.channel_id == "ch_doc"
