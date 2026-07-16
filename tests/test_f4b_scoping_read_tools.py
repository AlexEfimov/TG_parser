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
        assert results.result == []
        assert results.degraded is False
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
        assert results.result == []
        assert results.degraded is False
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

    async def test_workspace_empty_passes_empty_list(self, _scope_db, user_repo_for_scope):
        """Hidden gotcha § 3: empty workspace narrows scope to ``[]`` — NOT
        silent fallback to user.allowed (which would leak unrelated channels)."""
        from tg_parser.mcp_server import AnswerResultItem, ask_question

        owner = await user_repo_for_scope.create_user("ask_empty")
        user = _make_user(owner.id, allowed=["ch_a", "ch_b"])
        ws_id = await _seed_workspace_with_channels(_scope_db, user, [], name="ask_empty_ws")

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
        assert captured["allowed_channel_ids"] == []


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

    async def test_workspace_empty_passes_empty_list(self, _scope_db, user_repo_for_scope):
        """Hidden gotcha § 3: empty workspace → ``allowed_channel_ids=[]``."""
        from tg_parser.mcp_server import list_channels

        owner = await user_repo_for_scope.create_user("listch_empty")
        user = _make_user(owner.id, allowed=["ch_lc1", "ch_lc2"])
        ws_id = await _seed_workspace_with_channels(_scope_db, user, [], name="listch_empty_ws")

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
        assert captured["allowed_channel_ids"] == []


# ---------------------------------------------------------------------------
# get_topic_details / get_document — Q4 R3 invariant
# ---------------------------------------------------------------------------


def _mock_processing_repos_with_card_and_bundle(card, bundle):
    """Patch helper mirroring ``tests/test_mcp_server._mock_processing_repos``.

    Returns the context manager that ``tg_parser.services.db_context``
    .processing_repos`` is patched to so the MCP tool sees our fixture data.
    """
    from contextlib import asynccontextmanager

    proc_repo = AsyncMock()
    topic_card_repo = AsyncMock()
    topic_bundle_repo = AsyncMock()
    db_mock = AsyncMock()

    async def get_card(tid):
        return card if (card and card.id == tid) else None

    async def get_bundle(tid):
        return bundle if (bundle and bundle.topic_id == tid) else None

    topic_card_repo.get_by_id.side_effect = get_card
    topic_bundle_repo.get_by_topic_id.side_effect = get_bundle

    @asynccontextmanager
    async def fake_repos():
        yield (proc_repo, topic_card_repo, topic_bundle_repo, db_mock)

    return fake_repos


