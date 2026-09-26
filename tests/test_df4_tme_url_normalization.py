"""DF-4 (R15) — t.me links resolve to the channel username on every surface.

``add_channel("https://t.me/physics_of_business")`` used to create a source
row keyed by the literal URL (two phantom rows on prod, 2026-08-31). The
single normalizer now resolves a closed grammar of public-channel links to
the username and raises ``InvalidChannelUsername`` for any other link-like
input — never ``None``, which read paths treat as "no channel filter".

Red on ``main`` before R15: the grammar table returns the URL verbatim, the
rejection table returns strings instead of raising, and every surface test
sees the URL (or nothing) instead of the username.
"""

from __future__ import annotations

import contextlib
import os
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from typer.testing import CliRunner

from tg_parser.api.auth import resolve_current_user
from tg_parser.api.main import create_app
from tg_parser.auth.models import CurrentUser
from tg_parser.domain.models import Anchor, MessageType, TopicCard, TopicType
from tg_parser.utils.channel_id import (
    INVALID_CHANNEL_USERNAME_ERROR_CLASS,
    InvalidChannelUsername,
    normalize_channel_id,
    validate_channel_username,
)

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)

CH = "own_channel"
INVITE = "https://t.me/+AbCdEfGh123"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _plain(output: str) -> str:
    return _ANSI_RE.sub("", output)


# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------

ACCEPTED_LINKS = [
    "https://t.me/own_channel",
    "http://t.me/own_channel",
    "t.me/own_channel",
    "HTTPS://T.ME/own_channel",
    "https://www.t.me/own_channel",
    "https://telegram.me/own_channel",
    "www.telegram.me/own_channel",
    "https://t.me/own_channel/",
    "https://t.me/s/own_channel",
    "https://t.me/s/own_channel/",
    "https://t.me/own_channel/12345",
    "https://t.me/s/own_channel/12345",
    "https://t.me/own_channel/",
    "https://t.me/own_channel?single",
    "https://t.me/own_channel/7?comment=3",
    "https://t.me/own_channel#frag",
    "  https://t.me/own_channel  ",
    "'https://t.me/own_channel'",
    '"t.me/own_channel"',
    "https://t.me/@own_channel",
    "https://t.me/s/@own_channel/7",
]

REJECTED_LINKS = [
    "https://telegram.dog/own_channel",
    "tg://resolve?domain=own_channel",
    "https://user@t.me/own_channel",
    "user@t.me/own_channel",
    "https://t.me:443/own_channel",
    "//t.me/own_channel",
    "https:/t.me/own_channel",
    "ftp://t.me/own_channel",
    "https://t.me/%6Fwn_channel",
    "https://t.me/own_channel/123/extra",
    "https://t.me/own_channel/123/",
    "https://t.me/own_channel/12a",
    "https://t.me//own_channel",
    INVITE,
    "t.me/+AbCdEfGh123",
    "https://t.me/joinchat/AbCdEfGh123",
    "https://t.me/joinchat",
    "https://t.me/@joinchat",
    "https://t.me/@",
    "https://t.me/addlist/AbCdEf",
    "https://t.me/share?url=https://x.example",
    "https://t.me/c/1234567890/55",
    "https://t.me/",
    "https://t.me",
    "t.me",
    "https://t.me/s",
    "https://t.me/abc",
    "https://t.me/1channel",
    "evilt.me/own_channel",
    "https://t.me.example.com/own_channel",
    "own_channel.t.me",
    "own.channel",
    "own:channel",
    "own/channel",
    "own_channel?",
    "own_channel#x",
    "own\\channel",
    "https://t.me/ own_channel",
    "https://t.me/own_channel /",
    "https://t.me/own\tchannel",
    "@https://t.me/own_channel",
    "@t.me/own_channel",
    "'@ https://t.me/own_channel'",
    "@own.channel",
]

# Snapshot of every live-or-deleted non-URL channel_id on prod, 2026-09-26.
PROD_CHANNEL_IDS = [
    "-1002120019100",
    "-1002123123123",
    "-1002125361157",
    "AgeManagment",
    "BiocodebySechenov",
    "Docma_ru",
    "Lab4health",
    "LongevityClub",
    "aiinsideteam",
    "andre_dataist",
    "foodf4thought",
    "genotek",
    "kdl_ru",
    "labdiagnostica_logical",
    "mediamedics",
    "medportal_rfed",
    "mind_rise",
    "murashko_med",
    "pashaaiaiai",
    "physics_of_business",
    "profendocrinologist",
    "test_channel_123",
    "tgnikitin",
]


class TestGrammar:
    @pytest.mark.parametrize("raw", ACCEPTED_LINKS)
    def test_public_link_resolves_to_username(self, raw: str):
        assert normalize_channel_id(raw) == CH

    @pytest.mark.parametrize("raw", ACCEPTED_LINKS)
    def test_resolution_is_idempotent(self, raw: str):
        once = normalize_channel_id(raw)
        assert normalize_channel_id(once) == once

    def test_host_case_does_not_touch_username_case(self):
        assert normalize_channel_id("https://T.ME/AgeManagment") == "AgeManagment"

    @pytest.mark.parametrize("raw", REJECTED_LINKS)
    def test_link_outside_grammar_raises_not_none(self, raw: str):
        with pytest.raises(InvalidChannelUsername) as exc_info:
            normalize_channel_id(raw)
        assert isinstance(exc_info.value, ValueError)
        assert exc_info.value.error_class == INVALID_CHANNEL_USERNAME_ERROR_CLASS

    @pytest.mark.parametrize("raw", PROD_CHANNEL_IDS)
    def test_prod_ids_unchanged_bit_for_bit(self, raw: str):
        assert normalize_channel_id(raw) == raw
        assert validate_channel_username(raw) == (raw, None)

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("AgeManagment", "AgeManagment"),
            ("@AgeManagment", "AgeManagment"),
            ("  'AgeManagment' ", "AgeManagment"),
            ("12345", "12345"),
            ("-1002120019100", "-1002120019100"),
            ("pro fendocrinologist", "pro fendocrinologist"),
            ("pro@fendocrinologist", "pro@fendocrinologist"),
            ("ab", "ab"),
            (None, None),
            ("", None),
            ("   ", None),
            ("@", None),
        ],
    )
    def test_non_link_input_keeps_legacy_semantics(self, raw, expected):
        assert normalize_channel_id(raw) == expected

    def test_phantom_prod_rows_resolve_to_the_live_channel(self):
        assert normalize_channel_id("https://t.me/physics_of_business") == "physics_of_business"
        assert normalize_channel_id("t.me/physics_of_business") == "physics_of_business"

    def test_watchlist_permalink_degrades_to_no_link(self):
        from tg_parser.services.watchlist_service import _post_url

        assert _post_url(f"tg:{CH}:post:7") == f"https://t.me/{CH}/7"
        assert _post_url("tg:own.channel:post:7") is None

    def test_advisory_lock_and_dispatch_identity_use_the_same_key(self):
        from tg_parser.services import pipeline_dispatch_service as pds

        pds._running_channel_jobs.add("physics_of_business")
        try:
            assert pds.is_channel_pipeline_busy("physics_of_business")
            assert pds.is_channel_pipeline_busy("https://t.me/physics_of_business")
            with pytest.raises(InvalidChannelUsername):
                pds.is_channel_pipeline_busy(INVITE)
        finally:
            pds._running_channel_jobs.discard("physics_of_business")


class TestAdvisoryLockKey:
    @staticmethod
    def _engine():
        row = MagicMock()
        row.scalar.return_value = True
        conn = AsyncMock()
        conn.execute.return_value = row
        engine = MagicMock()
        engine.connect = AsyncMock(return_value=conn)
        db = MagicMock()
        db.advisory_lock_engine = engine
        return db, engine, conn

    async def _lock_cid(self, channel_id: str) -> str:
        from tg_parser.services.advisory_lock import channel_advisory_lock

        db, _engine, conn = self._engine()
        with patch("tg_parser.storage.sqlalchemy.database.Database.get_instance", return_value=db):
            async with channel_advisory_lock(
                channel_id, namespace=1, engine_attr="advisory_lock_engine", label="t"
            ) as acquired:
                assert acquired
        return conn.execute.await_args_list[0].args[1]["cid"]

    @pytest.mark.parametrize("raw", PROD_CHANNEL_IDS)
    async def test_prod_id_lock_key_unchanged(self, raw: str):
        assert await self._lock_cid(raw) == raw

    async def test_link_locks_the_username_key(self):
        assert await self._lock_cid("https://t.me/physics_of_business/12") == "physics_of_business"

    async def test_rejected_link_never_takes_a_lock(self):
        from tg_parser.services.advisory_lock import channel_advisory_lock

        db, engine, _conn = self._engine()
        with (
            patch("tg_parser.storage.sqlalchemy.database.Database.get_instance", return_value=db),
            pytest.raises(InvalidChannelUsername),
        ):
            async with channel_advisory_lock(
                INVITE, namespace=1, engine_attr="advisory_lock_engine", label="t"
            ):
                pass

        engine.connect.assert_not_awaited()


