"""F4-B Core — Phase 4 scoping integration in read MCP/CLI tools.

These tests pin the contract from § "Read tools" of
``docs/notes/START_PROMPT_SPRINT_F4B_CORE_2026-05-13.md``:

* ``workspace_id=None`` → bit-for-bit F4-A behaviour (regression guard).
* unknown / foreign ``workspace_id`` → 404-like empty response (no leak).
* empty workspace → empty result list.
* valid workspace → ``allowed_channel_ids`` narrowed to intersection.
* ``get_topic_details`` / ``get_document`` honour Q4 R3 — return FULL bundle
  items regardless of workspace scope but still 404 on unknown / foreign
  workspace_id.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from tg_parser.auth.models import CurrentUser
from tg_parser.storage.ports import Source
from tg_parser.storage.sqlalchemy.ingestion_state_repo import SAIngestionStateRepo
from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


def _make_user(
    user_id: str,
    *,
    name: str = "alice",
    role: str = "user",
    allowed: list[str] | None = None,
    max_channels: int = 10,
) -> CurrentUser:
    return CurrentUser(
        id=user_id,
        name=name,
        role=role,
        allowed_channel_ids=None if role == "admin" else (allowed or []),
        max_channels=max_channels,
    )


@pytest.fixture
async def _scope_db(test_db):
    return test_db


@pytest.fixture
async def user_repo_for_scope(_scope_db):
    session = _scope_db.ingestion_state_session()
    try:
        yield SAUserRepo(session)
    finally:
        await session.close()


async def _seed_source(test_db, source_id: str, channel_id: str, owner_id: str) -> None:
    session = test_db.ingestion_state_session()
    try:
        repo = SAIngestionStateRepo(session)
        await repo.upsert_source(
            Source(
                source_id=source_id,
                channel_id=channel_id,
                status="active",
                include_comments=False,
                fail_count=0,
                comments_unavailable=False,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                owner_id=owner_id,
            )
        )
    finally:
        await session.close()


async def _seed_workspace_with_channels(
    db,
    owner: CurrentUser,
    channels: list[str],
    *,
    name: str = "ws",
) -> str:
    """Create a workspace and add the given channels via the service layer."""
    from tg_parser.services.db_context import workspace_repo
    from tg_parser.services.workspace_service import WorkspaceService

    async with workspace_repo() as (repo, _db):
        svc = WorkspaceService(repo)
        ws = await svc.create_workspace(owner, name=name, description=None)
        for ch in channels:
            await svc.add_source(owner, ws.id, ch)
        return ws.id


# ---------------------------------------------------------------------------
# search_knowledge_base
# ---------------------------------------------------------------------------


@pg_only
class TestSearchKnowledgeBaseScoping:
    async def test_workspace_none_uses_user_allowed_channels(self, _scope_db, user_repo_for_scope):
        """workspace_id=None must pass user.allowed_channel_ids unchanged (F4-A parity)."""
        from tg_parser.mcp_server import search_knowledge_base

        owner = await user_repo_for_scope.create_user("search_none")
        user = _make_user(owner.id, allowed=["ch_a", "ch_b"])

        captured: dict = {}

        async def fake_search(**kwargs):
            captured.update(kwargs)
            return []

        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
            patch(
                "tg_parser.services.retrieval_service.search", AsyncMock(side_effect=fake_search)
            ),
        ):
            await search_knowledge_base(query="hello")
        assert captured["allowed_channel_ids"] == ["ch_a", "ch_b"]

    async def test_workspace_unknown_returns_empty_no_service_call(
        self, _scope_db, user_repo_for_scope
    ):
        """Unknown workspace_id must short-circuit to ``[]`` and never reach search()."""
        from tg_parser.mcp_server import search_knowledge_base

        owner = await user_repo_for_scope.create_user("search_unk")
        user = _make_user(owner.id, allowed=["ch_a"])
        search_mock = AsyncMock()

        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
            patch("tg_parser.services.retrieval_service.search", search_mock),
        ):
            results = await search_knowledge_base(
                query="hi",
                workspace_id="00000000-0000-0000-0000-000000000999",
            )
        assert results == []
        search_mock.assert_not_called()

    async def test_workspace_foreign_returns_empty(self, _scope_db, user_repo_for_scope):
        """Foreign workspace_id must look like 404 (no leak)."""
        from tg_parser.mcp_server import search_knowledge_base

        alice = await user_repo_for_scope.create_user("alice_search_fg")
        bob = await user_repo_for_scope.create_user("bob_search_fg")
        alice_user = _make_user(alice.id, allowed=["ch_a"])
        bob_user = _make_user(bob.id, allowed=["ch_a"])
        await _seed_source(_scope_db, "tg:src_fg", "ch_a", alice.id)

        ws_id = await _seed_workspace_with_channels(
            _scope_db, alice_user, ["ch_a"], name="alice_search_fg_ws"
        )

        search_mock = AsyncMock()
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=bob_user)),
            patch("tg_parser.services.retrieval_service.search", search_mock),
        ):
            results = await search_knowledge_base(query="hi", workspace_id=ws_id)
        assert results == []
        search_mock.assert_not_called()

    async def test_workspace_empty_passes_empty_list(self, _scope_db, user_repo_for_scope):
        """Empty workspace narrows scope to ``[]`` (explicit, not None)."""
        from tg_parser.mcp_server import search_knowledge_base

        owner = await user_repo_for_scope.create_user("search_empty")
        user = _make_user(owner.id, allowed=["ch_a", "ch_b"])
        ws_id = await _seed_workspace_with_channels(_scope_db, user, [], name="empty_ws")

        captured: dict = {}

        async def fake_search(**kwargs):
            captured.update(kwargs)
            return []

        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
            patch(
                "tg_parser.services.retrieval_service.search", AsyncMock(side_effect=fake_search)
            ),
        ):
            await search_knowledge_base(query="hi", workspace_id=ws_id)
        assert captured["allowed_channel_ids"] == []

    async def test_workspace_narrows_to_intersection(self, _scope_db, user_repo_for_scope):
        """Non-admin: effective = user.allowed ∩ workspace.channel_ids."""
        from tg_parser.mcp_server import search_knowledge_base

        owner = await user_repo_for_scope.create_user("search_intersect")
        await _seed_source(_scope_db, "tg:src_a", "ch_a", owner.id)
        await _seed_source(_scope_db, "tg:src_b", "ch_b", owner.id)
        user = _make_user(owner.id, allowed=["ch_a", "ch_b", "ch_c"])
        ws_id = await _seed_workspace_with_channels(
            _scope_db, user, ["ch_a", "ch_b"], name="intersect_ws"
        )

        captured: dict = {}

        async def fake_search(**kwargs):
            captured.update(kwargs)
            return []

        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
            patch(
                "tg_parser.services.retrieval_service.search", AsyncMock(side_effect=fake_search)
            ),
        ):
            await search_knowledge_base(query="hi", workspace_id=ws_id)
        assert sorted(captured["allowed_channel_ids"]) == ["ch_a", "ch_b"]


# ---------------------------------------------------------------------------
# ask_question
# ---------------------------------------------------------------------------


@pg_only
class TestAskQuestionScoping:
    async def test_workspace_unknown_returns_benign_answer(self, _scope_db, user_repo_for_scope):
        from tg_parser.mcp_server import ask_question

        owner = await user_repo_for_scope.create_user("ask_unk")
        user = _make_user(owner.id, allowed=["ch_a"])
        answer_mock = AsyncMock()
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
            patch("tg_parser.services.retrieval_service.answer", answer_mock),
        ):
            res = await ask_question(
                question="anything?",
                workspace_id="00000000-0000-0000-0000-000000000999",
            )
        assert "not found" in res.answer.lower()
        assert res.sources == []
        answer_mock.assert_not_called()

    async def test_workspace_narrows_retrieval(self, _scope_db, user_repo_for_scope):
        from tg_parser.mcp_server import AnswerResultItem, ask_question

        owner = await user_repo_for_scope.create_user("ask_narrow")
        await _seed_source(_scope_db, "tg:src_ax", "ch_ax", owner.id)
        user = _make_user(owner.id, allowed=["ch_ax", "ch_other"])
        ws_id = await _seed_workspace_with_channels(
            _scope_db, user, ["ch_ax"], name="ask_narrow_ws"
        )

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
            await ask_question(question="hi", workspace_id=ws_id)
        assert captured["allowed_channel_ids"] == ["ch_ax"]


# ---------------------------------------------------------------------------
# list_channels
# ---------------------------------------------------------------------------


@pg_only
class TestListChannelsScoping:
    async def test_workspace_narrows_channel_list(self, _scope_db, user_repo_for_scope):
        from tg_parser.mcp_server import list_channels

        owner = await user_repo_for_scope.create_user("listch_narrow")
        await _seed_source(_scope_db, "tg:src_lc1", "ch_lc1", owner.id)
        await _seed_source(_scope_db, "tg:src_lc2", "ch_lc2", owner.id)
        user = _make_user(owner.id, allowed=["ch_lc1", "ch_lc2"])
        ws_id = await _seed_workspace_with_channels(
            _scope_db, user, ["ch_lc1"], name="listch_narrow_ws"
        )

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
            await list_channels(workspace_id=ws_id)
        assert captured["allowed_channel_ids"] == ["ch_lc1"]

    async def test_workspace_unknown_returns_empty(self, _scope_db, user_repo_for_scope):
        from tg_parser.mcp_server import list_channels

        owner = await user_repo_for_scope.create_user("listch_unk")
        user = _make_user(owner.id, allowed=["ch_lc1"])
        stats_mock = AsyncMock()
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
            patch(
                "tg_parser.services.channel_service.get_all_channel_stats",
                stats_mock,
            ),
        ):
            results = await list_channels(workspace_id="00000000-0000-0000-0000-000000000999")
        assert results == []
        stats_mock.assert_not_called()


# ---------------------------------------------------------------------------
# get_topic_details / get_document — Q4 R3 invariant
# ---------------------------------------------------------------------------


@pg_only
class TestGetDetailsHonorsQ4R3:
    async def test_get_topic_details_unknown_workspace_returns_not_found(
        self, _scope_db, user_repo_for_scope
    ):
        from tg_parser.mcp_server import get_topic_details

        owner = await user_repo_for_scope.create_user("getdet_unk")
        user = _make_user(owner.id, allowed=[])
        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)):
            result = await get_topic_details(
                topic_id="topic:tg:irrelevant",
                workspace_id="00000000-0000-0000-0000-000000000999",
            )
        assert isinstance(result, str)
        assert "not found" in result.lower()

    async def test_get_document_unknown_workspace_returns_not_found(
        self, _scope_db, user_repo_for_scope
    ):
        from tg_parser.mcp_server import get_document

        owner = await user_repo_for_scope.create_user("getdoc_unk")
        user = _make_user(owner.id, allowed=[])
        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)):
            result = await get_document(
                source_ref="tg:ch:post:1",
                workspace_id="00000000-0000-0000-0000-000000000999",
            )
        assert isinstance(result, str)
        assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# Cross-channel + related — narrow scope
# ---------------------------------------------------------------------------


@pg_only
class TestAnalyticsScoping:
    async def test_get_cross_channel_stats_workspace_narrows(self, _scope_db, user_repo_for_scope):
        from tg_parser.mcp_server import get_cross_channel_stats

        owner = await user_repo_for_scope.create_user("cc_narrow")
        await _seed_source(_scope_db, "tg:src_cc", "ch_cc", owner.id)
        user = _make_user(owner.id, allowed=["ch_cc"])
        ws_id = await _seed_workspace_with_channels(_scope_db, user, ["ch_cc"], name="cc_narrow_ws")

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
            await get_cross_channel_stats(workspace_id=ws_id)
        assert captured["allowed_channel_ids"] == ["ch_cc"]

    async def test_get_related_topics_workspace_unknown_returns_empty(
        self, _scope_db, user_repo_for_scope
    ):
        from tg_parser.mcp_server import get_related_topics

        owner = await user_repo_for_scope.create_user("rel_unk")
        user = _make_user(owner.id, allowed=["ch_a"])
        linker = AsyncMock()
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
            patch(
                "tg_parser.services.topic_linking_service.get_related_topics_for",
                linker,
            ),
        ):
            results = await get_related_topics(
                topic_id="topic:tg:irrelevant",
                workspace_id="00000000-0000-0000-0000-000000000999",
            )
        assert results == []
        linker.assert_not_called()


# ---------------------------------------------------------------------------
# list_topics
# ---------------------------------------------------------------------------


@pg_only
class TestListTopicsScoping:
    async def test_workspace_unknown_returns_empty_page(self, _scope_db, user_repo_for_scope):
        from tg_parser.mcp_server import list_topics

        owner = await user_repo_for_scope.create_user("lt_unk")
        user = _make_user(owner.id, allowed=["ch_a"])
        with patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)):
            result = await list_topics(workspace_id="00000000-0000-0000-0000-000000000999")
        assert result.total == 0
        assert result.items == []
