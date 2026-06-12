"""
Tests for F4 Multi-Tenancy Phase 4: Scoped Data Access.

Unit tests (mock DB) for service-level and tool-level scoping.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tg_parser.auth.models import CurrentUser
from tg_parser.auth.ownership import PermissionDenied


def _admin() -> CurrentUser:
    return CurrentUser(
        id="admin-1",
        name="admin",
        role="admin",
        allowed_channel_ids=None,
        max_channels=100,
    )


def _user(channels: list[str]) -> CurrentUser:
    return CurrentUser(
        id="user-1",
        name="alice",
        role="user",
        allowed_channel_ids=channels,
        max_channels=5,
    )


# ---------------------------------------------------------------------------
# retrieval_service.search scoping
# ---------------------------------------------------------------------------


class TestSearchScoping:
    async def test_empty_allowed_returns_empty(self):
        from tg_parser.services.retrieval_service import search

        results = await search(query="test", allowed_channel_ids=[])
        assert results == []

    async def test_channel_id_not_in_allowed_raises(self):
        from tg_parser.services.retrieval_service import search

        with pytest.raises(PermissionDenied, match="No access to channel ch3"):
            await search(query="test", channel_id="ch3", allowed_channel_ids=["ch1", "ch2"])

    async def test_channel_id_in_allowed_passes(self):
        """channel_id + allowed intersection should not raise."""
        mock_emb_repo = AsyncMock()
        mock_emb_repo.similarity_search.return_value = []
        mock_emb_repo.keyword_search.return_value = []
        mock_proc_repo = AsyncMock()
        mock_proc_repo.get_by_source_refs.return_value = {}

        from tg_parser.services.retrieval_service import search

        with patch("tg_parser.services.retrieval_service.create_embedding_client") as mock_client:
            client_inst = AsyncMock()
            client_inst.embed.return_value = [[0.1] * 1536]
            mock_client.return_value = client_inst

            results = await search(
                query="test",
                channel_id="ch1",
                allowed_channel_ids=["ch1", "ch2"],
                emb_repo=mock_emb_repo,
                proc_repo=mock_proc_repo,
                include_topics=False,
            )
        assert results == []
        mock_emb_repo.similarity_search.assert_called_once()
        call_kwargs = mock_emb_repo.similarity_search.call_args
        assert call_kwargs.kwargs.get("channel_ids") == ["ch1"]

    async def test_admin_no_filter(self):
        mock_emb_repo = AsyncMock()
        mock_emb_repo.similarity_search.return_value = []
        mock_emb_repo.keyword_search.return_value = []
        mock_proc_repo = AsyncMock()

        from tg_parser.services.retrieval_service import search

        with patch("tg_parser.services.retrieval_service.create_embedding_client") as mock_client:
            client_inst = AsyncMock()
            client_inst.embed.return_value = [[0.1] * 1536]
            mock_client.return_value = client_inst

            await search(
                query="test",
                allowed_channel_ids=None,
                emb_repo=mock_emb_repo,
                proc_repo=mock_proc_repo,
                include_topics=False,
            )
        call_kwargs = mock_emb_repo.similarity_search.call_args
        assert call_kwargs.kwargs.get("channel_ids") is None


# ---------------------------------------------------------------------------
# retrieval_service.answer scoping
# ---------------------------------------------------------------------------


class TestAnswerScoping:
    @patch("tg_parser.services.retrieval_service.search")
    async def test_answer_passes_allowed_channel_ids(self, mock_search):
        mock_search.return_value = []

        from tg_parser.services.retrieval_service import answer

        await answer(
            question="test question",
            allowed_channel_ids=["ch1"],
        )
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args
        assert call_kwargs.kwargs.get("allowed_channel_ids") == ["ch1"]


# ---------------------------------------------------------------------------
# analytics_service scoping
# ---------------------------------------------------------------------------


class TestAnalyticsScoping:
    @patch("tg_parser.services.analytics_service.stats_repos")
    async def test_non_admin_filters_sources(self, mock_repos):
        from contextlib import asynccontextmanager

        from tg_parser.services.analytics_service import get_cross_channel_analytics

        mock_source = MagicMock()
        mock_source.channel_id = "ch1"
        mock_source2 = MagicMock()
        mock_source2.channel_id = "ch2"

        mock_state_repo = AsyncMock()
        mock_state_repo.list_sources.return_value = [mock_source, mock_source2]

        mock_proc_repo = AsyncMock()
        mock_proc_repo.count_by_channel.return_value = 0
        mock_proc_repo.list_source_refs_by_channel.return_value = []

        mock_tc_repo = AsyncMock()
        mock_tc_repo.list_all.return_value = []

        mock_tb_repo = AsyncMock()
        mock_tb_repo.list_all.return_value = []

        mock_emb_repo = AsyncMock()

        mock_link_repo = AsyncMock()
        mock_link_repo.list_all.return_value = []

        @asynccontextmanager
        async def fake_repos():
            yield (
                mock_state_repo,
                AsyncMock(),
                mock_proc_repo,
                mock_tc_repo,
                mock_tb_repo,
                mock_emb_repo,
                mock_link_repo,
                MagicMock(),
            )

        mock_repos.return_value = fake_repos()

        result = await get_cross_channel_analytics(allowed_channel_ids=["ch1"])
        assert "channels" in result
        channel_ids = [c["channel_id"] for c in result["channels"]]
        assert "ch1" in channel_ids
        assert "ch2" not in channel_ids


# ---------------------------------------------------------------------------
# channel_service scoping
# ---------------------------------------------------------------------------


class TestChannelServiceScoping:
    @patch("tg_parser.services.channel_service.stats_repos")
    async def test_get_all_channel_stats_filters(self, mock_repos):
        from contextlib import asynccontextmanager

        from tg_parser.services.channel_service import get_all_channel_stats

        src1 = MagicMock()
        src1.channel_id = "ch1"
        src1.channel_username = None
        src1.status = "active"
        src2 = MagicMock()
        src2.channel_id = "ch2"

        mock_state_repo = AsyncMock()
        mock_state_repo.list_sources.return_value = [src1, src2]

        mock_raw_repo = AsyncMock()
        mock_raw_repo.count_by_channel.return_value = 5

        mock_proc_repo = AsyncMock()
        mock_proc_repo.count_by_channel.return_value = 3
        mock_proc_repo.list_source_refs_by_channel.return_value = []

        mock_tc_repo = AsyncMock()
        mock_tc_repo.list_by_channel.return_value = []

        mock_tb_repo = AsyncMock()
        mock_tb_repo.list_by_channel.return_value = []

        mock_emb_repo = AsyncMock()
        mock_emb_repo.list_missing.return_value = []

        mock_link_repo = AsyncMock()
        mock_link_repo.list_all.return_value = []

        @asynccontextmanager
        async def fake_repos():
            yield (
                mock_state_repo,
                mock_raw_repo,
                mock_proc_repo,
                mock_tc_repo,
                mock_tb_repo,
                mock_emb_repo,
                mock_link_repo,
                MagicMock(),
            )

        mock_repos.return_value = fake_repos()

        result = await get_all_channel_stats(allowed_channel_ids=["ch1"])
        assert len(result) == 1
        assert result[0]["channel_id"] == "ch1"


# ---------------------------------------------------------------------------
# topic_linking_service scoping
# ---------------------------------------------------------------------------


class TestTopicLinkingScoping:
    @patch("tg_parser.services.topic_linking_service.topic_linking_repos")
    async def test_get_related_topics_filters_by_channels(self, mock_repos):
        from contextlib import asynccontextmanager
        from datetime import UTC, datetime

        from tg_parser.domain.models import Anchor, MessageType, TopicCard, TopicLink, TopicType
        from tg_parser.services.topic_linking_service import get_related_topics_for

        link = TopicLink(
            topic_id_a="t1",
            topic_id_b="t2",
            similarity_score=0.8,
            shared_keywords=["kw"],
            created_at=datetime.now(UTC),
        )

        anchor_ch1 = Anchor(
            channel_id="ch1",
            message_id="1",
            message_type=MessageType.POST,
            anchor_ref="tg:ch1:post:1",
        )
        card_ch1 = TopicCard(
            id="t2",
            title="Topic 2",
            summary="sum",
            scope_in=["in"],
            scope_out=["out"],
            type=TopicType.SINGLETON,
            anchors=[anchor_ch1],
            sources=["ch1"],
            updated_at=datetime.now(UTC),
        )
        anchor_ch3 = Anchor(
            channel_id="ch3",
            message_id="1",
            message_type=MessageType.POST,
            anchor_ref="tg:ch3:post:1",
        )
        card_ch3 = TopicCard(
            id="t3",
            title="Topic 3",
            summary="sum",
            scope_in=["in"],
            scope_out=["out"],
            type=TopicType.SINGLETON,
            anchors=[anchor_ch3],
            sources=["ch3"],
            updated_at=datetime.now(UTC),
        )

        mock_tc_repo = AsyncMock()
        mock_tc_repo.get_by_id.side_effect = lambda tid: {"t2": card_ch1, "t3": card_ch3}.get(tid)

        mock_link_repo = AsyncMock()
        mock_link_repo.get_by_topic_id.return_value = [
            link,
            TopicLink(
                topic_id_a="t1",
                topic_id_b="t3",
                similarity_score=0.7,
                shared_keywords=["kw2"],
                created_at=datetime.now(UTC),
            ),
        ]

        @asynccontextmanager
        async def fake_repos():
            yield (mock_tc_repo, AsyncMock(), mock_link_repo, AsyncMock(), MagicMock())

        mock_repos.return_value = fake_repos()

        related = await get_related_topics_for("t1", allowed_channel_ids=["ch1"])
        assert len(related) == 1
        assert related[0]["channel_id"] == "ch1"


# ---------------------------------------------------------------------------
# Bot tool scoping: _exec_get_document
# ---------------------------------------------------------------------------


class TestBotGetDocumentScoping:
    async def test_document_access_denied(self):
        user = _user(["ch1"])

        mock_doc = MagicMock()
        mock_doc.channel_id = "ch2"

        mock_proc_repo = AsyncMock()
        mock_proc_repo.get_by_source_ref.return_value = mock_doc

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake_repos():
            yield (mock_proc_repo, MagicMock(), MagicMock(), MagicMock())

        with patch("tg_parser.services.db_context.processing_repos", fake_repos):
            from tg_parser.bot.tools import _exec_get_document

            result = await _exec_get_document(
                {"source_ref": "tg:ch2:post:1"},
                current_user=user,
            )

        assert "error" in result
        assert "No access" in result["error"]


# ---------------------------------------------------------------------------
# Bot tool scoping: admin-only tools
# ---------------------------------------------------------------------------


class TestBotAdminOnlyTools:
    async def test_set_llm_config_rejected(self):
        from tg_parser.bot.tools import _exec_set_llm_config

        result = await _exec_set_llm_config(
            {"scope": "global", "provider": "openai", "confirm": True},
            current_user=_user(["ch1"]),
        )
        assert "error" in result
        assert "Admin" in result["error"]

    async def test_reset_llm_config_rejected(self):
        from tg_parser.bot.tools import _exec_reset_llm_config

        result = await _exec_reset_llm_config(
            {"confirm": True},
            current_user=_user(["ch1"]),
        )
        assert "error" in result
        assert "Admin" in result["error"]

    async def test_reload_prompts_rejected(self):
        from tg_parser.bot.tools import _exec_reload_prompts

        result = await _exec_reload_prompts(
            {},
            current_user=_user(["ch1"]),
        )
        assert "error" in result
        assert "Admin" in result["error"]


# ---------------------------------------------------------------------------
# API admin-only enforcement (agents)
# ---------------------------------------------------------------------------


class TestAPIAdminOnly:
    @pytest.fixture
    def admin_user(self):
        return _admin()

    @pytest.fixture
    def regular_user(self):
        return _user(["ch1"])

    async def test_agents_list_admin_ok(self, admin_user):
        """Admin should not raise on assert_admin."""
        from tg_parser.auth.ownership import assert_admin

        assert_admin(admin_user)

    async def test_agents_list_user_rejected(self, regular_user):
        from tg_parser.auth.ownership import assert_admin

        with pytest.raises(PermissionDenied):
            assert_admin(regular_user)

    async def test_llm_config_set_user_rejected(self, regular_user):
        from tg_parser.auth.ownership import assert_admin

        with pytest.raises(PermissionDenied, match="Admin"):
            assert_admin(regular_user)
