"""
BUG-107 — a soft-deleted channel is invisible everywhere, admin included,
except on the restore path (re-adding it with ``add_channel``).

Class of test: "what must NOT happen" (BUG-093 / BUG-100 precedent). Every
case runs against real Postgres with real repositories, and the caller is
resolved through the production resolvers — ``resolve_mcp_user`` for MCP,
``resolve_user_by_auth`` for the bot and the HTTP API — because that is where
the leak lived: the admin scope was ``None`` ("every channel") and the owner's
scope still listed the removed channel.

World: ``LIVE`` and ``DEAD`` belong to the owner, ``OTHER`` to the admin;
``DEAD`` is soft-deleted. Every channel has one document, one topic card and
one embedding of each; the only live-to-dead topic link exists in advance.
All content shares ``QUERY``; only ``DEAD`` content carries ``MARK``.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from tg_parser.auth.resolvers import clear_cache, resolve_user_by_auth
from tg_parser.domain.ids import make_processed_document_id, make_source_ref
from tg_parser.domain.models import (
    Anchor,
    DigestSubscription,
    MessageType,
    NotifyMode,
    ProcessedDocument,
    TopicCard,
    TopicLink,
    TopicType,
    WatchInterest,
    WatchMatch,
)
from tg_parser.storage.ports import Source
from tg_parser.storage.sqlalchemy.embedding_repo import SAEmbeddingRepo
from tg_parser.storage.sqlalchemy.ingestion_state_repo import SAIngestionStateRepo
from tg_parser.storage.sqlalchemy.processed_document_repo import SAProcessedDocumentRepo
from tg_parser.storage.sqlalchemy.topic_card_repo import SATopicCardRepo
from tg_parser.storage.sqlalchemy.topic_link_repo import SATopicLinkRepo
from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)

LIVE = "bug107_live"
DEAD = "bug107_dead"
OTHER = "bug107_other"
QUERY = "zebrafish"
MARK = "necrozebra"

ADMIN_TG = "107001"
OWNER_TG = "107002"


def _ref(channel_id: str) -> str:
    return make_source_ref(channel_id, "post", "1")


def _topic(channel_id: str) -> str:
    return f"topic:{_ref(channel_id)}"


DEAD_REF = _ref(DEAD)
DEAD_TOPIC = _topic(DEAD)
LIVE_REF = _ref(LIVE)
LIVE_TOPIC = _topic(LIVE)
OTHER_TOPIC = _topic(OTHER)

VEC = [1.0] + [0.0] * 1535
NOW = datetime.now(UTC)


def _text(obj: Any) -> str:
    if isinstance(obj, BaseModel):
        return obj.model_dump_json()
    if isinstance(obj, list):
        return "[" + ",".join(_text(o) for o in obj) + "]"
    if isinstance(obj, dict):
        return json.dumps(obj, default=str, ensure_ascii=False)
    return str(obj)


def assert_no_dead(obj: Any) -> str:
    text = _text(obj)
    assert MARK not in text, f"deleted channel content leaked: {text[:500]}"
    assert DEAD_REF not in text, f"deleted channel document leaked: {text[:500]}"
    assert DEAD_TOPIC not in text, f"deleted channel topic leaked: {text[:500]}"
    return text


def _source(channel_id: str, owner_id: str) -> Source:
    return Source(
        source_id=channel_id,
        channel_id=channel_id,
        status="active",
        include_comments=False,
        fail_count=0,
        comments_unavailable=False,
        created_at=NOW,
        updated_at=NOW,
        owner_id=owner_id,
    )


def _card(channel_id: str) -> TopicCard:
    mark = f" {MARK}" if channel_id == DEAD else ""
    return TopicCard(
        id=_topic(channel_id),
        title=f"{QUERY} biology{mark}",
        summary=f"{QUERY} research in {channel_id}{mark}",
        scope_in=[QUERY, "biology"],
        scope_out=["finance"],
        type=TopicType.SINGLETON,
        anchors=[
            Anchor(
                channel_id=channel_id,
                message_id="1",
                message_type=MessageType.POST,
                anchor_ref=_ref(channel_id),
                score=1.0,
            )
        ],
        sources=[channel_id],
        updated_at=NOW,
        last_summarized_at=NOW - timedelta(hours=1),
        new_items_since_last_summary=5,
    )


@pytest.fixture
async def world(test_db):
    session = test_db.ingestion_state_session()
    try:
        users = SAUserRepo(session)
        admin = await users.create_user("bug107_admin", role="admin")
        owner = await users.create_user("bug107_owner", role="user", max_channels=2)
        await users.add_auth_mapping(admin.id, "telegram", ADMIN_TG)
        await users.add_auth_mapping(owner.id, "telegram", OWNER_TG)
        state = SAIngestionStateRepo(session)
        for channel_id, owner_id in ((LIVE, owner.id), (DEAD, owner.id), (OTHER, admin.id)):
            await state.upsert_source(_source(channel_id, owner_id))
        assert await state.delete_source(DEAD)
    finally:
        await session.close()

    psession = test_db.processing_storage_session()
    try:
        docs = SAProcessedDocumentRepo(psession)
        embeddings = SAEmbeddingRepo(psession)
        cards = SATopicCardRepo(psession)
        for channel_id in (LIVE, DEAD, OTHER):
            mark = f" {MARK}" if channel_id == DEAD else ""
            ref = _ref(channel_id)
            await docs.upsert(
                ProcessedDocument(
                    id=make_processed_document_id(ref),
                    source_ref=ref,
                    source_message_id="1",
                    channel_id=channel_id,
                    processed_at=NOW - timedelta(hours=1),
                    text_clean=f"{QUERY} research note from {channel_id}{mark}",
                    summary=f"{QUERY} note{mark}",
                )
            )
            await embeddings.save(ref, VEC, "test", entry_type="message", channel_ids=[channel_id])
            card = _card(channel_id)
            await cards.upsert(card)
            await embeddings.save(
                card.id, VEC, "test", entry_type="topic", topic_id=card.id, channel_ids=[channel_id]
            )
        await SATopicLinkRepo(psession).upsert(
            TopicLink(
                topic_id_a=LIVE_TOPIC,
                topic_id_b=DEAD_TOPIC,
                similarity_score=0.9,
                shared_keywords=[QUERY],
                created_at=NOW,
            )
        )
    finally:
        await psession.close()

    clear_cache()
    try:
        yield {"admin": admin.id, "owner": owner.id, "db": test_db}
    finally:
        clear_cache()


WHO = ["admin", "owner"]


def _tg(who: str) -> str:
    return ADMIN_TG if who == "admin" else OWNER_TG


async def _bot_user(who: str):
    user = await resolve_user_by_auth("telegram", _tg(who))
    assert user is not None
    return user


def _as_mcp(world: dict, who: str):
    return patch("tg_parser.mcp_server._extract_authenticated_user_id", return_value=world[who])


def _stub_query_embedding():
    client = MagicMock()
    client.embed = AsyncMock(return_value=[VEC])
    return patch("tg_parser.services.retrieval_service.get_embedding_client", return_value=client)


def _stub_rag_llm():
    return patch(
        "tg_parser.services.retrieval_service._call_llm",
        AsyncMock(return_value=("answer", "test-model")),
    )


def _forbid_dispatch():
    """Export and pipeline dispatch must never be reached for a deleted channel."""
    boom = AsyncMock(side_effect=AssertionError("dispatch reached for a deleted channel"))
    return (
        patch("tg_parser.services.pipeline_dispatch_client.post_export", boom),
        patch("tg_parser.services.pipeline_dispatch_client.post_pipeline_trigger", boom),
    )


# ---------------------------------------------------------------------------
# Scope and ownership counters (DF-5)
# ---------------------------------------------------------------------------


class TestScope:
    @pytest.mark.parametrize("who", WHO)
    async def test_resolved_scope_excludes_deleted_channel(self, world, who):
        from tg_parser.mcp_server import resolve_mcp_user

        mcp_user = await resolve_mcp_user(world[who])
        bot_user = await _bot_user(who)
        expected = [LIVE, OTHER] if who == "admin" else [LIVE]
        assert mcp_user.allowed_channel_ids == expected
        assert bot_user.allowed_channel_ids == expected

    async def test_owned_channel_ids_exclude_deleted(self, world):
        session = world["db"].ingestion_state_session()
        try:
            repo = SAUserRepo(session)
            assert await repo.get_owned_channel_ids(world["owner"]) == [LIVE]
            assert await repo.get_live_channel_ids() == [LIVE, OTHER]
        finally:
            await session.close()

    async def test_whoami_and_list_users_count_live_channels_only(self, world):
        from tg_parser.bot.tools import _exec_list_users, _exec_whoami
        from tg_parser.mcp_server import list_users, whoami

        with _as_mcp(world, "owner"):
            me = await whoami()
        assert me.owned_channels == [LIVE]
        assert me.owned_channels_count == 1

        bot_me = await _exec_whoami({}, current_user=await _bot_user("owner"))
        assert DEAD not in _text(bot_me)

        with _as_mcp(world, "admin"):
            listed = await list_users()
        counts = {u.name: u.owned_channels_count for u in listed.users}
        assert counts["bug107_owner"] == 1

        bot_listed = await _exec_list_users({}, current_user=await _bot_user("admin"))
        assert DEAD not in _text(bot_listed)


# ---------------------------------------------------------------------------
# Search and RAG — all three retrieval modes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("who", WHO)
@pytest.mark.parametrize("mode", ["semantic", "keyword", "hybrid"])
class TestSearchAndRag:
    async def test_mcp_search(self, world, who, mode):
        from tg_parser.mcp_server import search_knowledge_base

        with _as_mcp(world, who), _stub_query_embedding():
            results = await search_knowledge_base(query=QUERY, mode=mode, limit=20)
        text = assert_no_dead(results)
        assert LIVE_REF in text or LIVE_TOPIC in text

    async def test_mcp_search_explicit_deleted_channel(self, world, who, mode):
        from tg_parser.mcp_server import search_knowledge_base

        with _as_mcp(world, who), _stub_query_embedding():
            try:
                results = await search_knowledge_base(
                    query=QUERY, channel_id=DEAD, mode=mode, limit=20
                )
            except Exception as exc:  # denial form is the tool's own
                results = str(exc)
        assert_no_dead(results)

    async def test_mcp_ask_question(self, world, who, mode):
        from tg_parser.mcp_server import ask_question

        with _as_mcp(world, who), _stub_query_embedding(), _stub_rag_llm() as llm:
            answer = await ask_question(question=QUERY, mode=mode)
        assert_no_dead(answer)
        for call in llm.await_args_list:
            assert MARK not in call.args[0], "deleted content reached the RAG prompt"

    async def test_bot_search(self, world, who, mode):
        from tg_parser.bot.tools import _exec_search

        with _stub_query_embedding():
            result = await _exec_search(
                {"query": QUERY, "mode": mode, "limit": 20}, current_user=await _bot_user(who)
            )
        text = assert_no_dead(result)
        assert LIVE_REF in text or LIVE_TOPIC in text

    async def test_bot_ask_question(self, world, who, mode):
        from tg_parser.bot.tools import _exec_ask_question

        with _stub_query_embedding(), _stub_rag_llm() as llm:
            result = await _exec_ask_question(
                {"question": QUERY, "mode": mode}, current_user=await _bot_user(who)
            )
        assert_no_dead(result)
        for call in llm.await_args_list:
            assert MARK not in call.args[0]

    async def test_http_search_and_ask(self, world, who, mode):
        from tg_parser.api.auth import resolve_current_user
        from tg_parser.api.main import create_app

        user = await _bot_user(who)
        app = create_app()
        app.dependency_overrides[resolve_current_user] = lambda: user
        with _stub_query_embedding(), _stub_rag_llm():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                search = await c.post("/api/v1/search", json={"query": QUERY, "mode": mode})
                ask = await c.post("/api/v1/ask", json={"question": QUERY, "mode": mode})
        assert search.status_code == 200, search.text
        assert LIVE_REF in assert_no_dead(search.text) or LIVE_TOPIC in search.text
        assert ask.status_code == 200, ask.text
        assert_no_dead(ask.text)


# ---------------------------------------------------------------------------
# Navigation, analytics, explicit ids
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("who", WHO)
class TestMcpSurfaces:
    async def test_list_topics(self, world, who):
        from tg_parser.mcp_server import list_topics

        with _as_mcp(world, who):
            everything = await list_topics(limit=100)
            explicit = await list_topics(channel_id=DEAD, limit=100)
        assert LIVE_TOPIC in assert_no_dead(everything)
        assert explicit.total == 0
        assert_no_dead(explicit)

    async def test_topic_details_versions_document(self, world, who):
        from tg_parser.mcp_server import get_document, get_topic_details, get_topic_versions

        with _as_mcp(world, who):
            details = await get_topic_details(topic_id=DEAD_TOPIC)
            versions = await get_topic_versions(topic_id=DEAD_TOPIC)
            document = await get_document(source_ref=DEAD_REF)
        for result in (details, versions, document):
            assert MARK not in _text(result)
        assert not isinstance(details, BaseModel)
        assert not isinstance(document, BaseModel)

    async def test_related_topics(self, world, who):
        from tg_parser.mcp_server import get_related_topics

        with _as_mcp(world, who):
            related = await get_related_topics(topic_id=LIVE_TOPIC)
            from_dead = await get_related_topics(topic_id=DEAD_TOPIC)
        assert_no_dead(related)
        assert from_dead == [], "a deleted topic must not expose its links"

    async def test_force_resummarize_is_refused(self, world, who):
        from tg_parser.mcp_server import force_resummarize

        boom = AsyncMock(side_effect=AssertionError("resummarize reached a deleted topic"))
        with (
            _as_mcp(world, who),
            patch(
                "tg_parser.services.resummarization_service.ResummarizationService.resummarize_topic",
                boom,
            ),
        ):
            result = await force_resummarize(topic_id=DEAD_TOPIC)
        assert "error" in result
        assert MARK not in _text(result)

    async def test_cross_channel_stats_and_list_channels(self, world, who):
        from tg_parser.mcp_server import get_cross_channel_stats, list_channels

        with _as_mcp(world, who):
            stats = await get_cross_channel_stats()
            single = await get_cross_channel_stats(channel_id=DEAD)
            channels = await list_channels()
        for result in (stats, channels):
            assert DEAD not in _text(result)
        assert MARK not in _text(single)

    @pytest.mark.parametrize("level", ["raw", "processed", "full"])
    async def test_export_is_refused(self, world, who, level):
        from tg_parser.mcp_server import export_channel

        export_patch, _trigger_patch = _forbid_dispatch()
        with _as_mcp(world, who), export_patch:
            try:
                result = await export_channel(channel_id=DEAD, level=level)
            except Exception as exc:  # PermissionDenied surfaced as a tool error
                result = str(exc)
        assert "No access" in _text(result)

    async def test_trigger_pipeline_is_refused(self, world, who):
        from tg_parser.mcp_server import trigger_pipeline

        _export_patch, trigger_patch = _forbid_dispatch()
        with _as_mcp(world, who), trigger_patch:
            result = await trigger_pipeline(channel_id=DEAD)
        assert result.triggered is False
        assert result.error_class == "PermissionDenied"


@pytest.mark.parametrize("who", WHO)
class TestBotSurfaces:
    async def test_navigation(self, world, who):
        from tg_parser.bot.tools import (
            _exec_get_cross_channel_stats,
            _exec_get_document,
            _exec_get_related_topics,
            _exec_get_topic_details,
            _exec_list_channels,
            _exec_list_topics,
        )

        user = await _bot_user(who)
        everything = await _exec_list_topics({"limit": 100}, current_user=user)
        assert LIVE_TOPIC in assert_no_dead(everything)
        assert_no_dead(await _exec_list_topics({"channel_id": DEAD}, current_user=user))
        for result in (
            await _exec_get_topic_details({"topic_id": DEAD_TOPIC}, current_user=user),
            await _exec_get_document({"source_ref": DEAD_REF}, current_user=user),
        ):
            assert MARK not in _text(result)
        assert_no_dead(await _exec_get_related_topics({"topic_id": LIVE_TOPIC}, current_user=user))
        from_dead = await _exec_get_related_topics({"topic_id": DEAD_TOPIC}, current_user=user)
        assert LIVE_TOPIC not in _text(from_dead), "a deleted topic must not expose its links"
        for result in (
            await _exec_get_cross_channel_stats({}, current_user=user),
            await _exec_list_channels({}, current_user=user),
        ):
            assert DEAD not in _text(result)

    @pytest.mark.parametrize("level", ["raw", "processed", "full"])
    async def test_export_is_refused(self, world, who, level):
        from tg_parser.bot.tools import _exec_export_channel

        export_patch, _trigger_patch = _forbid_dispatch()
        with export_patch:
            result = await _exec_export_channel(
                {"channel_id": DEAD, "level": level}, current_user=await _bot_user(who)
            )
        assert "No access" in _text(result)

    @pytest.mark.parametrize(
        "args", [{"dry_run": True}, {}, {"confirm": True}], ids=["dry_run", "preview", "run"]
    )
    async def test_force_resummarize_is_refused(self, world, who, args):
        from tg_parser.bot.tools import _exec_force_resummarize

        boom = AsyncMock(side_effect=AssertionError("resummarize reached a deleted topic"))
        with patch(
            "tg_parser.services.resummarization_service.ResummarizationService.resummarize_topic",
            boom,
        ):
            result = await _exec_force_resummarize(
                {"topic_id": DEAD_TOPIC, **args}, current_user=await _bot_user(who)
            )
        assert "error" in result
        assert "preview" not in result and "dry_run" not in result
        assert MARK not in _text(result)

    async def test_trigger_pipeline_is_refused(self, world, who):
        from tg_parser.bot.tools import _exec_trigger_pipeline

        _export_patch, trigger_patch = _forbid_dispatch()
        with trigger_patch:
            result = await _exec_trigger_pipeline(
                {"channel_id": DEAD}, current_user=await _bot_user(who)
            )
        assert "No access" in _text(result)


@pytest.mark.parametrize("who", WHO)
class TestHttpSurfaces:
    async def test_reads_and_mutations(self, world, who):
        from tg_parser.api.auth import resolve_current_user
        from tg_parser.api.main import create_app

        user = await _bot_user(who)
        app = create_app()
        app.dependency_overrides[resolve_current_user] = lambda: user
        export_patch, trigger_patch = _forbid_dispatch()
        with export_patch, trigger_patch:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                topics = await c.get("/api/v1/topics")
                topics_dead = await c.get(f"/api/v1/topics?channel_id={DEAD}")
                topic = await c.get(f"/api/v1/topics/{DEAD_TOPIC}")
                document = await c.get(f"/api/v1/documents?source_ref={DEAD_REF}")
                stats = await c.get(f"/api/v1/channels/{DEAD}/stats")
                channels = await c.get("/api/v1/channels")
                me = await c.get("/api/v1/users/me")
                exports = [
                    await c.post("/api/v1/export", json={"channel_id": DEAD, "level": level})
                    for level in ("raw", "processed", "full")
                ]
                trigger = await c.post("/api/v1/pipeline/trigger", json={"channel_id": DEAD})

        assert topics.status_code == 200
        assert LIVE_TOPIC in assert_no_dead(topics.text)
        assert_no_dead(topics_dead.text)
        for response in (topic, document, stats):
            assert response.status_code in (403, 404), response.text
            assert MARK not in response.text
        assert DEAD not in channels.text
        assert DEAD not in me.text
        for response in (*exports, trigger):
            assert response.status_code == 403, response.text


# ---------------------------------------------------------------------------
# Pipeline internals: Phase 2 catalog, both linkings, digest, watchlist
# ---------------------------------------------------------------------------


class TestPipeline:
    async def test_phase2_catalog_excludes_deleted(self, world):
        from tg_parser.services.topicization_service import _load_cross_channel_topics

        session = world["db"].processing_storage_session()
        try:
            catalog = await _load_cross_channel_topics(OTHER, SATopicCardRepo(session))
        finally:
            await session.close()
        ids = {t["id"] for t in catalog or []}
        assert ids == {LIVE_TOPIC}

    async def test_full_relink_creates_no_link_to_deleted(self, world):
        from tg_parser.services.topic_linking_service import link_topics

        await link_topics(threshold=0.0)
        session = world["db"].processing_storage_session()
        try:
            links = await SATopicLinkRepo(session).list_all()
        finally:
            await session.close()
        assert links, "sanity: live topics must still link"
        assert_no_dead(links)

    async def test_incremental_linking_skips_deleted(self, world):
        from tg_parser.services.topicization_service import _run_cross_channel_linking

        await _run_cross_channel_linking(OTHER, {OTHER_TOPIC}, threshold=0.0)
        session = world["db"].processing_storage_session()
        try:
            linked = await SATopicLinkRepo(session).get_by_topic_id(OTHER_TOPIC)
        finally:
            await session.close()
        assert linked, "sanity: the live pair must link"
        assert_no_dead(linked)

    async def test_topic_card_reads_for_digest_and_resummarize(self, world):
        session = world["db"].processing_storage_session()
        try:
            cards = SATopicCardRepo(session)
            visible = await cards.list_all_except_deleted()
            changed = await cards.list_topics_changed_since(cursor=None, channel_ids=[LIVE, DEAD])
            candidates = await cards.list_resummarize_candidates(threshold=1)
            everything = await cards.list_all()
        finally:
            await session.close()
        assert {c.id for c in visible} == {LIVE_TOPIC, OTHER_TOPIC}
        assert {c.id for c in changed} == {LIVE_TOPIC}
        assert {c.id for c in candidates} == {LIVE_TOPIC, OTHER_TOPIC}
        assert DEAD_TOPIC in {c.id for c in everything}, "list_all stays unfiltered"

    async def test_deleted_means_deleted_row_and_no_live_row(self, world):
        """``channel_id`` is not unique: a live row wins over a deleted one, and a
        channel with no ``sources`` row at all is not treated as deleted."""
        unregistered = "bug107_unregistered"
        session = world["db"].ingestion_state_session()
        try:
            state = SAIngestionStateRepo(session)
            twin = _source(DEAD, world["owner"])
            twin.source_id = "bug107_dead_twin"
            await state.upsert_source(twin)
        finally:
            await session.close()

        psession = world["db"].processing_storage_session()
        try:
            cards = SATopicCardRepo(psession)
            await cards.upsert(_card(unregistered))
            visible = {c.id for c in await cards.list_all_except_deleted()}
            dead_docs = await SAProcessedDocumentRepo(psession).list_by_channel(
                DEAD, exclude_deleted_channel=True
            )
        finally:
            await psession.close()
        assert {DEAD_TOPIC, _topic(unregistered)} <= visible
        assert [d.source_ref for d in dead_docs] == [DEAD_REF]

    async def test_channel_scope_is_exact_not_like_wildcard(self, world):
        """``_`` in a channel id is a LIKE wildcard: scope ``bug107_live`` used to
        match a card of ``bug107Xlive`` too. Admin now reads through the same
        scoped path, so the match must be exact."""
        lookalike = "bug107Xlive"
        session = world["db"].processing_storage_session()
        try:
            cards = SATopicCardRepo(session)
            await cards.upsert(_card(lookalike))
            scoped = {c.id for c in await cards.list_by_channels([LIVE])}
            single = {c.id for c in await cards.list_by_channel(LIVE)}
            changed = {
                c.id for c in await cards.list_topics_changed_since(cursor=None, channel_ids=[LIVE])
            }
            candidates = {c.id for c in await cards.list_resummarize_candidates(LIVE, threshold=1)}
        finally:
            await session.close()
        for ids in (scoped, single, changed, candidates):
            assert ids == {LIVE_TOPIC}

    async def test_channel_digest_skips_deleted_channel(self, world):
        from tg_parser.services.digest_service import DigestService

        sub = DigestSubscription(
            id="00000000-0000-4000-8000-000000000107",
            owner_id=world["owner"],
            chat_id=107,
            name="bug107",
            channel_ids=[LIVE, DEAD],
        )
        session = world["db"].processing_storage_session()
        try:
            service = DigestService(
                processed_repo=SAProcessedDocumentRepo(session),
                subscription_repo=AsyncMock(),
                prompt_loader=None,
                llm_client_factory=None,
            )
            with patch.object(service, "_call_llm", AsyncMock(return_value="body")) as llm:
                result = await service.generate(sub)
        finally:
            await session.close()
        assert result.per_channel_counts == {LIVE: 1, DEAD: 0}
        assert MARK not in llm.await_args.kwargs["channels_block"]

    async def test_watchlist_backfill_and_calibration_skip_deleted_channel(self, world):
        from tg_parser.services.watchlist_service import WatchlistService

        interest = WatchInterest(
            id="00000000-0000-4000-8000-000000000108",
            user_id=world["owner"],
            chat_id=107,
            title="bug107",
            description=QUERY,
            keywords=[QUERY],
            exclude_keywords=[],
            channel_ids=[LIVE, DEAD],
            threshold=0.0,
            notify_mode=NotifyMode.INSTANT,
            is_active=True,
            embedding=VEC,
        )
        interest_repo = AsyncMock()
        interest_repo.get.return_value = interest
        session = world["db"].processing_storage_session()
        try:
            service = WatchlistService(
                interest_repo=interest_repo,
                match_repo=AsyncMock(),
                processed_doc_repo=SAProcessedDocumentRepo(session),
                embedding_repo=SAEmbeddingRepo(session),
                embedding_client=None,
            )
            backfill = await service.backfill_interest(interest.id, dry_run=True)
            _scores, corpus, _max = await service._collect_corpus_combined_scores(interest)
        finally:
            await session.close()
        assert backfill.scored_docs == 1
        assert corpus == 1

    async def test_stored_watch_matches_are_neither_listed_nor_delivered(self, world):
        from tg_parser.mcp_server import get_watchlist_matches
        from tg_parser.storage.sqlalchemy.watch_interest_repo import SAWatchInterestRepo
        from tg_parser.storage.sqlalchemy.watch_match_repo import SAWatchMatchRepo

        session = world["db"].ingestion_state_session()
        try:
            interest = await SAWatchInterestRepo(session).create(
                WatchInterest(
                    id="00000000-0000-4000-8000-000000000109",
                    user_id=world["owner"],
                    chat_id=107,
                    title="bug107 matches",
                    keywords=[QUERY],
                    exclude_keywords=[],
                    channel_ids=[LIVE, DEAD],
                    threshold=0.1,
                    notify_mode=NotifyMode.INSTANT,
                    is_active=True,
                )
            )
            matches = SAWatchMatchRepo(session)
            await matches.upsert_many(
                [
                    WatchMatch(
                        id=0,
                        interest_id=interest.id,
                        source_ref=_ref(channel_id),
                        channel_id=channel_id,
                        keyword_score=1.0,
                        semantic_score=1.0,
                        combined_score=1.0,
                    )
                    for channel_id in (LIVE, DEAD)
                ]
            )
            history = await matches.list_for_interest(interest.id)
            pending = await matches.list_unnotified_for_interests([interest.id])
            backlog = await matches.count_unnotified_for_interests([interest.id])
        finally:
            await session.close()

        assert [m.source_ref for m in history] == [LIVE_REF]
        assert [m.source_ref for m in pending] == [LIVE_REF]
        assert backlog == 1
        with _as_mcp(world, "owner"):
            listed = await get_watchlist_matches(interest_id=interest.id)
        assert LIVE_REF in assert_no_dead(listed)


# ---------------------------------------------------------------------------
# Restore path, limit on restore, repeated remove
# ---------------------------------------------------------------------------


class TestRestore:
    async def test_readding_restores_visibility(self, world):
        from tg_parser.mcp_server import add_channel, search_knowledge_base

        with _as_mcp(world, "owner"):
            added = await add_channel(channel_id=DEAD)
            results = await search_knowledge_base(query=QUERY, mode="keyword", limit=20)
        assert added.status == "active"
        assert "restored" in added.message
        assert DEAD_REF in _text(results)

    async def test_restore_counts_toward_limit_mcp_and_bot(self, world):
        from tg_parser.bot.tools import _exec_add_channel
        from tg_parser.mcp_server import add_channel

        session = world["db"].ingestion_state_session()
        try:
            await SAUserRepo(session).update_user(world["owner"], max_channels=1)
        finally:
            await session.close()
        clear_cache()

        with _as_mcp(world, "owner"):
            mcp_result = await add_channel(channel_id=DEAD)
        bot_result = await _exec_add_channel(
            {"channel_id": DEAD, "confirm": True}, current_user=await _bot_user("owner")
        )
        assert mcp_result.status == "rejected"
        assert "Channel limit reached" in mcp_result.message
        assert "Channel limit reached" in bot_result["message"]

        session = world["db"].ingestion_state_session()
        try:
            assert await SAUserRepo(session).get_owned_channel_ids(world["owner"]) == [LIVE]
        finally:
            await session.close()

    @pytest.mark.parametrize("who", WHO)
    async def test_repeated_remove_says_not_found(self, world, who):
        from tg_parser.bot.tools import _exec_remove_channel
        from tg_parser.mcp_server import remove_channel

        with _as_mcp(world, who):
            mcp_result = await remove_channel(channel_id=DEAD, confirm=True)
        bot_result = await _exec_remove_channel(
            {"channel_id": DEAD, "confirm": True}, current_user=await _bot_user(who)
        )
        assert mcp_result.removed is False
        assert "not found" in mcp_result.message
        assert bot_result["removed"] is False
        assert "not found" in bot_result["message"]