class TestValidateChannelUsername:
    @pytest.mark.parametrize("raw", ACCEPTED_LINKS)
    def test_public_link_validates_as_username(self, raw: str):
        assert validate_channel_username(raw) == (CH, None)

    @pytest.mark.parametrize("raw", REJECTED_LINKS)
    def test_link_outside_grammar_is_typed_error(self, raw: str):
        value, err = validate_channel_username(raw)
        assert value is None
        assert err is not None
        assert err["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS

    @pytest.mark.parametrize("raw", ACCEPTED_LINKS + REJECTED_LINKS)
    def test_read_and_write_paths_agree(self, raw: str):
        """A link a read path resolves is the id a write path stores, and vice versa."""
        value, err = validate_channel_username(raw)
        try:
            read = normalize_channel_id(raw)
        except InvalidChannelUsername:
            read = None
        assert (value is not None) == (read is not None)
        assert value == read


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------

NOW = datetime(2026, 9, 26, 12, 0, 0, tzinfo=UTC)


def _admin() -> CurrentUser:
    return CurrentUser(
        id="admin-1", name="admin", role="admin", allowed_channel_ids=None, max_channels=100
    )


def _user() -> CurrentUser:
    return CurrentUser(
        id="user-1", name="alice", role="user", allowed_channel_ids=[CH], max_channels=5
    )


def _card() -> TopicCard:
    return TopicCard(
        id=f"topic:tg:{CH}:post:1",
        title="Own topic",
        summary="s",
        scope_in=["in"],
        scope_out=["out"],
        type=TopicType.SINGLETON,
        anchors=[
            Anchor(
                channel_id=CH,
                message_id="1",
                message_type=MessageType.POST,
                anchor_ref=f"tg:{CH}:post:1",
                score=1.0,
            )
        ],
        sources=[CH],
        updated_at=NOW,
    )


def _processing_repos():
    topic_card_repo = AsyncMock()
    topic_card_repo.list_by_channel.return_value = [_card()]
    topic_card_repo.list_by_channels.return_value = [_card()]
    topic_card_repo.list_all_except_deleted.return_value = [_card()]
    topic_bundle_repo = AsyncMock()
    topic_bundle_repo.list_by_channel.return_value = []
    topic_bundle_repo.list_all.return_value = []
    entered = MagicMock()

    @asynccontextmanager
    async def fake_repos():
        entered()
        yield (AsyncMock(), topic_card_repo, topic_bundle_repo, MagicMock())

    return fake_repos, topic_card_repo, entered


class _FakeStateRepo:
    """Dict-backed source table keyed by ``source_id``."""

    def __init__(self) -> None:
        self.rows: dict = {}
        self.upserts = 0
        self.deleted: list[str] = []

    async def get_source(self, source_id, include_deleted=False):
        return self.rows.get(source_id)

    async def get_source_by_username(self, username, include_deleted=False):
        return None

    async def list_sources(self, status=None, owner_id=None, include_deleted=False):
        return list(self.rows.values())

    async def upsert_source(self, source):
        self.upserts += 1
        self.rows[source.source_id] = source

    async def delete_source(self, source_id):
        self.deleted.append(source_id)
        return self.rows.pop(source_id, None) is not None


def _state_ctx(repo: _FakeStateRepo):
    @asynccontextmanager
    async def ctx():
        yield (repo, MagicMock())

    return ctx


def _seeded_repo(status: str = "active") -> _FakeStateRepo:
    from tg_parser.storage.ports import Source

    repo = _FakeStateRepo()
    repo.rows[CH] = Source(
        source_id=CH, channel_id=CH, status=status, include_comments=False, owner_id="admin-1"
    )
    return repo


def _allow_access():
    return patch("tg_parser.auth.ownership.assert_channel_access", AsyncMock())


def _no_audit():
    return patch("tg_parser.auth.audit.audit_channel_event", new_callable=AsyncMock)


# ---------------------------------------------------------------------------
# Read surfaces: a rejected link never widens the scope
# ---------------------------------------------------------------------------


class TestMcpRead:
    async def test_list_topics_link_equals_username(self):
        from tg_parser.mcp_server import list_topics

        fake_repos, topic_card_repo, _ = _processing_repos()
        with patch("tg_parser.services.db_context.processing_repos", fake_repos):
            result = await list_topics(channel_id="https://t.me/own_channel")

        topic_card_repo.list_by_channel.assert_awaited_once_with(CH)
        assert [t.title for t in result.items] == ["Own topic"]

    @pytest.mark.parametrize("raw", [INVITE, "https://evil.example/own_channel"])
    async def test_list_topics_rejected_link_raises_before_lookup(self, raw):
        from tg_parser.mcp_server import list_topics

        fake_repos, topic_card_repo, entered = _processing_repos()
        with (
            patch("tg_parser.services.db_context.processing_repos", fake_repos),
            pytest.raises(InvalidChannelUsername),
        ):
            await list_topics(channel_id=raw)

        entered.assert_not_called()
        topic_card_repo.list_all_except_deleted.assert_not_awaited()

    async def test_search_link_equals_username(self):
        from tg_parser.mcp_server import search_knowledge_base

        with patch(
            "tg_parser.services.retrieval_service.search", new_callable=AsyncMock, return_value=[]
        ) as search:
            await search_knowledge_base("q", channel_id="t.me/s/own_channel/42")

        assert search.await_args.kwargs["channel_id"] == CH

    async def test_search_rejected_link_does_not_search(self):
        from tg_parser.mcp_server import search_knowledge_base

        with (
            patch("tg_parser.services.retrieval_service.search", new_callable=AsyncMock) as search,
            pytest.raises(InvalidChannelUsername),
        ):
            await search_knowledge_base("q", channel_id=INVITE)

        search.assert_not_awaited()

    async def test_cross_channel_stats_rejected_link_does_not_query(self):
        from tg_parser.mcp_server import get_cross_channel_stats

        with (
            patch(
                "tg_parser.services.analytics_service.get_cross_channel_analytics",
                new_callable=AsyncMock,
            ) as analytics,
            pytest.raises(InvalidChannelUsername),
        ):
            await get_cross_channel_stats(channel_id=INVITE)

        analytics.assert_not_awaited()


MCP_CHANNEL_TOOLS = [
    ("pause_channel", {}),
    ("resume_channel", {}),
    ("remove_channel", {"confirm": True}),
    ("trigger_pipeline", {}),
    ("trigger_topicization", {}),
    ("trigger_link_topics", {}),
    ("export_channel", {}),
]


class TestMcpChannelTools:
    @staticmethod
    def _patches():
        from tg_parser.auth.ownership import PermissionDenied

        access = AsyncMock(side_effect=PermissionDenied("denied"))
        return access, (
            patch("tg_parser.auth.ownership.assert_channel_access", access),
            patch(
                "tg_parser.services.channel_service.is_own_removed_channel",
                AsyncMock(return_value=False),
            ),
        )

    @pytest.mark.parametrize("tool, extra", MCP_CHANNEL_TOOLS)
    async def test_link_reaches_rbac_as_username(self, tool, extra):
        import tg_parser.mcp_server as mcp

        access, (p1, p2) = self._patches()
        with p1, p2:
            await getattr(mcp, tool)("https://t.me/own_channel", **extra)

        assert access.await_args.args[1] == CH

    @pytest.mark.parametrize("tool, extra", MCP_CHANNEL_TOOLS)
    async def test_rejected_link_raises_before_rbac(self, tool, extra):
        import tg_parser.mcp_server as mcp

        access, (p1, p2) = self._patches()
        with p1, p2, pytest.raises(InvalidChannelUsername):
            await getattr(mcp, tool)(INVITE, **extra)

        access.assert_not_awaited()

    async def test_pipeline_status_link_filters_by_username(self):
        from tg_parser.mcp_server import get_pipeline_status

        def row(cid):
            return {"source_id": cid, "channel_id": cid, "status": "active"}

        status = {
            "scheduler_enabled": True,
            "default_interval_seconds": 3600,
            "sources": [row(CH), row("kdl_ru")],
        }
        with patch(
            "tg_parser.services.scheduler_service.get_scheduler_status",
            AsyncMock(return_value=status),
        ):
            result = await get_pipeline_status(channel_id="t.me/own_channel")

        assert [s.channel_id for s in result.sources] == [CH]

    async def test_pipeline_status_rejected_link_raises_before_lookup(self):
        from tg_parser.mcp_server import get_pipeline_status

        with (
            patch(
                "tg_parser.services.scheduler_service.get_scheduler_status", AsyncMock()
            ) as lookup,
            pytest.raises(InvalidChannelUsername),
        ):
            await get_pipeline_status(channel_id=INVITE)

        lookup.assert_not_awaited()


class TestBotRead:
    async def test_list_topics_link_equals_username(self):
        from tg_parser.bot.tools import execute_tool

        fake_repos, topic_card_repo, _ = _processing_repos()
        with patch("tg_parser.services.db_context.processing_repos", fake_repos):
            result = await execute_tool(
                "list_topics", {"channel_id": "https://t.me/own_channel"}, current_user=_user()
            )

        topic_card_repo.list_by_channel.assert_awaited_once_with(CH)
        assert result["total"] == 1

    @pytest.mark.parametrize(
        "tool, args",
        [
            ("list_topics", {"channel_id": INVITE}),
            ("search_knowledge_base", {"query": "q", "channel_id": INVITE}),
            ("ask_question", {"question": "q", "channel_id": INVITE}),
            ("get_cross_channel_stats", {"channel_id": "https://telegram.dog/own_channel"}),
        ],
    )
    async def test_rejected_link_is_typed_error_before_lookup(self, tool, args):
        from tg_parser.bot.tools import execute_tool

        fake_repos, _, entered = _processing_repos()
        with (
            patch("tg_parser.services.db_context.processing_repos", fake_repos),
            patch("tg_parser.services.retrieval_service.search", new_callable=AsyncMock) as search,
            patch("tg_parser.services.retrieval_service.answer", new_callable=AsyncMock) as answer,
            patch(
                "tg_parser.services.analytics_service.get_cross_channel_analytics",
                new_callable=AsyncMock,
            ) as analytics,
        ):
            result = await execute_tool(tool, args, current_user=_user())

        assert result["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        entered.assert_not_called()
        search.assert_not_awaited()
        answer.assert_not_awaited()
        analytics.assert_not_awaited()


class TestHttpRead:
    @pytest.fixture
    def app(self):
        app = create_app()
        app.dependency_overrides[resolve_current_user] = lambda: _user()
        yield app
        app.dependency_overrides.clear()

    async def _client(self, app):
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async def test_topics_link_equals_username(self, app):
        fake_repos, topic_card_repo, _ = _processing_repos()
        async with await self._client(app) as client:
            with patch("tg_parser.services.db_context.processing_repos", fake_repos):
                resp = await client.get(
                    "/api/v1/topics", params={"channel_id": "https://t.me/own_channel"}
                )

        assert resp.status_code == 200
        topic_card_repo.list_by_channel.assert_awaited_once_with(CH)
        assert resp.json()["total"] == 1

    async def test_topics_rejected_link_is_422_not_all_channels(self, app):
        fake_repos, topic_card_repo, entered = _processing_repos()
        async with await self._client(app) as client:
            with patch("tg_parser.services.db_context.processing_repos", fake_repos):
                resp = await client.get("/api/v1/topics", params={"channel_id": INVITE})

        assert resp.status_code == 422
        assert resp.json()["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        entered.assert_not_called()
        topic_card_repo.list_by_channels.assert_not_awaited()

    @pytest.mark.parametrize("path", ["/api/v1/search", "/api/v1/ask"])
    async def test_rag_rejected_link_is_422_before_retrieval(self, app, path):
        body = {"query": "q", "question": "q", "channel_id": INVITE}
        async with await self._client(app) as client:
            with (
                patch(
                    "tg_parser.services.retrieval_service.search", new_callable=AsyncMock
                ) as search,
                patch(
                    "tg_parser.services.retrieval_service.answer", new_callable=AsyncMock
                ) as answer,
            ):
                resp = await client.post(path, json=body)

        assert resp.status_code == 422
        search.assert_not_awaited()
        answer.assert_not_awaited()

    async def test_search_link_equals_username(self, app):
        async with await self._client(app) as client:
            with patch(
                "tg_parser.services.retrieval_service.search",
                new_callable=AsyncMock,
                return_value=[],
            ) as search:
                resp = await client.post(
                    "/api/v1/search", json={"query": "q", "channel_id": "t.me/own_channel"}
                )

        assert resp.status_code == 200
        assert search.await_args.kwargs["channel_id"] == CH

    async def test_pipeline_trigger_rejected_link_is_422_before_rbac(self, app):
        async with await self._client(app) as client:
            with patch(
                "tg_parser.api.routes.pipeline.assert_channel_access", new_callable=AsyncMock
            ) as access:
                resp = await client.post("/api/v1/pipeline/trigger", json={"channel_id": INVITE})

        assert resp.status_code == 422
        access.assert_not_awaited()

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/channels/t.me/own_channel/stats",
            "/api/v1/channels/https%3A%2F%2Ft.me%2Fown_channel/stats",
        ],
    )
    async def test_channel_stats_path_link_is_404_without_lookup(self, app, path):
        async with await self._client(app) as client:
            with (
                patch(
                    "tg_parser.api.routes.channels.assert_channel_access", new_callable=AsyncMock
                ) as access,
                patch(
                    "tg_parser.services.channel_service.get_channel_stats", new_callable=AsyncMock
                ) as stats,
            ):
                resp = await client.get(path)

        assert resp.status_code == 404
        access.assert_not_awaited()
        stats.assert_not_awaited()

    async def test_channel_stats_canonical_id_reaches_rbac(self, app):
        from tg_parser.auth.ownership import PermissionDenied

        access = AsyncMock(side_effect=PermissionDenied("denied"))
        async with await self._client(app) as client:
            with patch("tg_parser.api.routes.channels.assert_channel_access", access):
                resp = await client.get("/api/v1/channels/@own_channel/stats")

        assert resp.status_code == 403
        assert access.await_args.args[1] == CH

    async def test_channel_stats_link_like_id_is_422_before_rbac(self, app):
        async with await self._client(app) as client:
            with patch(
                "tg_parser.api.routes.channels.assert_channel_access", new_callable=AsyncMock
            ) as access:
                resp = await client.get("/api/v1/channels/tg:own_channel/stats")

        assert resp.status_code == 422
        access.assert_not_awaited()

    def test_request_models_canonicalize(self):
        from tg_parser.api.schemas import (
            DigestCreateRequest,
            ExportRequest,
            PipelineTriggerRequest,
            ProcessRequest,
            WatchlistCreateRequest,
        )

        link = "https://t.me/own_channel/5"
        assert ProcessRequest(channel_id=link).channel_id == CH
        assert PipelineTriggerRequest(channel_id=link).channel_id == CH
        assert ExportRequest(channel_id=link).channel_id == CH
        assert DigestCreateRequest(name="n", channel_ids=[link], chat_id=1).channel_ids == [CH]
        assert WatchlistCreateRequest(title="t", channel_ids=[link], chat_id=1).channel_ids == [CH]

    async def test_digest_and_watchlist_rejected_link_is_422(self, app):
        async with await self._client(app) as client:
            with (
                patch(
                    "tg_parser.services.digest_service.DigestService.subscribe",
                    new_callable=AsyncMock,
                ) as digest_subscribe,
                patch(
                    "tg_parser.services.watchlist_service.WatchlistService.subscribe",
                    new_callable=AsyncMock,
                ) as watch_subscribe,
            ):
                digest = await client.post(
                    "/api/v1/digests", json={"name": "n", "channel_ids": [INVITE], "chat_id": 1}
                )
                watch = await client.post(
                    "/api/v1/watchlists",
                    json={"title": "t", "channel_ids": [INVITE], "chat_id": 1},
                )

        assert digest.status_code == 422
        assert watch.status_code == 422
        digest_subscribe.assert_not_awaited()
        watch_subscribe.assert_not_awaited()
        for resp in (digest, watch):
            assert resp.json()["detail"][0]["type"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS

    @pytest.mark.parametrize(
        "module, path, body",
        [
            ("process", "/api/v1/process", {}),
            ("export", "/api/v1/export", {"level": "raw"}),
            ("pipeline", "/api/v1/pipeline/trigger", {}),
        ],
    )
    async def test_job_link_reaches_rbac_as_username(self, app, module, path, body):
        from tg_parser.auth.ownership import PermissionDenied

        access = AsyncMock(side_effect=PermissionDenied("denied"))
        async with await self._client(app) as client:
            with patch(f"tg_parser.api.routes.{module}.assert_channel_access", access):
                resp = await client.post(
                    path, json={**body, "channel_id": "https://t.me/own_channel"}
                )

        assert resp.status_code == 403
        assert access.await_args.args[1] == CH

    def test_braces_in_rejected_input_are_echoed_verbatim(self):
        from pydantic import ValidationError

        from tg_parser.api.routes.rag import SearchRequest
        from tg_parser.api.schemas import DigestCreateRequest

        for model, kwargs in (
            (SearchRequest, {"query": "q", "channel_id": "t.me/+{x}{0}"}),
            (DigestCreateRequest, {"name": "n", "chat_id": 1, "channel_ids": ["t.me/+{x}{0}"]}),
        ):
            with pytest.raises(ValidationError) as exc_info:
                model(**kwargs)
            error = exc_info.value.errors()[0]
            assert error["type"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS
            assert "t.me/+{x}{0}" in error["msg"]

    async def test_rejected_link_under_known_key_is_adr0009_mismatch(self, app):
        from tg_parser.api.idempotency import MISMATCH_ERROR_CLASS, get_idempotency_key_repo

        repo = AsyncMock()
        repo.find_by_key.return_value = MagicMock(request_hash="stored-hash-of-another-body")
        app.dependency_overrides[get_idempotency_key_repo] = lambda: repo
        async with await self._client(app) as client:
            with patch(
                "tg_parser.services.digest_service.DigestService.subscribe", new_callable=AsyncMock
            ) as subscribe:
                resp = await client.post(
                    "/api/v1/digests",
                    json={"name": "n", "channel_ids": [INVITE], "chat_id": 1},
                    headers={"Idempotency-Key": "k-1"},
                )

        assert resp.status_code == 422
        assert resp.json()["error_class"] == MISMATCH_ERROR_CLASS
        subscribe.assert_not_awaited()

    async def test_rejected_link_under_fresh_key_is_invalid_channel(self, app):
        from tg_parser.api.idempotency import get_idempotency_key_repo

        repo = AsyncMock()
        repo.find_by_key.return_value = None
        app.dependency_overrides[get_idempotency_key_repo] = lambda: repo
        async with await self._client(app) as client:
            with patch(
                "tg_parser.services.digest_service.DigestService.subscribe", new_callable=AsyncMock
            ) as subscribe:
                resp = await client.post(
                    "/api/v1/digests",
                    json={"name": "n", "channel_ids": [INVITE], "chat_id": 1},
                    headers={"Idempotency-Key": "k-1"},
                )

        assert resp.status_code == 422
        assert resp.json()["detail"][0]["type"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        subscribe.assert_not_awaited()
        repo.insert.assert_not_awaited()

    async def test_body_filter_rejection_carries_error_class(self, app):
        async with await self._client(app) as client:
            resp = await client.post("/api/v1/search", json={"query": "q", "channel_id": INVITE})

        assert resp.status_code == 422
        assert resp.json()["detail"][0]["type"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS

    def test_idempotency_hash_uses_canonical_source_ids(self):
        import json

        from tg_parser.api.idempotency import _hash_body

        def body(**kw):
            return json.dumps({"name": "n", "chat_id": 1, **kw}).encode()

        assert _hash_body(body(channel_ids=["@own_channel"])) == _hash_body(
            body(channel_ids=["https://t.me/own_channel"])
        )
        assert _hash_body(body(channel_id="own_channel")) == _hash_body(
            body(channel_id="t.me/s/own_channel")
        )
        assert _hash_body(body(channel_ids=[CH])) != _hash_body(body(channel_ids=["kdl_ru"]))
        assert _hash_body(body(channel_ids=[INVITE])) != _hash_body(
            body(channel_ids=["t.me/+AbCdEfGh123"])
        )
        target = {"kind": "channel", "channel_id": "@own_channel"}
        assert _hash_body(body(target=target)) != _hash_body(
            body(target={**target, "channel_id": "own_channel"})
        )


class TestCliRead:
    @pytest.mark.parametrize("raw", [INVITE, "https://t.me/c/123/4"])
    def test_search_rejected_link_is_usage_error(self, raw):
        from tg_parser.cli.app import app

        with (
            patch(
                "tg_parser.cli.app._resolve_workspace_scope_cli",
                new_callable=AsyncMock,
                return_value=(None, True),
            ),
            patch("tg_parser.services.retrieval_service.search", new_callable=AsyncMock) as search,
        ):
            result = CliRunner().invoke(app, ["search", "--query", "q", "--channel", raw])

        assert result.exit_code == 2
        assert "Invalid value for --channel" in _plain(result.output)
        search.assert_not_awaited()

    def test_search_link_equals_username(self):
        from tg_parser.cli.app import app

        with (
            patch(
                "tg_parser.cli.app._resolve_workspace_scope_cli",
                new_callable=AsyncMock,
                return_value=(None, True),
            ),
            patch(
                "tg_parser.services.retrieval_service.search",
                new_callable=AsyncMock,
                return_value=[],
            ) as search,
        ):
            result = CliRunner().invoke(
                app, ["search", "--query", "q", "--channel", "https://t.me/own_channel"]
            )

        assert result.exit_code == 0, result.output
        assert search.await_args.kwargs["channel_id"] == CH

    @pytest.mark.parametrize(
        "argv, target, pick",
        [
            (
                ["ask", "--question", "q"],
                "tg_parser.services.retrieval_service.answer",
                lambda call: call.kwargs["channel_id"],
            ),
            (
                ["export", "--out", "/tmp/df4-unused"],
                "tg_parser.cli.export_cmd.run_export",
                lambda call: call.kwargs["channel_id"],
            ),
            (
                ["process"],
                "tg_parser.cli.process_cmd.run_processing",
                lambda call: call.args[0],
            ),
            (
                ["embed"],
                "tg_parser.services.embedding_service.run_embedding",
                lambda call: call.kwargs["channel_id"],
            ),
        ],
    )
    def test_command_link_reaches_service_as_username(self, argv, target, pick):
        from tg_parser.cli.app import app

        service = AsyncMock(side_effect=RuntimeError("stop after capture"))
        with (
            patch(
                "tg_parser.cli.app._resolve_workspace_scope_cli",
                new_callable=AsyncMock,
                return_value=(None, True),
            ),
            patch(target, service),
        ):
            CliRunner().invoke(app, [*argv, "--channel", "https://t.me/own_channel"])

        assert pick(service.await_args) == CH

    def test_topicize_link_reaches_service_as_username(self):
        from tg_parser.cli.app import app

        with patch("tg_parser.cli.app._run_full_topicization") as run:
            result = CliRunner().invoke(
                app, ["topicize", "--channel", "t.me/own_channel", "--mode", "full"]
            )

        assert result.exit_code == 0, result.output
        assert run.call_args.args[0] == CH

    def test_workspace_add_source_link_is_stored_as_username(self):
        from tg_parser.cli.workspace_cmd import app as workspace_app

        add_source = AsyncMock(return_value=True)

        @asynccontextmanager
        async def fake_repo():
            yield (MagicMock(), MagicMock())

        with (
            patch("tg_parser.cli.workspace_cmd._resolve_acting_user", AsyncMock()),
            patch("tg_parser.services.db_context.workspace_repo", fake_repo),
            patch("tg_parser.services.workspace_service.WorkspaceService.add_source", add_source),
            patch("tg_parser.storage.sqlalchemy.database.Database.close_instance", AsyncMock()),
        ):
            ok = CliRunner().invoke(
                workspace_app, ["add-source", "ws-1", "--channel", "https://t.me/own_channel"]
            )
            again = CliRunner().invoke(
                workspace_app, ["add-source", "ws-1", "--channel", "@own_channel"]
            )
            bad = CliRunner().invoke(workspace_app, ["add-source", "ws-1", "--channel", INVITE])

        assert ok.exit_code == 0, ok.output
        assert again.exit_code == 0, again.output
        assert [c.args[1:] for c in add_source.await_args_list] == [("ws-1", CH)] * 2
        assert bad.exit_code == 2
        assert add_source.await_count == 2

    def test_keyword_and_topic_lists_are_not_parsed_as_links(self):
        from tg_parser.cli.watchlist_cmd import _split_csv

        assert _split_csv("ai/ml, @covid:19 ,'x.y'") == ["ai/ml", "covid:19", "x.y"]
        assert _split_csv("topic:tg:own_channel:post:1") == ["topic:tg:own_channel:post:1"]

    def test_source_channel_list(self):
        import typer

        from tg_parser.cli.channel_args import source_channel_list

        assert source_channel_list("https://t.me/own_channel, ,@kdl_ru") == [CH, "kdl_ru"]
        with pytest.raises(typer.BadParameter):
            source_channel_list(f"kdl_ru,{INVITE}")

    @pytest.mark.parametrize(
        "raw",
        [
            "https://t.me/own_channel?x=1,2",
            "kdl_ru,https://t.me/own_channel?x=1,2",
            "https://t.me/own_channel#a,kdl_ru",
        ],
    )
    def test_source_channel_list_comma_after_link_tail_is_usage_error(self, raw):
        import typer

        from tg_parser.cli.channel_args import source_channel_list

        with pytest.raises(typer.BadParameter):
            source_channel_list(raw)

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("kdl_ru,https://t.me/own_channel?x=1", ["kdl_ru", CH]),
            ("https://t.me/own_channel/7?comment=3, ,", [CH]),
        ],
    )
    def test_source_channel_list_link_tail_on_last_entry(self, raw, expected):
        from tg_parser.cli.channel_args import source_channel_list

        assert source_channel_list(raw) == expected


# ---------------------------------------------------------------------------
# Write surfaces: one row per channel, whatever the spelling
# ---------------------------------------------------------------------------


class TestMcpWrite:
    async def test_add_channel_link_and_username_are_one_row(self):
        from tg_parser.mcp_server import add_channel

        repo = _FakeStateRepo()
        with (
            patch("tg_parser.services.db_context.ingestion_state_repo", _state_ctx(repo)),
            patch("tg_parser.auth.audit.audit_channel_event", new_callable=AsyncMock),
        ):
            first = await add_channel("https://t.me/own_channel")
            second = await add_channel("@own_channel")
            third = await add_channel("t.me/s/own_channel/9")

        assert (first.created, second.created, third.created) == (True, False, False)
        assert first.channel_id == second.channel_id == third.channel_id == CH
        assert list(repo.rows) == [CH]
        assert repo.rows[CH].channel_id == CH

    async def test_add_channel_invite_is_rejected_without_write(self):
        from tg_parser.mcp_server import add_channel

        repo = _FakeStateRepo()
        with patch("tg_parser.services.db_context.ingestion_state_repo", _state_ctx(repo)):
            result = await add_channel(INVITE)

        assert result.status == "rejected"
        assert result.created is False
        assert repo.upserts == 0

    async def test_add_channel_placeholder_link_is_blocked(self):
        from tg_parser.mcp_server import add_channel

        repo = _FakeStateRepo()
        with patch("tg_parser.services.db_context.ingestion_state_repo", _state_ctx(repo)):
            result = await add_channel("https://t.me/test_channel")

        assert result.status == "rejected"
        assert result.channel_id == "test_channel"
        assert repo.upserts == 0

    def test_subscription_channel_ids_are_validated(self):
        from tg_parser.mcp_server import _validate_source_channel_ids

        assert _validate_source_channel_ids(["https://t.me/own_channel", " ", "@kdl_ru"]) == (
            [CH, "kdl_ru"],
            None,
        )
        ids, error = _validate_source_channel_ids(["kdl_ru", INVITE])
        assert ids == []
        assert error is not None and INVITE in error

    @pytest.mark.parametrize("tool", ["subscribe_digest", "subscribe_watchlist"])
    async def test_subscribe_invite_is_rejected_before_rbac(self, tool):
        import tg_parser.mcp_server as mcp

        kwargs = {"channel_ids": [INVITE], "chat_id": 1}
        kwargs["name" if tool == "subscribe_digest" else "title"] = "n"
        with patch(
            "tg_parser.auth.ownership.assert_channel_access", new_callable=AsyncMock
        ) as access:
            result = await getattr(mcp, tool)(**kwargs)

        assert result.success is False
        assert "t.me/+" in result.message
        access.assert_not_awaited()

    @pytest.mark.parametrize("tool", ["subscribe_digest", "subscribe_watchlist"])
    async def test_subscribe_link_reaches_rbac_as_username(self, tool):
        import tg_parser.mcp_server as mcp
        from tg_parser.auth.ownership import PermissionDenied

        kwargs = {"channel_ids": ["https://t.me/own_channel"], "chat_id": 1}
        kwargs["name" if tool == "subscribe_digest" else "title"] = "n"
        access = AsyncMock(side_effect=PermissionDenied("denied"))
        with patch("tg_parser.auth.ownership.assert_channel_access", access):
            result = await getattr(mcp, tool)(**kwargs)

        assert result.success is False
        assert access.await_args.args[1] == CH

    async def test_add_workspace_source_invite_is_rejected(self):
        from tg_parser.mcp_server import add_workspace_source

        with patch("tg_parser.services.db_context.workspace_repo") as ws_repo:
            result = await add_workspace_source("ws-1", INVITE)

        assert result.success is False
        ws_repo.assert_not_called()


class TestBotWrite:
    async def test_add_channel_link_and_username_are_one_row(self):
        from tg_parser.bot.tools import _exec_add_channel

        repo = _FakeStateRepo()
        with (
            patch("tg_parser.services.db_context.ingestion_state_repo", _state_ctx(repo)),
            patch("tg_parser.auth.audit.audit_channel_event", new_callable=AsyncMock),
        ):
            first = await _exec_add_channel(
                {"channel_id": "https://t.me/own_channel", "confirm": True}, current_user=_admin()
            )
            second = await _exec_add_channel(
                {"channel_id": "@own_channel", "confirm": True}, current_user=_admin()
            )

        assert (first["created"], second["created"]) == (True, False)
        assert list(repo.rows) == [CH]

    async def test_add_channel_invite_is_typed_error(self):
        from tg_parser.bot.tools import _exec_add_channel

        repo = _FakeStateRepo()
        with patch("tg_parser.services.db_context.ingestion_state_repo", _state_ctx(repo)):
            result = await _exec_add_channel(
                {"channel_id": INVITE, "confirm": True}, current_user=_admin()
            )

        assert result["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        assert repo.upserts == 0

    async def test_add_channel_placeholder_link_is_blocked(self):
        from tg_parser.bot.tools import _exec_add_channel

        repo = _FakeStateRepo()
        with patch("tg_parser.services.db_context.ingestion_state_repo", _state_ctx(repo)):
            result = await _exec_add_channel(
                {"channel_id": "t.me/test_channel", "confirm": True}, current_user=_admin()
            )

        assert result["error"] == "blocked_placeholder_name"
        assert repo.upserts == 0


class TestBotSubscribe:
    @pytest.mark.parametrize(
        "tool, label", [("subscribe_digest", "name"), ("subscribe_watchlist", "title")]
    )
    async def test_link_reaches_rbac_as_username(self, tool, label):
        from tg_parser.auth.ownership import PermissionDenied
        from tg_parser.bot import tools

        access = AsyncMock(side_effect=PermissionDenied("denied"))
        with (
            patch("tg_parser.auth.ownership.assert_channel_access", access),
            patch("tg_parser.bot.tools.verify_channel_exists", AsyncMock(return_value=True)),
        ):
            result = await tools._TOOL_EXECUTORS[tool](
                {label: "n", "channel_ids": ["https://t.me/own_channel"], "chat_id": 1},
                current_user=_user(),
            )

        assert access.await_args.args[1] == CH
        assert result["channel_id"] == CH

    @pytest.mark.parametrize(
        "tool, label", [("subscribe_digest", "name"), ("subscribe_watchlist", "title")]
    )
    async def test_invite_is_typed_error_before_rbac(self, tool, label):
        from tg_parser.bot import tools

        access = AsyncMock()
        with patch("tg_parser.auth.ownership.assert_channel_access", access):
            result = await tools._TOOL_EXECUTORS[tool](
                {label: "n", "channel_ids": [INVITE], "chat_id": 1}, current_user=_user()
            )

        assert result["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        access.assert_not_awaited()


class TestCliWrite:
    async def test_add_source_both_link_forms_update_one_row(self):
        from tg_parser.cli.add_source_cmd import run_add_source

        repo = _FakeStateRepo()
        with patch("tg_parser.services.db_context.ingestion_state_repo", _state_ctx(repo)):
            for link in ("https://t.me/own_channel", "t.me/own_channel"):
                await run_add_source(source_id="src_1", channel_id=link, owner_id="admin-1")

        assert list(repo.rows) == ["src_1"]
        assert repo.rows["src_1"].channel_id == CH
        assert repo.upserts == 2

    async def test_add_source_invite_is_rejected(self):
        from tg_parser.cli.add_source_cmd import AddSourceError, run_add_source

        repo = _FakeStateRepo()
        with (
            patch("tg_parser.services.db_context.ingestion_state_repo", _state_ctx(repo)),
            pytest.raises(AddSourceError),
        ):
            await run_add_source(source_id="src_1", channel_id=INVITE, owner_id="admin-1")

        assert repo.upserts == 0

    @pytest.mark.parametrize("cmd", ["digest", "watchlist"])
    def test_subscription_invite_is_usage_error(self, cmd):
        from tg_parser.cli.app import app

        label = "--name" if cmd == "digest" else "--title"
        result = CliRunner().invoke(
            app, [cmd, "add", label, "n", "--chat-id", "1", "--channels", INVITE]
        )

        assert result.exit_code == 2
        assert "Invalid value for --channels" in _plain(result.output)


@pg_only
class TestHttpDigestPg:
    async def test_link_and_username_update_one_subscription(self, test_db):
        from sqlalchemy import text

        from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo

        session = test_db.ingestion_state_session()
        try:
            owner = await SAUserRepo(session).create_user("df4_digest_owner")
        finally:
            await session.close()

        app = create_app()
        app.dependency_overrides[resolve_current_user] = lambda: CurrentUser(
            id=owner.id, name=owner.name, role="user", allowed_channel_ids=[], max_channels=5
        )
        body = {"name": "df4", "chat_id": 1, "channel_ids": ["@own_channel"]}
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                first = await c.post("/api/v1/digests", json=body)
                body["channel_ids"] = ["https://t.me/own_channel"]
                second = await c.post("/api/v1/digests", json=body)
                listing = await c.get("/api/v1/digests")
        finally:
            session = test_db.ingestion_state_session()
            try:
                await session.execute(
                    text("DELETE FROM digest_subscriptions WHERE owner_id = :o"), {"o": owner.id}
                )
                await session.execute(text("DELETE FROM users WHERE id = :o"), {"o": owner.id})
                await session.commit()
            finally:
                await session.close()

        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        assert second.json()["created"] is False
        assert second.json()["changed_fields"] == []
        assert [d["channel_ids"] for d in listing.json()["items"]] == [[CH]]


# ---------------------------------------------------------------------------
# Operation matrix: on every surface × operation a link reaches the
# operation's own downstream call as the username, and a rejected link
# never reaches it.
# ---------------------------------------------------------------------------

LINK = "https://t.me/own_channel"


def _answer_result():
    return MagicMock(answer="a", sources=[], model="m", degraded=False)


def _dispatch_result(job: str = "full_pipeline"):
    from tg_parser.services.pipeline_dispatch_client import PipelineDispatchClientResult

    return PipelineDispatchClientResult(
        channel_id=CH, triggered=True, message="ok", job_id="j-1", job=job
    )


def _removal_ctx(repo: _FakeStateRepo):
    @asynccontextmanager
    async def ctx():
        yield (repo, *(MagicMock() for _ in range(9)))

    return ctx


class TestMcpOperations:
    async def test_ask_question(self):
        from tg_parser.mcp_server import ask_question

        answer = AsyncMock(return_value=_answer_result())
        with patch("tg_parser.services.retrieval_service.answer", answer):
            await ask_question("q", channel_id=LINK)
            with pytest.raises(InvalidChannelUsername):
                await ask_question("q", channel_id=INVITE)

        answer.assert_awaited_once()
        assert answer.await_args.kwargs["channel_id"] == CH

    async def test_cross_channel_stats(self):
        from tg_parser.mcp_server import get_cross_channel_stats

        analytics = AsyncMock(
            return_value={
                "total_documents": 0,
                "total_topics": 0,
                "channels": [],
                "keyword_overlaps": [],
                "overlap_count": 0,
            }
        )
        with patch("tg_parser.services.analytics_service.get_cross_channel_analytics", analytics):
            await get_cross_channel_stats(channel_id="t.me/s/own_channel")

        assert analytics.await_args.kwargs["channel_id"] == CH

    @pytest.mark.parametrize(
        "tool, before, after",
        [("pause_channel", "active", "paused"), ("resume_channel", "paused", "active")],
    )
    async def test_status_change_lands_on_the_username_row(self, tool, before, after):
        import tg_parser.mcp_server as mcp

        repo = _seeded_repo(before)
        with (
            _allow_access(),
            _no_audit(),
            patch("tg_parser.services.db_context.ingestion_state_repo", _state_ctx(repo)),
        ):
            result = await getattr(mcp, tool)(LINK)
            with pytest.raises(InvalidChannelUsername):
                await getattr(mcp, tool)(INVITE)

        assert result.changed is True
        assert repo.rows[CH].status == after
        assert repo.upserts == 1

    async def test_remove_channel_soft_deletes_the_username_row(self):
        from tg_parser.mcp_server import remove_channel

        repo = _seeded_repo()
        with (
            _allow_access(),
            _no_audit(),
            patch("tg_parser.services.db_context.removal_repos", _removal_ctx(repo)),
        ):
            result = await remove_channel("t.me/own_channel/3", confirm=True)
            with pytest.raises(InvalidChannelUsername):
                await remove_channel(INVITE, confirm=True)

        assert result.removed is True
        assert repo.deleted == [CH]

    @pytest.mark.parametrize(
        "tool, job",
        [
            ("trigger_pipeline", "full_pipeline"),
            ("trigger_topicization", "topicization"),
            ("trigger_link_topics", "link_topics"),
        ],
    )
    async def test_trigger_dispatches_the_username(self, tool, job):
        import tg_parser.mcp_server as mcp

        post = AsyncMock(return_value=_dispatch_result(job))
        with (
            _allow_access(),
            patch("tg_parser.services.pipeline_dispatch_client.post_pipeline_trigger", post),
        ):
            result = await getattr(mcp, tool)(LINK)
            with pytest.raises(InvalidChannelUsername):
                await getattr(mcp, tool)(INVITE)

        assert result.triggered is True
        post.assert_awaited_once()
        assert post.await_args.kwargs["channel_id"] == CH
        assert post.await_args.kwargs["job"] == job

    async def test_export_dispatches_the_username(self):
        from tg_parser.mcp_server import export_channel
        from tg_parser.services.pipeline_dispatch_client import ExportDispatchClientResult

        post = AsyncMock(
            return_value=ExportDispatchClientResult(
                job_id="j-1", status="pending", message="ok", channel_id=CH
            )
        )
        with (
            _allow_access(),
            patch("tg_parser.services.pipeline_dispatch_client.post_export", post),
        ):
            await export_channel("t.me/s/own_channel/9")
            with pytest.raises(InvalidChannelUsername):
                await export_channel(INVITE)

        post.assert_awaited_once()
        assert post.await_args.kwargs["channel_id"] == CH

    async def test_remove_workspace_source_detaches_the_username(self):
        from tg_parser.mcp_server import remove_workspace_source

        @asynccontextmanager
        async def fake_repo():
            yield (MagicMock(), MagicMock())

        remove = AsyncMock(return_value=True)
        with (
            patch("tg_parser.services.db_context.workspace_repo", fake_repo),
            patch("tg_parser.services.workspace_service.WorkspaceService.remove_source", remove),
        ):
            result = await remove_workspace_source("ws-1", "t.me/s/own_channel")
            with pytest.raises(InvalidChannelUsername):
                await remove_workspace_source("ws-1", INVITE)

        assert result.changed is True
        remove.assert_awaited_once()
        assert remove.await_args.args[1:] == ("ws-1", CH)


class TestBotOperations:
    @pytest.mark.parametrize(
        "tool, args, target",
        [
            (
                "search_knowledge_base",
                {"query": "q"},
                "tg_parser.services.retrieval_service.search",
            ),
            ("ask_question", {"question": "q"}, "tg_parser.services.retrieval_service.answer"),
            (
                "get_cross_channel_stats",
                {},
                "tg_parser.services.analytics_service.get_cross_channel_analytics",
            ),
        ],
    )
    async def test_read_link_reaches_service_as_username(self, tool, args, target):
        from tg_parser.bot.tools import execute_tool

        service = AsyncMock(side_effect=RuntimeError("stop after capture"))
        with patch(target, service), contextlib.suppress(RuntimeError):
            await execute_tool(tool, {**args, "channel_id": LINK}, current_user=_user())

        assert service.await_args.kwargs["channel_id"] == CH

    async def test_pipeline_status(self):
        from tg_parser.bot.tools import execute_tool

        def row(cid):
            return {"source_id": cid, "channel_id": cid, "status": "active"}

        lookup = AsyncMock(
            return_value={
                "scheduler_enabled": True,
                "default_interval_seconds": 3600,
                "sources": [row(CH), row("kdl_ru")],
            }
        )
        with patch("tg_parser.services.scheduler_service.get_scheduler_status", lookup):
            ok = await execute_tool(
                "get_pipeline_status", {"channel_id": "t.me/own_channel"}, current_user=_admin()
            )
            bad = await execute_tool(
                "get_pipeline_status", {"channel_id": INVITE}, current_user=_admin()
            )

        assert [s["channel_id"] for s in ok["sources"]] == [CH]
        assert bad["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        lookup.assert_awaited_once()

    async def test_trigger_pipeline_dispatches_the_username(self):
        from tg_parser.bot import tools

        repo = _seeded_repo()
        post = AsyncMock(return_value=_dispatch_result())
        with (
            _allow_access(),
            patch("tg_parser.services.db_context.ingestion_state_repo", _state_ctx(repo)),
            patch(
                "tg_parser.services.scheduler_service.get_scheduler_status",
                AsyncMock(return_value={"sources": []}),
            ),
            patch(
                "tg_parser.services.channel_service.get_channel_stats",
                AsyncMock(return_value={"processed_documents": 0}),
            ),
            patch(
                "tg_parser.services.pipeline_dispatch_client.resolve_dispatch_api_key_for_user",
                AsyncMock(return_value="k"),
            ),
            patch("tg_parser.services.pipeline_dispatch_client.post_pipeline_trigger", post),
        ):
            ok = await tools._TOOL_EXECUTORS["trigger_pipeline"](
                {"channel_id": LINK, "confirm": True}, current_user=_admin()
            )
            bad = await tools.execute_tool(
                "trigger_pipeline", {"channel_id": INVITE}, current_user=_admin()
            )

        assert ok["triggered"] is True
        assert bad["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS
        post.assert_awaited_once()
        assert post.await_args.kwargs["channel_id"] == CH

    @pytest.mark.parametrize(
        "tool, before, after",
        [("pause_channel", "active", "paused"), ("resume_channel", "paused", "active")],
    )
    async def test_status_change_lands_on_the_username_row(self, tool, before, after):
        from tg_parser.bot import tools

        repo = _seeded_repo(before)
        with (
            _allow_access(),
            _no_audit(),
            patch("tg_parser.services.db_context.ingestion_state_repo", _state_ctx(repo)),
        ):
            ok = await tools._TOOL_EXECUTORS[tool](
                {"channel_id": LINK, "confirm": True}, current_user=_admin()
            )
            bad = await tools.execute_tool(tool, {"channel_id": INVITE}, current_user=_admin())

        assert ok["changed"] is True
        assert repo.rows[CH].status == after
        assert repo.upserts == 1
        assert bad["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS

    async def test_remove_channel_soft_deletes_the_username_row(self):
        from tg_parser.bot import tools

        repo = _seeded_repo()
        with (
            _allow_access(),
            _no_audit(),
            patch("tg_parser.services.db_context.ingestion_state_repo", _state_ctx(repo)),
        ):
            ok = await tools._TOOL_EXECUTORS["remove_channel"](
                {"channel_id": LINK, "confirm": True}, current_user=_admin()
            )
            bad = await tools.execute_tool(
                "remove_channel", {"channel_id": INVITE}, current_user=_admin()
            )

        assert ok["removed"] is True
        assert repo.deleted == [CH]
        assert bad["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS

    async def test_export_runs_for_the_username(self):
        from tg_parser.bot import tools

        run = AsyncMock(side_effect=ValueError("stop after capture"))
        with _allow_access(), patch("tg_parser.services.export_service.run_export", run):
            await tools._TOOL_EXECUTORS["export_channel"](
                {"channel_id": LINK}, current_user=_admin()
            )
            bad = await tools.execute_tool(
                "export_channel", {"channel_id": INVITE}, current_user=_admin()
            )

        run.assert_awaited_once()
        assert run.await_args.kwargs["channel_id"] == CH
        assert bad["error_class"] == INVALID_CHANNEL_USERNAME_ERROR_CLASS


class TestHttpOperations:
    @pytest.fixture
    def app(self):
        app = create_app()
        app.dependency_overrides[resolve_current_user] = lambda: _user()
        yield app
        app.dependency_overrides.clear()

    def _client(self, app):
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async def test_ask(self, app):
        answer = AsyncMock(return_value=_answer_result())
        async with self._client(app) as client:
            with patch("tg_parser.services.retrieval_service.answer", answer):
                resp = await client.post("/api/v1/ask", json={"question": "q", "channel_id": LINK})

        assert resp.status_code == 200, resp.text
        assert answer.await_args.kwargs["channel_id"] == CH

    @pytest.mark.parametrize(
        "module, path, body, runner",
        [
            ("process", "/api/v1/process", {}, "_run_processing_job"),
            ("export", "/api/v1/export", {"level": "raw"}, "_run_export_job"),
        ],
    )
    async def test_job_is_stored_under_the_username(self, app, module, path, body, runner):
        store = MagicMock()
        store.create_job = AsyncMock()
        route = f"tg_parser.api.routes.{module}"
        async with self._client(app) as client:
            with (
                patch(f"{route}.assert_channel_access", AsyncMock()),
                patch(f"{route}.ensure_job_store_initialized", AsyncMock(return_value=store)),
                patch(f"{route}.{runner}", AsyncMock()),
            ):
                ok = await client.post(path, json={**body, "channel_id": LINK})
                bad = await client.post(path, json={**body, "channel_id": INVITE})

        assert ok.status_code < 300, ok.text
        assert bad.status_code == 422
        store.create_job.assert_awaited_once()
        assert store.create_job.await_args.args[0].channel_id == CH

    async def test_pipeline_trigger_dispatches_the_username(self, app):
        from tg_parser.services.pipeline_dispatch_service import PipelineDispatchError

        trigger = AsyncMock(
            side_effect=PipelineDispatchError(
                error_class="JobAlreadyRunning", message="busy", status_code=409
            )
        )
        async with self._client(app) as client:
            with (
                patch("tg_parser.api.routes.pipeline.assert_channel_access", AsyncMock()),
                patch("tg_parser.api.routes.pipeline.trigger_pipeline_job", trigger),
            ):
                resp = await client.post(
                    "/api/v1/pipeline/trigger", json={"channel_id": "t.me/own_channel/4"}
                )

        assert resp.status_code == 409
        assert trigger.await_args.kwargs["channel_id"] == CH


CLI_CHANNEL_COMMANDS = [
    (
        ["ask", "--question", "q"],
        "tg_parser.services.retrieval_service.answer",
    ),
    (["export", "--out", "/tmp/df4-unused"], "tg_parser.cli.export_cmd.run_export"),
    (["process"], "tg_parser.cli.process_cmd.run_processing"),
    (["embed"], "tg_parser.services.embedding_service.run_embedding"),
]


class TestCliOperations:
    @pytest.mark.parametrize("argv, target", CLI_CHANNEL_COMMANDS)
    def test_rejected_link_never_reaches_the_service(self, argv, target):
        from tg_parser.cli.app import app

        service = AsyncMock()
        with (
            patch(
                "tg_parser.cli.app._resolve_workspace_scope_cli",
                new_callable=AsyncMock,
                return_value=(None, True),
            ),
            patch(target, service),
        ):
            result = CliRunner().invoke(app, [*argv, "--channel", INVITE])

        assert result.exit_code == 2
        assert "Invalid value for --channel" in _plain(result.output)
        service.assert_not_awaited()

    def test_backfill_content_hash(self):
        from tg_parser.cli.app import app

        run = AsyncMock(side_effect=RuntimeError("stop after capture"))
        with patch("tg_parser.cli.backfill_content_hash_cmd.run_backfill_content_hash", run):
            CliRunner().invoke(app, ["backfill-content-hash", "--channel-id", LINK])
            bad = CliRunner().invoke(app, ["backfill-content-hash", "--channel-id", INVITE])

        run.assert_awaited_once()
        assert run.await_args.kwargs["channel_id"] == CH
        assert bad.exit_code == 2
        assert "Invalid value for --channel-id" in _plain(bad.output)

    def test_workspace_remove_source(self):
        from tg_parser.cli.workspace_cmd import app as workspace_app

        remove_source = AsyncMock(return_value=True)

        @asynccontextmanager
        async def fake_repo():
            yield (MagicMock(), MagicMock())

        with (
            patch("tg_parser.cli.workspace_cmd._resolve_acting_user", AsyncMock()),
            patch("tg_parser.services.db_context.workspace_repo", fake_repo),
            patch(
                "tg_parser.services.workspace_service.WorkspaceService.remove_source",
                remove_source,
            ),
            patch("tg_parser.storage.sqlalchemy.database.Database.close_instance", AsyncMock()),
        ):
            ok = CliRunner().invoke(
                workspace_app, ["remove-source", "ws-1", "--channel", "t.me/own_channel/2"]
            )
            bad = CliRunner().invoke(workspace_app, ["remove-source", "ws-1", "--channel", INVITE])

        assert ok.exit_code == 0, ok.output
        remove_source.assert_awaited_once()
        assert remove_source.await_args.args[1:] == ("ws-1", CH)
        assert bad.exit_code == 2

    def test_topicize_rejected_link_never_runs(self):
        from tg_parser.cli.app import app

        with patch("tg_parser.cli.app._run_full_topicization") as run:
            result = CliRunner().invoke(app, ["topicize", "--channel", INVITE, "--mode", "full"])

        assert result.exit_code == 2
        run.assert_not_called()

    @staticmethod
    def _subscribe_patches(cmd: str, service: AsyncMock):
        @asynccontextmanager
        async def digest_repo():
            yield (MagicMock(), MagicMock())

        @asynccontextmanager
        async def watch_repos():
            yield (MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock())

        target = (
            "tg_parser.services.digest_service.DigestService.subscribe"
            if cmd == "digest"
            else "tg_parser.services.watchlist_service.WatchlistService.subscribe"
        )
        return (
            patch(
                f"tg_parser.cli.{cmd}_cmd._resolve_acting_user", AsyncMock(return_value=_admin())
            ),
            patch("tg_parser.services.db_context.digest_subscription_repo", digest_repo),
            patch("tg_parser.services.db_context.watchlist_repos", watch_repos),
            patch(
                "tg_parser.services.embedding_service.create_embedding_client",
                side_effect=RuntimeError("no embeddings in tests"),
            ),
            patch("tg_parser.storage.sqlalchemy.database.Database.close_instance", AsyncMock()),
            patch(target, service),
        )

    @pytest.mark.parametrize("cmd, label", [("digest", "--name"), ("watchlist", "--title")])
    def test_subscription_ids_reach_the_service_canonical(self, cmd, label):
        from tg_parser.cli.app import app

        service = AsyncMock(side_effect=RuntimeError("stop after capture"))
        p1, p2, p3, p4, p5, p6 = self._subscribe_patches(cmd, service)
        base = [cmd, "add", label, "n", "--chat-id", "1", "--channels"]
        with p1, p2, p3, p4, p5, p6:
            for channels in (
                "https://t.me/own_channel/5,kdl_ru",
                "@own_channel, kdl_ru",
                "kdl_ru,https://t.me/own_channel?single",
            ):
                CliRunner().invoke(app, [*base, channels])
            tail = CliRunner().invoke(app, [*base, "https://t.me/own_channel?x=1,2"])
            invite = CliRunner().invoke(app, [*base, INVITE])

        assert [sorted(c.kwargs["channel_ids"]) for c in service.await_args_list] == [
            sorted([CH, "kdl_ru"])
        ] * 3
        assert tail.exit_code == 2
        assert invite.exit_code == 2
        assert service.await_count == 3


# ---------------------------------------------------------------------------
# Repeat on real persistence: a link, then @username, is one row
# ---------------------------------------------------------------------------


@pg_only
class TestRepeatIsOneRowPg:
    @pytest.fixture
    async def owner(self, test_db):
        from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo

        session = test_db.ingestion_state_session()
        try:
            user = await SAUserRepo(session).create_user("df4_owner")
        finally:
            await session.close()
        return CurrentUser(
            id=user.id, name=user.name, role="user", allowed_channel_ids=[CH], max_channels=5
        )

    @staticmethod
    def _scheduler():
        return (
            patch("tg_parser.services.background_scheduler.get_scheduler", lambda: object()),
            patch(
                "tg_parser.services.background_scheduler.register_digest_subscription",
                lambda *_a, **_kw: None,
            ),
            patch(
                "tg_parser.services.background_scheduler.unregister_digest_subscription",
                lambda *_a, **_kw: None,
            ),
            patch(
                "tg_parser.services.embedding_service.create_embedding_client",
                side_effect=RuntimeError("no embeddings in tests"),
            ),
        )

    async def test_mcp_subscriptions(self, owner):
        import tg_parser.mcp_server as mcp

        s1, s2, s3, s4 = self._scheduler()
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=owner)),
            _allow_access(),
            s1,
            s2,
            s3,
            s4,
        ):
            digests = [
                await mcp.subscribe_digest(name="df4", channel_ids=[cid], chat_id=1)
                for cid in (LINK, "@own_channel")
            ]
            watches = [
                await mcp.subscribe_watchlist(
                    title="df4", channel_ids=[cid], chat_id=1, keywords=["x"]
                )
                for cid in (LINK, "@own_channel")
            ]
            digest_rows = await mcp.list_digests()
            watch_rows = await mcp.list_watchlists()

        assert [d.created for d in digests] == [True, False], [d.message for d in digests]
        assert [w.created for w in watches] == [True, False], [w.message for w in watches]
        assert digests[1].changed_fields == [] and watches[1].changed_fields == []
        assert [d.channel_ids for d in digest_rows.items] == [[CH]]
        assert [w.channel_ids for w in watch_rows.items] == [[CH]]

    async def test_mcp_workspace_source(self, owner):
        import tg_parser.mcp_server as mcp

        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=owner)),
            _no_audit(),
        ):
            added = await mcp.add_channel(LINK)
            ws = await mcp.create_workspace("df4")
            assert added.channel_id == CH and ws.workspace is not None, (added, ws)
            first = await mcp.add_workspace_source(ws.workspace.id, LINK)
            second = await mcp.add_workspace_source(ws.workspace.id, "@own_channel")
            bad = await mcp.add_workspace_source(ws.workspace.id, INVITE)
            listing = await mcp.list_workspace_sources(ws.workspace.id)
            removed = await mcp.remove_workspace_source(ws.workspace.id, "t.me/s/own_channel")
            after = await mcp.list_workspace_sources(ws.workspace.id)

        assert (first.changed, second.changed) == (True, False), (first, second)
        assert bad.success is False
        assert listing.channel_ids == [CH]
        assert removed.changed is True
        assert after.channel_ids == []

    async def test_bot_subscriptions(self, owner):
        from tg_parser.bot import tools

        s1, s2, s3, s4 = self._scheduler()
        with (
            _allow_access(),
            patch("tg_parser.bot.tools.verify_channel_exists", AsyncMock(return_value=True)),
            s1,
            s2,
            s3,
            s4,
        ):
            digests = [
                await tools._TOOL_EXECUTORS["subscribe_digest"](
                    {"name": "df4", "channel_ids": [cid], "chat_id": 1, "confirm": True},
                    current_user=owner,
                )
                for cid in (LINK, "@own_channel")
            ]
            watches = [
                await tools._TOOL_EXECUTORS["subscribe_watchlist"](
                    {
                        "title": "df4",
                        "channel_ids": [cid],
                        "chat_id": 1,
                        "keywords": ["x"],
                        "confirm": True,
                    },
                    current_user=owner,
                )
                for cid in (LINK, "@own_channel")
            ]

        assert [d.get("created") for d in digests] == [True, False], digests
        assert [w.get("created") for w in watches] == [True, False], watches
        assert digests[0]["subscription_id"] == digests[1]["subscription_id"]
        assert watches[0]["watchlist_id"] == watches[1]["watchlist_id"]
        assert digests[1]["channel_ids"] == [CH]

    async def test_http_watchlist(self, owner):
        app = create_app()
        app.dependency_overrides[resolve_current_user] = lambda: owner
        body = {"title": "df4", "chat_id": 1, "keywords": ["x"], "channel_ids": ["@own_channel"]}
        with patch(
            "tg_parser.services.embedding_service.create_embedding_client",
            side_effect=RuntimeError("no embeddings in tests"),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                first = await c.post("/api/v1/watchlists", json=body)
                body["channel_ids"] = [LINK]
                second = await c.post("/api/v1/watchlists", json=body)
                listing = await c.get("/api/v1/watchlists")

        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        assert second.json()["created"] is False
        assert second.json()["changed_fields"] == []
        assert [w["channel_ids"] for w in listing.json()["items"]] == [[CH]]