def _mock_processing_repos_with_document(doc):
    """Same idea as the topic helper, but for ``get_document``'s
    ``proc_repo.get_by_source_ref`` call site."""
    from contextlib import asynccontextmanager

    proc_repo = AsyncMock()
    topic_card_repo = AsyncMock()
    topic_bundle_repo = AsyncMock()
    db_mock = AsyncMock()

    async def get_doc(ref):
        return doc if (doc and doc.source_ref == ref) else None

    proc_repo.get_by_source_ref.side_effect = get_doc

    @asynccontextmanager
    async def fake_repos():
        yield (proc_repo, topic_card_repo, topic_bundle_repo, db_mock)

    return fake_repos


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

    async def test_get_topic_details_returns_full_bundle_when_workspace_narrower(
        self, _scope_db, user_repo_for_scope
    ):
        """Q4 R3 happy path: bundle items must include channels OUTSIDE the
        workspace, as long as the caller can see them through their F4-A
        ``allowed_channel_ids``. Workspace narrows list/search, not get-details.

        Setup: topic spans ``ch_in`` (in workspace) + ``ch_out`` (not in
        workspace, but still owned by the user). The workspace contains only
        ``ch_in``. Asserting that ``get_topic_details(topic_id, workspace_id=ws)``
        returns BOTH bundle items, not just the in-workspace one.
        """
        from datetime import datetime

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

        owner = await user_repo_for_scope.create_user("q4r3_topic")
        await _seed_source(_scope_db, "tg:src_in", "ch_in", owner.id)
        await _seed_source(_scope_db, "tg:src_out", "ch_out", owner.id)
        user = _make_user(owner.id, allowed=["ch_in", "ch_out"])

        ws_id = await _seed_workspace_with_channels(
            _scope_db, user, ["ch_in"], name="q4r3_topic_ws"
        )

        topic_id = "topic:tg:ch_in:post:42"
        now = datetime.now(UTC)
        card = TopicCard(
            id=topic_id,
            title="cross-channel topic",
            summary="spans ch_in + ch_out",
            scope_in=["AI/ML news"],
            scope_out=["other domains"],
            type=TopicType.CLUSTER,
            anchors=[
                Anchor(
                    channel_id="ch_in",
                    message_id="42",
                    message_type=MessageType.POST,
                    anchor_ref="tg:ch_in:post:42",
                    score=1.0,
                ),
                Anchor(
                    channel_id="ch_out",
                    message_id="43",
                    message_type=MessageType.POST,
                    anchor_ref="tg:ch_out:post:43",
                    score=0.9,
                ),
            ],
            sources=["ch_in", "ch_out"],
            updated_at=now,
        )
        bundle = TopicBundle(
            topic_id=topic_id,
            items=[
                BundleItem(
                    channel_id="ch_in",
                    message_id="42",
                    message_type=MessageType.POST,
                    source_ref="tg:ch_in:post:42",
                    role=BundleItemRole.ANCHOR,
                ),
                BundleItem(
                    channel_id="ch_out",
                    message_id="43",
                    message_type=MessageType.POST,
                    source_ref="tg:ch_out:post:43",
                    role=BundleItemRole.SUPPORTING,
                ),
            ],
            updated_at=now,
        )

        fake_repos = _mock_processing_repos_with_card_and_bundle(card, bundle)
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
            patch("tg_parser.services.db_context.processing_repos", fake_repos),
            patch(
                "tg_parser.services.topic_linking_service.get_related_topics_for",
                AsyncMock(return_value=[]),
            ),
        ):
            result = await get_topic_details(topic_id=topic_id, workspace_id=ws_id)

        assert not isinstance(result, str), f"Expected TopicDetail, got string: {result}"
        assert result.id == topic_id
        assert sorted(result.sources) == ["ch_in", "ch_out"]
        assert result.items is not None
        item_channels = sorted({item["channel_id"] for item in result.items})
        assert item_channels == ["ch_in", "ch_out"]

    async def test_get_topic_details_full_bundle_equals_null_workspace(
        self, _scope_db, user_repo_for_scope
    ):
        """The bundle returned with ``workspace_id=ws`` must be **identical**
        to the one returned with ``workspace_id=None`` (Q4 R3 — no filtering
        on get-details). Documents the equivalence the start prompt requires.
        """
        from datetime import datetime

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

        owner = await user_repo_for_scope.create_user("q4r3_eq")
        await _seed_source(_scope_db, "tg:src_eqa", "ch_eqa", owner.id)
        await _seed_source(_scope_db, "tg:src_eqb", "ch_eqb", owner.id)
        user = _make_user(owner.id, allowed=["ch_eqa", "ch_eqb"])
        ws_id = await _seed_workspace_with_channels(_scope_db, user, ["ch_eqa"], name="q4r3_eq_ws")

        topic_id = "topic:tg:ch_eqa:post:1"
        now = datetime.now(UTC)
        card = TopicCard(
            id=topic_id,
            title="t",
            summary="s",
            scope_in=["focus"],
            scope_out=["unrelated"],
            type=TopicType.CLUSTER,
            anchors=[
                Anchor(
                    channel_id="ch_eqa",
                    message_id="1",
                    message_type=MessageType.POST,
                    anchor_ref="tg:ch_eqa:post:1",
                    score=1.0,
                ),
                Anchor(
                    channel_id="ch_eqb",
                    message_id="2",
                    message_type=MessageType.POST,
                    anchor_ref="tg:ch_eqb:post:2",
                    score=0.9,
                ),
            ],
            sources=["ch_eqa", "ch_eqb"],
            updated_at=now,
        )
        bundle = TopicBundle(
            topic_id=topic_id,
            items=[
                BundleItem(
                    channel_id="ch_eqa",
                    message_id="1",
                    message_type=MessageType.POST,
                    source_ref="tg:ch_eqa:post:1",
                    role=BundleItemRole.ANCHOR,
                ),
                BundleItem(
                    channel_id="ch_eqb",
                    message_id="2",
                    message_type=MessageType.POST,
                    source_ref="tg:ch_eqb:post:2",
                    role=BundleItemRole.SUPPORTING,
                ),
            ],
            updated_at=now,
        )

        fake_repos = _mock_processing_repos_with_card_and_bundle(card, bundle)
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
            patch("tg_parser.services.db_context.processing_repos", fake_repos),
            patch(
                "tg_parser.services.topic_linking_service.get_related_topics_for",
                AsyncMock(return_value=[]),
            ),
        ):
            scoped = await get_topic_details(topic_id=topic_id, workspace_id=ws_id)
            unscoped = await get_topic_details(topic_id=topic_id, workspace_id=None)

        assert not isinstance(scoped, str)
        assert not isinstance(unscoped, str)
        assert scoped.items == unscoped.items
        assert scoped.sources == unscoped.sources
        assert scoped.id == unscoped.id

    async def test_get_document_returns_doc_when_channel_outside_workspace(
        self, _scope_db, user_repo_for_scope
    ):
        """Q4 R3 for ``get_document``: returns the document even if its
        ``channel_id`` lives outside the workspace, provided the caller has
        F4-A access to that channel.
        """
        from tg_parser.domain.models import ProcessedDocument
        from tg_parser.mcp_server import get_document

        owner = await user_repo_for_scope.create_user("q4r3_doc")
        await _seed_source(_scope_db, "tg:src_doc_in", "ch_doc_in", owner.id)
        await _seed_source(_scope_db, "tg:src_doc_out", "ch_doc_out", owner.id)
        user = _make_user(owner.id, allowed=["ch_doc_in", "ch_doc_out"])
        ws_id = await _seed_workspace_with_channels(
            _scope_db, user, ["ch_doc_in"], name="q4r3_doc_ws"
        )

        doc = ProcessedDocument(
            id="d-out",
            source_ref="tg:ch_doc_out:post:7",
            source_message_id="7",
            channel_id="ch_doc_out",
            processed_at=datetime.now(UTC),
            text_clean="hello",
            summary="s",
            topics=["topic-x"],
        )
        fake_repos = _mock_processing_repos_with_document(doc)
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
            patch("tg_parser.services.db_context.processing_repos", fake_repos),
        ):
            result = await get_document(
                source_ref="tg:ch_doc_out:post:7",
                workspace_id=ws_id,
            )

        assert not isinstance(result, str), f"Expected DocumentDetail, got string: {result}"
        assert result.channel_id == "ch_doc_out"
        assert result.source_ref == "tg:ch_doc_out:post:7"


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

    async def test_get_cross_channel_stats_workspace_unknown_returns_empty(
        self, _scope_db, user_repo_for_scope
    ):
        """404 path for ``get_cross_channel_stats`` — analytics service must
        NOT be called when the workspace_id is unknown / foreign."""
        from tg_parser.mcp_server import get_cross_channel_stats

        owner = await user_repo_for_scope.create_user("cc_unk")
        user = _make_user(owner.id, allowed=["ch_cc"])
        analytics_mock = AsyncMock()
        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
            patch(
                "tg_parser.services.analytics_service.get_cross_channel_analytics",
                analytics_mock,
            ),
        ):
            result = await get_cross_channel_stats(
                workspace_id="00000000-0000-0000-0000-000000000999"
            )
        assert result.total_documents == 0
        assert result.channels == []
        analytics_mock.assert_not_called()

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

    async def test_get_related_topics_workspace_narrows(self, _scope_db, user_repo_for_scope):
        """``get_related_topics`` must pass the workspace-narrowed
        ``allowed_channel_ids`` to the linking service (intersection path)."""
        from tg_parser.mcp_server import get_related_topics

        owner = await user_repo_for_scope.create_user("rel_narrow")
        await _seed_source(_scope_db, "tg:src_rn", "ch_rn", owner.id)
        user = _make_user(owner.id, allowed=["ch_rn", "ch_other"])
        ws_id = await _seed_workspace_with_channels(
            _scope_db, user, ["ch_rn"], name="rel_narrow_ws"
        )

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
            await get_related_topics(topic_id="topic:tg:rn", workspace_id=ws_id)
        assert captured["allowed_channel_ids"] == ["ch_rn"]


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

    async def test_workspace_narrows_to_intersection(self, _scope_db, user_repo_for_scope):
        """``list_topics`` must call ``topic_card_repo.list_by_channels`` with
        the workspace-narrowed list (not user's full ``allowed_channel_ids``)."""
        from contextlib import asynccontextmanager

        from tg_parser.mcp_server import list_topics

        owner = await user_repo_for_scope.create_user("lt_narrow")
        await _seed_source(_scope_db, "tg:src_lt", "ch_lt", owner.id)
        user = _make_user(owner.id, allowed=["ch_lt", "ch_other"])
        ws_id = await _seed_workspace_with_channels(_scope_db, user, ["ch_lt"], name="lt_narrow_ws")

        topic_card_repo = AsyncMock()
        topic_bundle_repo = AsyncMock()
        proc_repo = AsyncMock()
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
            result = await list_topics(workspace_id=ws_id)
        assert result.total == 0
        assert captured["channel_ids"] == ["ch_lt"]

    async def test_q6_cross_channel_topic_visible_via_any_workspace(
        self, _scope_db, user_repo_for_scope
    ):
        """Q6 — topic spanning ch_a + ch_b is visible through whichever
        workspace contains either of them, **and** through null-workspace.

        Mirrors F4-A ``assert_topic_access`` "any source" semantics.
        Critical: F4-B must NOT post-filter the cards returned by
        ``topic_card_repo.list_by_channels`` — that would shrink cross-channel
        topics out of every workspace that doesn't contain *all* their sources.
        """
        from contextlib import asynccontextmanager
        from datetime import datetime

        from tg_parser.domain.models import (
            Anchor,
            MessageType,
            TopicCard,
            TopicType,
        )
        from tg_parser.mcp_server import list_topics

        owner = await user_repo_for_scope.create_user("q6_any_source")
        await _seed_source(_scope_db, "tg:src_qa", "ch_qa", owner.id)
        await _seed_source(_scope_db, "tg:src_qb", "ch_qb", owner.id)
        user = _make_user(owner.id, allowed=["ch_qa", "ch_qb"])
        ws_a = await _seed_workspace_with_channels(_scope_db, user, ["ch_qa"], name="q6_ws_a")
        ws_b = await _seed_workspace_with_channels(_scope_db, user, ["ch_qb"], name="q6_ws_b")

        now = datetime.now(UTC)
        cross_card = TopicCard(
            id="topic:tg:qa_qb",
            title="cross-channel",
            summary="spans ch_qa + ch_qb",
            scope_in=["theme"],
            scope_out=["other"],
            type=TopicType.CLUSTER,
            anchors=[
                Anchor(
                    channel_id="ch_qa",
                    message_id="1",
                    message_type=MessageType.POST,
                    anchor_ref="tg:ch_qa:post:1",
                    score=1.0,
                ),
                Anchor(
                    channel_id="ch_qb",
                    message_id="2",
                    message_type=MessageType.POST,
                    anchor_ref="tg:ch_qb:post:2",
                    score=0.9,
                ),
            ],
            sources=["ch_qa", "ch_qb"],
            updated_at=now,
        )

        topic_card_repo = AsyncMock()
        topic_bundle_repo = AsyncMock()
        proc_repo = AsyncMock()
        topic_bundle_repo.list_all.return_value = []

        async def fake_list_by_channels(channel_ids):
            # Stand-in for the F4-A any-source semantics: card is visible
            # if ANY of its sources is in the queried channel list.
            if any(src in channel_ids for src in cross_card.sources):
                return [cross_card]
            return []

        topic_card_repo.list_by_channels.side_effect = fake_list_by_channels
        topic_card_repo.list_all.return_value = [cross_card]

        @asynccontextmanager
        async def fake_repos():
            yield (proc_repo, topic_card_repo, topic_bundle_repo, AsyncMock())

        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
            patch("tg_parser.services.db_context.processing_repos", fake_repos),
        ):
            result_a = await list_topics(workspace_id=ws_a)
            result_b = await list_topics(workspace_id=ws_b)
            result_null = await list_topics(workspace_id=None)

        for label, result in (("ws_a", result_a), ("ws_b", result_b), ("null", result_null)):
            assert result.total == 1, f"{label}: expected 1 topic, got {result.total}"
            assert result.items[0].id == cross_card.id
            # CRITICAL: the surface must NOT filter sources down to the workspace.
            assert sorted(result.items[0].sources) == ["ch_qa", "ch_qb"], (
                f"{label}: sources were post-filtered, breaking Q6 any-source mirror"
            )

    async def test_workspace_empty_returns_empty_page_without_repo_call(
        self, _scope_db, user_repo_for_scope
    ):
        """Hidden gotcha § 3: empty workspace must NOT silently widen to
        all-channels. ``effective=[]`` flows into ``list_by_channels([])``
        and the result is empty.
        """
        from contextlib import asynccontextmanager

        from tg_parser.mcp_server import list_topics

        owner = await user_repo_for_scope.create_user("lt_empty")
        user = _make_user(owner.id, allowed=["ch_a", "ch_b"])
        ws_id = await _seed_workspace_with_channels(_scope_db, user, [], name="lt_empty_ws")

        topic_card_repo = AsyncMock()
        topic_bundle_repo = AsyncMock()
        proc_repo = AsyncMock()
        captured: dict = {}

        async def fake_list_by_channels(channel_ids):
            captured["channel_ids"] = channel_ids
            return []

        topic_card_repo.list_by_channels.side_effect = fake_list_by_channels
        topic_bundle_repo.list_all.return_value = []

        @asynccontextmanager
        async def fake_repos():
            yield (proc_repo, topic_card_repo, topic_bundle_repo, AsyncMock())

        with (
            patch("tg_parser.mcp_server.resolve_mcp_user", AsyncMock(return_value=user)),
            patch("tg_parser.services.db_context.processing_repos", fake_repos),
        ):
            result = await list_topics(workspace_id=ws_id)
        assert result.total == 0
        # Critical: explicit empty narrowing, NOT list_all() path.
        topic_card_repo.list_all.assert_not_called()
        assert captured["channel_ids"] == []
