"""
Supplementary tests for F4 Multi-Tenancy Phases 3–4.

Closes coverage gaps found during audit:
- Bot _exec_* scoping propagation and denial
- MCP tool scoping for data-access tools
- API PermissionDenied → 403 handler
- Default admin fallback
- SATopicCardRepo.list_by_channels edge cases
- retrieval_service.search: admin+channel_id, topic channel_id filter
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
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


# =========================================================================
# 1. Bot _exec_* scoping propagation
# =========================================================================


class TestBotSearchScoping:
    @patch("tg_parser.services.retrieval_service.search")
    async def test_exec_search_passes_allowed_channel_ids(self, mock_search):
        mock_search.return_value = []
        from tg_parser.bot.tools import _exec_search

        user = _user(["ch1", "ch2"])
        await _exec_search({"query": "test"}, current_user=user)

        mock_search.assert_awaited_once()
        assert mock_search.call_args.kwargs["allowed_channel_ids"] == ["ch1", "ch2"]

    @patch("tg_parser.services.retrieval_service.answer")
    async def test_exec_ask_passes_allowed_channel_ids(self, mock_answer):
        mock_answer.return_value = MagicMock(
            answer="ans",
            sources=[],
            model=None,
        )
        from tg_parser.bot.tools import _exec_ask_question

        user = _user(["ch1"])
        await _exec_ask_question({"question": "q"}, current_user=user)

        mock_answer.assert_awaited_once()
        assert mock_answer.call_args.kwargs["allowed_channel_ids"] == ["ch1"]


class TestBotListTopicsScoping:
    async def test_exec_list_topics_uses_list_by_channels_for_user(self):
        mock_tc_repo = AsyncMock()
        mock_tc_repo.list_by_channels.return_value = []
        mock_tb_repo = AsyncMock()
        mock_tb_repo.list_all.return_value = []

        @asynccontextmanager
        async def fake_repos():
            yield (AsyncMock(), mock_tc_repo, mock_tb_repo, MagicMock())

        with patch("tg_parser.services.db_context.processing_repos", fake_repos):
            from tg_parser.bot.tools import _exec_list_topics

            result = await _exec_list_topics({}, current_user=_user(["ch1", "ch2"]))

        mock_tc_repo.list_by_channels.assert_awaited_once_with(["ch1", "ch2"])
        assert result["total"] == 0

    async def test_exec_list_topics_uses_list_all_for_admin(self):
        mock_tc_repo = AsyncMock()
        mock_tc_repo.list_all.return_value = []
        mock_tb_repo = AsyncMock()
        mock_tb_repo.list_all.return_value = []

        @asynccontextmanager
        async def fake_repos():
            yield (AsyncMock(), mock_tc_repo, mock_tb_repo, MagicMock())

        with patch("tg_parser.services.db_context.processing_repos", fake_repos):
            from tg_parser.bot.tools import _exec_list_topics

            await _exec_list_topics({}, current_user=_admin())

        mock_tc_repo.list_all.assert_awaited_once()


class TestBotGetTopicDetailsScoping:
    async def test_access_denied_for_non_allowed_topic(self):
        card = MagicMock()
        card.sources = ["ch3"]

        mock_tc_repo = AsyncMock()
        mock_tc_repo.get_by_id.return_value = card

        @asynccontextmanager
        async def fake_repos():
            yield (AsyncMock(), mock_tc_repo, AsyncMock(), MagicMock())

        with patch("tg_parser.services.db_context.processing_repos", fake_repos):
            from tg_parser.bot.tools import _exec_get_topic_details

            result = await _exec_get_topic_details(
                {"topic_id": "t1"},
                current_user=_user(["ch1"]),
            )

        assert "error" in result
        assert "No access" in result["error"]


class TestBotRelatedTopicsScoping:
    @patch("tg_parser.services.topic_linking_service.get_related_topics_for")
    async def test_exec_get_related_topics_passes_channels(self, mock_fn):
        mock_fn.return_value = []
        from tg_parser.bot.tools import _exec_get_related_topics

        user = _user(["ch1"])
        await _exec_get_related_topics({"topic_id": "t1"}, current_user=user)

        mock_fn.assert_awaited_once()
        assert mock_fn.call_args.kwargs["allowed_channel_ids"] == ["ch1"]


class TestBotCrossChannelStatsScoping:
    @patch("tg_parser.services.analytics_service.get_cross_channel_analytics")
    async def test_exec_stats_passes_channels(self, mock_fn):
        mock_fn.return_value = {"channels": [], "keywords": {}}
        from tg_parser.bot.tools import _exec_get_cross_channel_stats

        user = _user(["ch1"])
        await _exec_get_cross_channel_stats({}, current_user=user)

        mock_fn.assert_awaited_once()
        assert mock_fn.call_args.kwargs["allowed_channel_ids"] == ["ch1"]


class TestBotTriggerPipelineDenied:
    async def test_trigger_pipeline_denied_for_non_owner(self):
        from tg_parser.bot.tools import _exec_trigger_pipeline

        user = _user(["ch1"])
        result = await _exec_trigger_pipeline(
            {"channel_id": "ch3", "confirm": True},
            current_user=user,
        )
        assert "error" in result
        assert "No access" in result["error"]


class TestBotPauseResumeDenied:
    async def test_pause_denied_for_non_owner(self):
        from tg_parser.bot.tools import _exec_pause_channel

        result = await _exec_pause_channel(
            {"channel_id": "ch3"},
            current_user=_user(["ch1"]),
        )
        assert "error" in result
        assert "No access" in result["error"]

    async def test_resume_denied_for_non_owner(self):
        from tg_parser.bot.tools import _exec_resume_channel

        result = await _exec_resume_channel(
            {"channel_id": "ch3"},
            current_user=_user(["ch1"]),
        )
        assert "error" in result
        assert "No access" in result["error"]


class TestBotRemoveChannelDenied:
    async def test_remove_channel_denied_for_non_owner(self):
        from tg_parser.bot.tools import _exec_remove_channel

        result = await _exec_remove_channel(
            {"channel_id": "ch3", "confirm": True},
            current_user=_user(["ch1"]),
        )
        assert result["removed"] is False
        assert "No access" in result["message"]


class TestBotGetPipelineStatusScoping:
    @patch("tg_parser.services.scheduler_service.get_scheduler_status")
    async def test_pipeline_status_filtered_by_user_channels(self, mock_status):
        mock_status.return_value = {
            "scheduler_enabled": True,
            "default_interval_seconds": 300,
            "retopicize_threshold": 50,
            "sources": [
                {"source_id": "ch1", "channel_id": "ch1", "status": "active"},
                {"source_id": "ch2", "channel_id": "ch2", "status": "active"},
                {"source_id": "ch3", "channel_id": "ch3", "status": "paused"},
            ],
        }
        from tg_parser.bot.tools import _exec_get_pipeline_status

        result = await _exec_get_pipeline_status({}, current_user=_user(["ch1"]))

        channel_ids = [s["channel_id"] for s in result["sources"]]
        assert channel_ids == ["ch1"]


class TestBotListChannelsScoping:
    @patch("tg_parser.services.channel_service.get_all_channel_stats")
    async def test_exec_list_channels_passes_user_channels(self, mock_stats):
        mock_stats.return_value = [
            {
                "channel_id": "ch1",
                "channel_username": None,
                "status": "active",
                "raw_messages": 5,
                "processed_documents": 3,
                "topics_count": 1,
                "coverage_percent": 60.0,
            },
        ]
        from tg_parser.bot.tools import _exec_list_channels

        user = _user(["ch1"])
        result = await _exec_list_channels({}, current_user=user)

        mock_stats.assert_awaited_once_with(allowed_channel_ids=["ch1"])
        assert result["count"] == 1


# =========================================================================
# 2. Default admin fallback
# =========================================================================


class TestDefaultAdminFallback:
    @patch("tg_parser.services.retrieval_service.search")
    @patch("tg_parser.auth.resolvers.get_default_admin")
    async def test_none_user_falls_back_to_default_admin(self, mock_admin, mock_search):
        admin = _admin()
        mock_admin.return_value = admin
        mock_search.return_value = []

        from tg_parser.bot.tools import _exec_search

        await _exec_search({"query": "test"}, current_user=None)

        mock_admin.assert_awaited_once()
        assert mock_search.call_args.kwargs["allowed_channel_ids"] is None


# =========================================================================
# 3. MCP tool scoping for data-access tools
# =========================================================================


class TestMCPSearchScoping:
    @patch("tg_parser.mcp_server.resolve_mcp_user")
    @patch("tg_parser.services.retrieval_service.search")
    async def test_search_passes_tenant_channels(self, mock_search, mock_resolve):
        mock_resolve.return_value = _user(["ch1"])
        mock_search.return_value = []

        from tg_parser.mcp_server import search_knowledge_base

        await search_knowledge_base("query", ctx=None)

        mock_search.assert_awaited_once()
        assert mock_search.call_args.kwargs["allowed_channel_ids"] == ["ch1"]

    @patch("tg_parser.mcp_server.resolve_mcp_user")
    @patch("tg_parser.services.retrieval_service.answer")
    async def test_ask_passes_tenant_channels(self, mock_answer, mock_resolve):
        mock_resolve.return_value = _user(["ch1"])
        mock_answer.return_value = MagicMock(
            answer="ans",
            sources=[],
            model=None,
        )

        from tg_parser.mcp_server import ask_question

        await ask_question("question", ctx=None)

        mock_answer.assert_awaited_once()
        assert mock_answer.call_args.kwargs["allowed_channel_ids"] == ["ch1"]


class TestMCPGetDocumentScoping:
    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_document_denied_for_non_owner(self, mock_resolve):
        mock_resolve.return_value = _user(["ch1"])

        mock_doc = MagicMock()
        mock_doc.channel_id = "ch2"
        mock_proc_repo = AsyncMock()
        mock_proc_repo.get_by_source_ref.return_value = mock_doc

        @asynccontextmanager
        async def fake_repos():
            yield (mock_proc_repo, AsyncMock(), AsyncMock(), MagicMock())

        with patch("tg_parser.services.db_context.processing_repos", fake_repos):
            from tg_parser.mcp_server import get_document

            result = await get_document("tg:ch2:post:1", ctx=None)

        assert isinstance(result, str)
        assert "No access" in result


class TestMCPGetTopicDetailsScoping:
    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_topic_denied_for_non_owner(self, mock_resolve):
        mock_resolve.return_value = _user(["ch1"])

        card = MagicMock()
        card.sources = ["ch3"]

        mock_tc_repo = AsyncMock()
        mock_tc_repo.get_by_id.return_value = card

        @asynccontextmanager
        async def fake_repos():
            yield (AsyncMock(), mock_tc_repo, AsyncMock(), MagicMock())

        with patch("tg_parser.services.db_context.processing_repos", fake_repos):
            from tg_parser.mcp_server import get_topic_details

            result = await get_topic_details("topic:ch3:post:1", ctx=None)

        assert isinstance(result, str)
        assert "No access" in result


class TestMCPTriggerPipelineDenied:
    @patch("tg_parser.mcp_server.resolve_mcp_user")
    async def test_trigger_denied_for_non_owner(self, mock_resolve):
        mock_resolve.return_value = _user(["ch1"])

        from tg_parser.mcp_server import trigger_pipeline

        result = await trigger_pipeline("ch3", ctx=None)

        assert result.triggered is False
        assert "No access" in result.message


class TestMCPGetPipelineStatusScoping:
    @patch("tg_parser.mcp_server.resolve_mcp_user")
    @patch("tg_parser.services.scheduler_service.get_scheduler_status")
    async def test_pipeline_status_scoped(self, mock_status, mock_resolve):
        mock_resolve.return_value = _user(["ch1"])
        mock_status.return_value = {
            "scheduler_enabled": True,
            "default_interval_seconds": 300,
            "sources": [
                {"source_id": "ch1", "channel_id": "ch1", "status": "active"},
                {"source_id": "ch2", "channel_id": "ch2", "status": "active"},
            ],
        }

        from tg_parser.mcp_server import get_pipeline_status

        result = await get_pipeline_status(ctx=None)

        channel_ids = [s.channel_id for s in result.sources]
        assert channel_ids == ["ch1"]


# =========================================================================
# 4. API PermissionDenied → 403 handler
# =========================================================================


class TestAPIPermissionDeniedHandler:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from tg_parser.api.main import app

        return TestClient(app)

    def test_permission_denied_returns_403(self, client):
        """PermissionDenied raised inside a route → 403 with detail message."""
        from fastapi import APIRouter

        from tg_parser.api.main import app
        from tg_parser.auth.ownership import PermissionDenied as PD

        test_router = APIRouter()

        @test_router.get("/test-403")
        async def raise_permission_denied():
            raise PD("test denial message")

        app.include_router(test_router)
        try:
            response = client.get("/test-403")
            assert response.status_code == 403
            assert response.json()["detail"] == "test denial message"
        finally:
            app.routes[:] = [r for r in app.routes if getattr(r, "path", "") != "/test-403"]


# =========================================================================
# 5. SATopicCardRepo.list_by_channels edge cases
# =========================================================================


class TestTopicCardRepoListByChannels:
    async def test_empty_channel_ids_returns_empty(self):
        from tg_parser.storage.sqlalchemy.topic_card_repo import SATopicCardRepo

        mock_session = AsyncMock()
        repo = SATopicCardRepo(mock_session)
        result = await repo.list_by_channels([])

        assert result == []
        mock_session.execute.assert_not_awaited()

    async def test_multiple_channels_generates_or_sql(self):
        from tg_parser.storage.sqlalchemy.topic_card_repo import SATopicCardRepo

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        repo = SATopicCardRepo(mock_session)
        await repo.list_by_channels(["ch1", "ch2", "ch3"])

        call_args = mock_session.execute.call_args
        sql_text = call_args.args[0].text
        assert sql_text.count("sources_json LIKE") == 3
        assert " OR " in sql_text

        params = (
            call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("params", {})
        )
        assert params["p0"] == '%"ch1"%'
        assert params["p1"] == '%"ch2"%'
        assert params["p2"] == '%"ch3"%'


# =========================================================================
# 6. retrieval_service.search edge cases
# =========================================================================


class TestSearchEdgeCases:
    async def test_admin_with_channel_id_narrows_to_one_channel(self):
        """allowed_channel_ids=None + channel_id='ch1' → channel_ids=['ch1']."""
        mock_emb_repo = AsyncMock()
        mock_emb_repo.similarity_search.return_value = []
        mock_proc_repo = AsyncMock()

        from tg_parser.services.retrieval_service import search

        with patch("tg_parser.services.retrieval_service.create_embedding_client") as mock_client:
            inst = AsyncMock()
            inst.embed.return_value = [[0.1] * 1536]
            mock_client.return_value = inst

            await search(
                query="test",
                channel_id="ch1",
                allowed_channel_ids=None,
                emb_repo=mock_emb_repo,
                proc_repo=mock_proc_repo,
                include_topics=False,
            )

        call_kwargs = mock_emb_repo.similarity_search.call_args.kwargs
        assert call_kwargs["channel_ids"] == ["ch1"]

    async def test_topic_filtered_by_channel_id(self):
        """Topic whose sources don't include channel_id is filtered out."""
        from tg_parser.domain.models import Anchor, MessageType, TopicCard, TopicType
        from tg_parser.services.retrieval_service import search
        from tg_parser.storage.ports import SimilarityResult

        anchor = Anchor(
            channel_id="other",
            message_id="1",
            message_type=MessageType.POST,
            anchor_ref="tg:other:post:1",
        )
        card = TopicCard(
            id="t1",
            title="Topic",
            summary="s",
            scope_in=["in"],
            scope_out=["out"],
            type=TopicType.SINGLETON,
            anchors=[anchor],
            sources=["other_channel"],
            updated_at=datetime.now(UTC),
        )

        sim = SimilarityResult(
            source_ref="topic:t1",
            score=0.9,
            entry_type="topic",
            topic_id="t1",
        )
        mock_emb_repo = AsyncMock()
        mock_emb_repo.similarity_search.return_value = [sim]

        mock_tc_repo = AsyncMock()
        mock_tc_repo.get_by_id.return_value = card

        mock_proc_repo = AsyncMock()
        mock_proc_repo.get_by_source_refs.return_value = {}

        with patch("tg_parser.services.retrieval_service.create_embedding_client") as mock_client:
            inst = AsyncMock()
            inst.embed.return_value = [[0.1] * 1536]
            mock_client.return_value = inst

            results = await search(
                query="test",
                channel_id="my_channel",
                allowed_channel_ids=None,
                emb_repo=mock_emb_repo,
                proc_repo=mock_proc_repo,
                topic_card_repo=mock_tc_repo,
            )

        assert len(results) == 0


