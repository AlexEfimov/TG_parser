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
