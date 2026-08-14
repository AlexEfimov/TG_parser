"""
R2 matrix — a foreign identifier given explicitly must not leak content.

Covers ``channel_id`` / ``topic_id`` / ``source_ref`` / ``job_id`` /
``interest_id`` on MCP + bot, plus the HTTP holes named in the session
(``GET /topics?channel_id=``, export status + download). Denial *forms*
are left as they are today: ``"No access"`` / ``"permission"`` / empty /
``PermissionDenied`` / MCP ``unknown`` / HTTP 404. This file does not
replace the point red/green tests for F-02 / F-10 / F-04.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tg_parser.api.auth import resolve_current_user
from tg_parser.api.main import create_app
from tg_parser.auth.models import CurrentUser
from tg_parser.auth.ownership import PermissionDenied
from tg_parser.domain.models import Anchor, MessageType, TopicCard, TopicType
from tg_parser.storage.ports import Job, JobStatus, JobType

OWN = "own_channel"
FOREIGN = "foreign_channel"
FOREIGN_TOPIC = "topic:tg:foreign_channel:post:1"
OWN_TOPIC = "topic:tg:own_channel:post:1"
FOREIGN_REF = "tg:foreign_channel:post:1"
OWN_REF = "tg:own_channel:post:1"
FOREIGN_JOB = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
FOREIGN_INTEREST = "ffffffff-0000-4000-8000-111111111111"
NOW = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)


def _admin() -> CurrentUser:
    return CurrentUser(
        id="admin-1", name="admin", role="admin", allowed_channel_ids=None, max_channels=100
    )


def _user() -> CurrentUser:
    return CurrentUser(
        id="user-1", name="alice", role="user", allowed_channel_ids=[OWN], max_channels=5
    )


def _card(channel_id: str, topic_id: str, title: str) -> TopicCard:
    return TopicCard(
        id=topic_id,
        title=title,
        summary="secret summary",
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


def _processing_repos(card: TopicCard | None = None, doc=None):
    topic_card_repo = AsyncMock()
    topic_card_repo.list_by_channel.return_value = [card] if card else []
    topic_card_repo.list_by_channels.return_value = [card] if card else []
    topic_card_repo.list_all.return_value = [card] if card else []
    topic_card_repo.get_by_id.return_value = card
    topic_bundle_repo = AsyncMock()
    topic_bundle_repo.list_by_channel.return_value = []
    topic_bundle_repo.list_all.return_value = []
    topic_bundle_repo.get_by_topic_id.return_value = None
    proc_repo = AsyncMock()
    proc_repo.get_by_source_ref.return_value = doc

    @asynccontextmanager
    async def fake():
        yield (proc_repo, topic_card_repo, topic_bundle_repo, MagicMock())

    return fake


def _resummarization_repos(card: TopicCard | None):
    card_repo = AsyncMock()
    card_repo.get_by_id.return_value = card
    version_repo = AsyncMock()
    version_repo.list_by_topic.return_value = []
    version_repo.get_two_versions.return_value = {}

    @asynccontextmanager
    async def fake():
        yield (card_repo, AsyncMock(), version_repo, AsyncMock(), MagicMock())

    return fake


# ---------------------------------------------------------------------------
# channel_id
# ---------------------------------------------------------------------------


class TestChannelIdExplicitForeign:
    async def test_mcp_list_topics_empty(self):
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=_user())),
            patch(
                "tg_parser.services.db_context.processing_repos",
                _processing_repos(_card(FOREIGN, FOREIGN_TOPIC, "Foreign topic")),
            ),
            patch(
                "tg_parser.bot.tools._build_no_results_suggestion",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            from tg_parser.mcp_server import list_topics

            result = await list_topics(channel_id=FOREIGN, ctx=None)
        assert result.total == 0
        assert result.items == []

    async def test_bot_list_topics_empty(self):
        with (
            patch(
                "tg_parser.services.db_context.processing_repos",
                _processing_repos(_card(FOREIGN, FOREIGN_TOPIC, "Foreign topic")),
            ),
            patch(
                "tg_parser.bot.tools._build_no_results_suggestion",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            from tg_parser.bot.tools import _exec_list_topics

            result = await _exec_list_topics({"channel_id": FOREIGN}, current_user=_user())
        assert result["total"] == 0
        assert result["items"] == []

    async def test_http_list_topics_empty(self):
        app = create_app()
        app.dependency_overrides[resolve_current_user] = lambda: _user()
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                with patch(
                    "tg_parser.services.db_context.processing_repos",
                    _processing_repos(_card(FOREIGN, FOREIGN_TOPIC, "Foreign topic")),
                ):
                    resp = await client.get(f"/api/v1/topics?channel_id={FOREIGN}")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        assert resp.json()["topics"] == []

    async def test_mcp_search_raises_permission_denied(self):
        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=_user())):
            from tg_parser.mcp_server import search_knowledge_base

            with pytest.raises(PermissionDenied, match="No access to channel"):
                await search_knowledge_base("q", channel_id=FOREIGN, ctx=None)

    async def test_bot_search_raises_permission_denied(self):
        from tg_parser.bot.tools import _exec_search

        with pytest.raises(PermissionDenied, match="No access to channel"):
            await _exec_search({"query": "q", "channel_id": FOREIGN}, current_user=_user())

    async def test_mcp_ask_raises_permission_denied(self):
        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=_user())):
            from tg_parser.mcp_server import ask_question

            with pytest.raises(PermissionDenied, match="No access to channel"):
                await ask_question("q", channel_id=FOREIGN, ctx=None)

    async def test_bot_ask_raises_permission_denied(self):
        from tg_parser.bot.tools import _exec_ask_question

        with pytest.raises(PermissionDenied, match="No access to channel"):
            await _exec_ask_question({"question": "q", "channel_id": FOREIGN}, current_user=_user())

    async def test_mcp_cross_channel_stats_no_foreign_content(self):
        empty = {
            "error": f"Channel not found: {FOREIGN}",
            "total_documents": 0,
            "total_topics": 0,
            "channels": [],
            "keyword_overlaps": [],
            "overlap_count": 0,
        }
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=_user())),
            patch(
                "tg_parser.services.analytics_service.get_cross_channel_analytics",
                AsyncMock(return_value=empty),
            ),
        ):
            from tg_parser.mcp_server import get_cross_channel_stats

            result = await get_cross_channel_stats(channel_id=FOREIGN, ctx=None)
        assert result.error
        assert "Foreign" not in (result.error or "")
        assert not result.channels

    async def test_bot_cross_channel_stats_no_foreign_content(self):
        empty = {"error": f"Channel not found: {FOREIGN}"}
        with (
            patch(
                "tg_parser.services.analytics_service.get_cross_channel_analytics",
                AsyncMock(return_value=empty),
            ),
            patch(
                "tg_parser.bot.tools._build_no_results_suggestion",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            from tg_parser.bot.tools import _exec_get_cross_channel_stats

            result = await _exec_get_cross_channel_stats(
                {"channel_id": FOREIGN}, current_user=_user()
            )
        assert "error" in result
        assert "secret" not in str(result).lower()

    async def test_mcp_pipeline_status_omits_foreign_source(self):
        status = {
            "scheduler_enabled": True,
            "default_interval_seconds": 300,
            "sources": [
                {"source_id": FOREIGN, "channel_id": FOREIGN, "status": "active"},
                {"source_id": OWN, "channel_id": OWN, "status": "active"},
            ],
        }
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=_user())),
            patch(
                "tg_parser.services.scheduler_service.get_scheduler_status",
                AsyncMock(return_value=status),
            ),
        ):
            from tg_parser.mcp_server import get_pipeline_status

            result = await get_pipeline_status(channel_id=FOREIGN, ctx=None)
        assert [s.channel_id for s in result.sources] == []

    async def test_bot_pipeline_status_omits_foreign_source(self):
        status = {
            "scheduler_enabled": True,
            "default_interval_seconds": 300,
            "sources": [
                {"source_id": FOREIGN, "channel_id": FOREIGN, "status": "active"},
                {"source_id": OWN, "channel_id": OWN, "status": "active"},
            ],
        }
        with patch(
            "tg_parser.services.scheduler_service.get_scheduler_status",
            AsyncMock(return_value=status),
        ):
            from tg_parser.bot.tools import _exec_get_pipeline_status

            result = await _exec_get_pipeline_status({"channel_id": FOREIGN}, current_user=_user())
        assert [s["channel_id"] for s in result["sources"]] == []


# ---------------------------------------------------------------------------
# topic_id
# ---------------------------------------------------------------------------


class TestTopicIdExplicitForeign:
    async def test_mcp_get_topic_details_no_access(self):
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=_user())),
            patch(
                "tg_parser.services.db_context.processing_repos",
                _processing_repos(_card(FOREIGN, FOREIGN_TOPIC, "Foreign topic")),
            ),
        ):
            from tg_parser.mcp_server import get_topic_details

            result = await get_topic_details(FOREIGN_TOPIC, ctx=None)
        assert isinstance(result, str)
        assert "No access" in result
        assert "not found" not in result.lower()

    async def test_bot_get_topic_details_no_access(self):
        with patch(
            "tg_parser.services.db_context.processing_repos",
            _processing_repos(_card(FOREIGN, FOREIGN_TOPIC, "Foreign topic")),
        ):
            from tg_parser.bot.tools import _exec_get_topic_details

            result = await _exec_get_topic_details(
                {"topic_id": FOREIGN_TOPIC}, current_user=_user()
            )
        assert "No access" in result["error"]

    async def test_mcp_get_topic_versions_no_access(self):
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=_user())),
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _resummarization_repos(_card(FOREIGN, FOREIGN_TOPIC, "Foreign topic")),
            ),
        ):
            from tg_parser.mcp_server import get_topic_versions

            result = await get_topic_versions(FOREIGN_TOPIC)
        assert "No access" in result["error"]
        assert "versions" not in result

    async def test_bot_get_topic_versions_no_access(self):
        with patch(
            "tg_parser.services.db_context.resummarization_repos",
            _resummarization_repos(_card(FOREIGN, FOREIGN_TOPIC, "Foreign topic")),
        ):
            from tg_parser.bot.tools import _exec_get_topic_versions

            result = await _exec_get_topic_versions(
                {"topic_id": FOREIGN_TOPIC}, current_user=_user()
            )
        assert "No access" in result["error"]

    async def test_mcp_get_topic_history_diff_no_access(self):
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=_user())),
            patch(
                "tg_parser.services.db_context.resummarization_repos",
                _resummarization_repos(_card(FOREIGN, FOREIGN_TOPIC, "Foreign topic")),
            ),
        ):
            from tg_parser.mcp_server import get_topic_history_diff

            result = await get_topic_history_diff(FOREIGN_TOPIC)
        assert "No access" in result["error"]

    async def test_bot_get_topic_history_diff_no_access(self):
        with patch(
            "tg_parser.services.db_context.resummarization_repos",
            _resummarization_repos(_card(FOREIGN, FOREIGN_TOPIC, "Foreign topic")),
        ):
            from tg_parser.bot.tools import _exec_get_topic_history_diff

            result = await _exec_get_topic_history_diff(
                {"topic_id": FOREIGN_TOPIC}, current_user=_user()
            )
        assert "No access" in result["error"]

    async def test_mcp_get_related_topics_passes_allowed(self):
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=_user())),
            patch(
                "tg_parser.services.topic_linking_service.get_related_topics_for",
                AsyncMock(return_value=[]),
            ) as mock_fn,
        ):
            from tg_parser.mcp_server import get_related_topics

            result = await get_related_topics(FOREIGN_TOPIC, ctx=None)
        mock_fn.assert_awaited()
        assert mock_fn.call_args.kwargs["allowed_channel_ids"] == [OWN]
        assert result == []

    async def test_bot_get_related_topics_passes_allowed(self):
        with patch(
            "tg_parser.services.topic_linking_service.get_related_topics_for",
            AsyncMock(return_value=[]),
        ) as mock_fn:
            from tg_parser.bot.tools import _exec_get_related_topics

            result = await _exec_get_related_topics(
                {"topic_id": FOREIGN_TOPIC}, current_user=_user()
            )
        mock_fn.assert_awaited()
        assert mock_fn.call_args.kwargs["allowed_channel_ids"] == [OWN]
        assert result["related_topics"] == []


# ---------------------------------------------------------------------------
# source_ref
# ---------------------------------------------------------------------------


class TestSourceRefExplicitForeign:
    def _doc(self, channel_id: str):
        doc = MagicMock()
        doc.id = "doc-1"
        doc.source_ref = f"tg:{channel_id}:post:1"
        doc.channel_id = channel_id
        doc.text_clean = "secret body"
        doc.summary = "secret summary"
        doc.topics = ["t"]
        return doc

    async def test_mcp_get_document_no_access(self):
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=_user())),
            patch(
                "tg_parser.services.db_context.processing_repos",
                _processing_repos(doc=self._doc(FOREIGN)),
            ),
        ):
            from tg_parser.mcp_server import get_document

            result = await get_document(FOREIGN_REF, ctx=None)
        assert isinstance(result, str)
        assert "No access" in result
        assert "secret" not in result

    async def test_bot_get_document_no_access(self):
        with patch(
            "tg_parser.services.db_context.processing_repos",
            _processing_repos(doc=self._doc(FOREIGN)),
        ):
            from tg_parser.bot.tools import _exec_get_document

            result = await _exec_get_document({"source_ref": FOREIGN_REF}, current_user=_user())
        assert "No access" in result["error"]
        assert "secret" not in str(result)


# ---------------------------------------------------------------------------
# job_id
# ---------------------------------------------------------------------------


class TestJobIdExplicitForeign:
    def _job(self, client: str) -> Job:
        return Job(
            job_id=FOREIGN_JOB,
            job_type=JobType.EXPORT,
            status=JobStatus.COMPLETED,
            created_at=NOW,
            channel_id=FOREIGN,
            client=client,
            export_format="json",
            download_url="/api/v1/export/download/x",
            progress={"level": "raw"},
            result={"file_size": 99, "level": "raw"},
        )

    async def test_mcp_get_export_status_unknown(self):
        store = AsyncMock()
        store.get_job.return_value = self._job("bob")
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=_user())),
            patch(
                "tg_parser.api.job_store.ensure_job_store_initialized",
                AsyncMock(return_value=store),
            ),
        ):
            from tg_parser.mcp_server import get_export_status

            result = await get_export_status(FOREIGN_JOB, ctx=None)
        assert result.status == "unknown"
        assert result.channel_id is None
        assert result.file_size is None

    async def test_http_status_and_download_404(self):
        store = AsyncMock()
        store.get_job.return_value = self._job("bob")
        app = create_app()
        app.dependency_overrides[resolve_current_user] = lambda: _user()
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                with patch(
                    "tg_parser.api.routes.export.ensure_job_store_initialized",
                    AsyncMock(return_value=store),
                ):
                    status = await client.get(f"/api/v1/export/status/{FOREIGN_JOB}")
                    download = await client.get(f"/api/v1/export/download/{FOREIGN_JOB}")
        finally:
            app.dependency_overrides.clear()
        assert status.status_code == 404
        assert download.status_code == 404


# ---------------------------------------------------------------------------
# interest_id
# ---------------------------------------------------------------------------


class TestInterestIdExplicitForeign:
    def _interest(self):
        interest = MagicMock()
        interest.id = FOREIGN_INTEREST
        interest.user_id = "someone-else"
        return interest

    def _service(self, interest):
        svc = AsyncMock()
        svc.get_interest.return_value = interest
        svc.get_matches.return_value = [MagicMock(source_ref="tg:x:post:1")]
        svc.aclose = AsyncMock()
        return svc

    @asynccontextmanager
    async def _watchlist_repos(self):
        yield (AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(), MagicMock())

    async def test_mcp_get_watchlist_matches_count_zero(self):
        interest = self._interest()
        svc = self._service(interest)
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=_user())),
            patch("tg_parser.services.db_context.watchlist_repos", self._watchlist_repos),
            patch(
                "tg_parser.services.watchlist_service.make_watchlist_service",
                return_value=svc,
            ),
        ):
            from tg_parser.mcp_server import get_watchlist_matches

            result = await get_watchlist_matches(FOREIGN_INTEREST, ctx=None)
        assert result.count == 0
        assert result.matches == []
        svc.get_matches.assert_not_awaited()

    async def test_bot_get_watchlist_matches_permission(self):
        interest = self._interest()
        svc = self._service(interest)
        with (
            patch("tg_parser.services.db_context.watchlist_repos", self._watchlist_repos),
            patch(
                "tg_parser.services.watchlist_service.make_watchlist_service",
                return_value=svc,
            ),
        ):
            from tg_parser.bot.tools import _exec_get_watchlist_matches

            result = await _exec_get_watchlist_matches(
                {"interest_id": FOREIGN_INTEREST}, current_user=_user()
            )
        assert "permission" in result["error"]
        svc.get_matches.assert_not_awaited()


# ---------------------------------------------------------------------------
# admin pass + own stays own
# ---------------------------------------------------------------------------


class TestAdminAndOwnRemain:
    async def test_admin_list_topics_explicit_foreign_sees_it(self):
        with patch(
            "tg_parser.services.db_context.processing_repos",
            _processing_repos(_card(FOREIGN, FOREIGN_TOPIC, "Foreign topic")),
        ):
            from tg_parser.bot.tools import _exec_list_topics

            result = await _exec_list_topics({"channel_id": FOREIGN}, current_user=_admin())
        assert result["total"] == 1
        assert result["items"][0]["title"] == "Foreign topic"

    async def test_user_own_topic_details_still_work(self):
        with (
            patch(
                "tg_parser.services.db_context.processing_repos",
                _processing_repos(_card(OWN, OWN_TOPIC, "Own topic")),
            ),
            patch(
                "tg_parser.services.topic_linking_service.get_related_topics_for",
                AsyncMock(return_value=[]),
            ),
        ):
            from tg_parser.bot.tools import _exec_get_topic_details

            result = await _exec_get_topic_details({"topic_id": OWN_TOPIC}, current_user=_user())
        assert "error" not in result
        assert result["title"] == "Own topic"

    async def test_user_own_document_still_works(self):
        doc = MagicMock()
        doc.id = "doc-own"
        doc.source_ref = OWN_REF
        doc.channel_id = OWN
        doc.text_clean = "own body"
        doc.summary = "own summary"
        doc.topics = []
        with patch(
            "tg_parser.services.db_context.processing_repos",
            _processing_repos(doc=doc),
        ):
            from tg_parser.bot.tools import _exec_get_document

            result = await _exec_get_document({"source_ref": OWN_REF}, current_user=_user())
        assert result["source_ref"] == OWN_REF
        assert "error" not in result