# =========================================================================
# 7. Bot _exec_get_document: admin access allowed
# =========================================================================


class TestBotGetDocumentAdminAllowed:
    async def test_admin_can_access_any_document(self):
        mock_doc = MagicMock()
        mock_doc.channel_id = "ch99"
        mock_doc.id = "doc1"
        mock_doc.source_ref = "tg:ch99:post:1"
        mock_doc.text_clean = "text"
        mock_doc.summary = "summary"
        mock_doc.topics = ["t1"]

        mock_proc_repo = AsyncMock()
        mock_proc_repo.get_by_source_ref.return_value = mock_doc

        @asynccontextmanager
        async def fake_repos():
            yield (mock_proc_repo, MagicMock(), MagicMock(), MagicMock())

        with patch("tg_parser.services.db_context.processing_repos", fake_repos):
            from tg_parser.bot.tools import _exec_get_document

            result = await _exec_get_document(
                {"source_ref": "tg:ch99:post:1"},
                current_user=_admin(),
            )

        assert "error" not in result
        assert result["channel_id"] == "ch99"


# =========================================================================
# 8. PermissionDenied exception attributes
# =========================================================================


class TestPermissionDeniedException:
    def test_default_message(self):
        exc = PermissionDenied()
        assert exc.message == "Permission denied"
        assert str(exc) == "Permission denied"

    def test_custom_message(self):
        exc = PermissionDenied("Custom reason")
        assert exc.message == "Custom reason"
        assert str(exc) == "Custom reason"

    def test_is_exception(self):
        assert issubclass(PermissionDenied, Exception)
        with pytest.raises(PermissionDenied):
            raise PermissionDenied("test")
