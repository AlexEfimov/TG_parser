"""F5-C #15 item #3 — F6 topic-scoped digest (ADR-0019) test suite.

Pure-logic tests (mock repos, no Postgres) cover the topic-mode content
selection + payload composition + cursor semantics inside ``DigestService``.
Postgres-gated tests (``TEST_POSTGRES=1``) cover the ``mode`` / ``topic_ids``
schema round-trip and the ``list_topics_changed_since`` read-path.
"""

from __future__ import annotations

import os
import uuid as _uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_parser.domain.models import (
    Anchor,
    DigestFormat,
    DigestMode,
    DigestSubscription,
    MessageType,
    TopicCard,
    TopicCardVersion,
    TopicType,
)
from tg_parser.processing.prompt_loader import PromptLoader
from tg_parser.services.digest_service import DigestService

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"

pg_only = pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES"),
    reason="PostgreSQL tests disabled (set TEST_POSTGRES=1)",
)


# ============================================================================
# Fixtures / fakes
# ============================================================================


_DEFAULT_LSA = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)


def _make_card(
    topic_id: str = "topic:t1",
    *,
    title: str = "Topic One",
    summary: str = "current summary",
    scope_in: list[str] | None = None,
    scope_out: list[str] | None = None,
    sources: list[str] | None = None,
    last_summarized_at: datetime | None = _DEFAULT_LSA,
    summary_version: int = 2,
) -> TopicCard:
    return TopicCard(
        id=topic_id,
        title=title,
        summary=summary,
        scope_in=scope_in or ["in-a"],
        scope_out=scope_out or ["out-a"],
        type=TopicType.SINGLETON,
        anchors=[
            Anchor(
                channel_id=(sources or ["ch1"])[0],
                message_id="1",
                message_type=MessageType.POST,
                anchor_ref=f"tg:{(sources or ['ch1'])[0]}:post:1",
            )
        ],
        sources=sources or ["ch1"],
        updated_at=datetime(2026, 7, 24, 10, 0, tzinfo=UTC),
        last_summarized_at=last_summarized_at,
        summary_version=summary_version,
    )


def _make_version(
    topic_id: str = "topic:t1",
    *,
    version_no: int = 1,
    summary: str = "old summary",
    scope_in: list[str] | None = None,
    scope_out: list[str] | None = None,
    created_at: datetime | None = None,
) -> TopicCardVersion:
    return TopicCardVersion(
        id=version_no,
        topic_id=topic_id,
        version_no=version_no,
        summary=summary,
        scope_in=scope_in or ["in-a"],
        scope_out=scope_out or ["out-a"],
        supporting_items_count_at_time=1,
        created_at=created_at or datetime(2026, 7, 24, 8, 0, tzinfo=UTC),
    )


class _FakeTopicCardRepo:
    def __init__(self, changed: list[TopicCard]):
        self._changed = changed
        self.calls: list[dict] = []

    async def list_topics_changed_since(
        self,
        *,
        cursor: datetime | None,
        channel_ids: list[str] | None = None,
        topic_ids: list[str] | None = None,
    ) -> list[TopicCard]:
        self.calls.append(
            {"cursor": cursor, "channel_ids": channel_ids, "topic_ids": topic_ids}
        )
        return list(self._changed)


class _FakeVersionRepo:
    def __init__(self, versions_by_topic: dict[str, list[TopicCardVersion]]):
        self._versions = versions_by_topic

    async def list_by_topic(self, topic_id: str, limit: int = 50) -> list[TopicCardVersion]:
        # newest-first (created_at DESC), mirrors the SA repo ordering.
        rows = sorted(
            self._versions.get(topic_id, []),
            key=lambda v: (v.created_at, v.version_no),
            reverse=True,
        )
        return rows[:limit]


class _FakeLLM:
    def __init__(self, response: str = "## digest body"):
        self.response = response
        self.calls: list[dict] = []

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> str:
        self.calls.append({"prompt": prompt, "system_prompt": system_prompt})
        return self.response


def _make_topic_sub(
    *,
    channel_ids: list[str] | None = None,
    topic_ids: list[str] | None = None,
    last_digest_cursor: datetime | None = None,
) -> DigestSubscription:
    return DigestSubscription(
        id=str(_uuid.uuid4()),
        owner_id="00000000-0000-0000-0000-0000000000bb",
        chat_id=123,
        name="topic brief",
        channel_ids=channel_ids or ["ch1"],
        mode=DigestMode.TOPIC,
        topic_ids=topic_ids,
        format=DigestFormat.SUMMARY,
        language="ru",
        last_digest_cursor=last_digest_cursor,
    )


def _make_topic_service(
    *,
    changed: list[TopicCard],
    versions_by_topic: dict[str, list[TopicCardVersion]] | None = None,
    llm_response: str = "## digest body",
) -> tuple[DigestService, _FakeTopicCardRepo, _FakeVersionRepo, _FakeLLM, AsyncMock]:
    card_repo = _FakeTopicCardRepo(changed)
    version_repo = _FakeVersionRepo(versions_by_topic or {})
    llm = _FakeLLM(llm_response)
    sub_repo = MagicMock()
    sub_repo.update = AsyncMock()
    loader = PromptLoader(prompts_dir=PROMPTS_DIR)
    factory: Callable = lambda: llm  # noqa: E731
    service = DigestService(
        processed_repo=None,
        subscription_repo=sub_repo,
        prompt_loader=loader,
        llm_client_factory=factory,
        topic_card_repo=card_repo,
        topic_version_repo=version_repo,
    )
    return service, card_repo, version_repo, llm, sub_repo.update


# ============================================================================
# Model validation
# ============================================================================


def test_channel_mode_rejects_topic_ids():
    with pytest.raises(ValueError, match="topic_ids is only valid"):
        DigestSubscription(
            id="x",
            owner_id="o",
            chat_id=1,
            name="n",
            channel_ids=["ch1"],
            mode=DigestMode.CHANNEL,
            topic_ids=["topic:1"],
        )


def test_topic_mode_allows_empty_topic_ids():
    sub = DigestSubscription(
        id="x", owner_id="o", chat_id=1, name="n", channel_ids=["ch1"], mode=DigestMode.TOPIC
    )
    assert sub.mode == DigestMode.TOPIC
    assert sub.topic_ids is None


# ============================================================================
# _generate_topic — happy path + diff reuse
# ============================================================================


@pytest.mark.asyncio
async def test_generate_topic_happy_diff_reuse():
    cursor = datetime(2026, 7, 24, 6, 0, tzinfo=UTC)
    card = _make_card(summary="new text", last_summarized_at=datetime(2026, 7, 24, 9, 0, tzinfo=UTC))
    # prior version live at cursor: created_at <= cursor.
    prior = _make_version(
        version_no=1, summary="old text", created_at=datetime(2026, 7, 24, 5, 0, tzinfo=UTC)
    )
    service, card_repo, _vr, llm, _upd = _make_topic_service(
        changed=[card], versions_by_topic={"topic:t1": [prior]}
    )
    sub = _make_topic_sub(topic_ids=["topic:t1"], last_digest_cursor=cursor)

    result = await service.generate(sub)

    assert not result.skipped
    assert result.docs_count == 1
    # scope = explicit topic_ids, cursor = strict last_digest_cursor.
    assert card_repo.calls[0]["topic_ids"] == ["topic:t1"]
    assert card_repo.calls[0]["channel_ids"] is None
    assert card_repo.calls[0]["cursor"] == cursor
    # cursor advances to the topic's last_summarized_at.
    assert result.new_cursor == datetime(2026, 7, 24, 9, 0, tzinfo=UTC)
    # LLM prompt carried the rendered diff (old → new).
    assert llm.calls, "LLM should have been called"
    body = llm.calls[0]["prompt"]
    assert "Topic One" in body
    assert "new text" in body


@pytest.mark.asyncio
async def test_generate_topic_empty_skips_and_advances():
    service, _cr, _vr, llm, _upd = _make_topic_service(changed=[])
    sub = _make_topic_sub(
        topic_ids=["topic:t1"], last_digest_cursor=datetime(2026, 7, 24, 6, 0, tzinfo=UTC)
    )

    result = await service.generate(sub)

    assert result.skipped
    assert result.docs_count == 0
    assert not llm.calls
    # non-first-run empty → cursor unchanged (kept).
    assert result.new_cursor == datetime(2026, 7, 24, 6, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_generate_topic_cumulative_prior_picks_newest_at_or_before_cursor():
    cursor = datetime(2026, 7, 24, 7, 0, tzinfo=UTC)
    card = _make_card(summary="v3 text", summary_version=3)
    v1 = _make_version(
        version_no=1, summary="v1 text", created_at=datetime(2026, 7, 24, 5, 0, tzinfo=UTC)
    )
    v2 = _make_version(
        version_no=2, summary="v2 text", created_at=datetime(2026, 7, 24, 6, 30, tzinfo=UTC)
    )
    service, _cr, _vr, llm, _upd = _make_topic_service(
        changed=[card], versions_by_topic={"topic:t1": [v1, v2]}
    )
    sub = _make_topic_sub(topic_ids=["topic:t1"], last_digest_cursor=cursor)

    await service.generate(sub)

    body = llm.calls[0]["prompt"]
    # prior = newest version with created_at <= cursor = v2.
    assert "v2 text" in body
    assert "v3 text" in body


@pytest.mark.asyncio
async def test_generate_topic_ttl_gap_fallback_never_500():
    cursor = datetime(2026, 7, 24, 7, 0, tzinfo=UTC)
    card = _make_card(summary="current text", summary_version=5)
    # All surviving versions are NEWER than the cursor (older ones purged, and
    # the oldest surviving version_no > 1 → real retention gap).
    v3 = _make_version(
        version_no=3, summary="v3 text", created_at=datetime(2026, 7, 24, 8, 0, tzinfo=UTC)
    )
    service, _cr, _vr, llm, _upd = _make_topic_service(
        changed=[card], versions_by_topic={"topic:t1": [v3]}
    )
    sub = _make_topic_sub(topic_ids=["topic:t1"], last_digest_cursor=cursor)

    result = await service.generate(sub)

    assert not result.skipped
    body = llm.calls[0]["prompt"]
    assert "baseline shifted (retention)" in body


@pytest.mark.asyncio
async def test_generate_topic_no_versions_treats_all_as_new():
    cursor = datetime(2026, 7, 24, 7, 0, tzinfo=UTC)
    card = _make_card(summary="brand new", summary_version=1)
    service, _cr, _vr, llm, _upd = _make_topic_service(
        changed=[card], versions_by_topic={}
    )
    sub = _make_topic_sub(topic_ids=["topic:t1"], last_digest_cursor=cursor)

    result = await service.generate(sub)

    assert not result.skipped
    body = llm.calls[0]["prompt"]
    assert "baseline shifted (genesis)" in body
    assert "brand new" in body


@pytest.mark.asyncio
async def test_generate_topic_m4_visibility_drops_out_of_scope():
    cursor = datetime(2026, 7, 24, 7, 0, tzinfo=UTC)
    # topic sources = ch9, but the subscription scope is ch1 → dropped.
    card = _make_card(sources=["ch9"])
    prior = _make_version(created_at=datetime(2026, 7, 24, 5, 0, tzinfo=UTC))
    service, _cr, _vr, llm, _upd = _make_topic_service(
        changed=[card], versions_by_topic={"topic:t1": [prior]}
    )
    sub = _make_topic_sub(channel_ids=["ch1"], topic_ids=["topic:t1"], last_digest_cursor=cursor)

    result = await service.generate(sub)

    assert result.skipped
    assert not llm.calls


@pytest.mark.asyncio
async def test_generate_topic_first_run_uses_lookback():
    card = _make_card(last_summarized_at=datetime.now(UTC) - timedelta(hours=1))
    prior = _make_version(created_at=datetime.now(UTC) - timedelta(hours=48))
    service, card_repo, _vr, _llm, _upd = _make_topic_service(
        changed=[card], versions_by_topic={"topic:t1": [prior]}
    )
    sub = _make_topic_sub(topic_ids=["topic:t1"], last_digest_cursor=None)

    await service.generate(sub)

    # first run → selection cursor is a lookback timestamp (not None).
    assert card_repo.calls[0]["cursor"] is not None


# ============================================================================
# subscribe() — mode-change resets cursor (M3)
# ============================================================================


@pytest.mark.asyncio
async def test_subscribe_mode_change_resets_cursor():
    existing = DigestSubscription(
        id="sub-1",
        owner_id="o",
        chat_id=1,
        name="brief",
        channel_ids=["ch1"],
        mode=DigestMode.CHANNEL,
        last_digest_cursor=datetime(2026, 7, 20, 9, 0, tzinfo=UTC),
    )
    sub_repo = MagicMock()
    sub_repo.find_by_owner_and_name = AsyncMock(return_value=existing)
    sub_repo.update = AsyncMock(return_value=existing)
    service = DigestService(
        processed_repo=None,
        subscription_repo=sub_repo,
        prompt_loader=None,
        llm_client_factory=None,
    )

    from tg_parser.domain.models import TargetChat

    result = await service.subscribe(
        owner_id="o",
        name="brief",
        channel_ids=["ch1"],
        target=TargetChat(chat_id=1),
        mode=DigestMode.TOPIC,
        topic_ids=["topic:t1"],
    )

    assert not result.created
    assert "mode" in result.changed_fields
    _, kwargs = sub_repo.update.call_args
    assert kwargs.get("reset_cursor") is True
    assert kwargs.get("mode") == DigestMode.TOPIC


@pytest.mark.asyncio
async def test_subscribe_topic_ids_change_resets_cursor():
    existing = DigestSubscription(
        id="sub-1",
        owner_id="o",
        chat_id=1,
        name="brief",
        channel_ids=["ch1"],
        mode=DigestMode.TOPIC,
        topic_ids=["topic:a"],
        last_digest_cursor=datetime(2026, 7, 20, 9, 0, tzinfo=UTC),
    )
    sub_repo = MagicMock()
    sub_repo.find_by_owner_and_name = AsyncMock(return_value=existing)
    sub_repo.update = AsyncMock(return_value=existing)
    service = DigestService(
        processed_repo=None,
        subscription_repo=sub_repo,
        prompt_loader=None,
        llm_client_factory=None,
    )

    from tg_parser.domain.models import TargetChat

    # Same mode, different topic set → cursor must still reset so a newly-added
    # topic with last_summarized_at <= cursor is not silently skipped.
    result = await service.subscribe(
        owner_id="o",
        name="brief",
        channel_ids=["ch1"],
        target=TargetChat(chat_id=1),
        mode=DigestMode.TOPIC,
        topic_ids=["topic:a", "topic:b"],
    )

    assert not result.created
    assert "topic_ids" in result.changed_fields
    assert "mode" not in result.changed_fields
    _, kwargs = sub_repo.update.call_args
    assert kwargs.get("reset_cursor") is True
    assert kwargs.get("topic_ids") == ["topic:a", "topic:b"]


# ============================================================================
# list_topics_changed_since read-path (Postgres)
# ============================================================================


@pg_only
class TestListTopicsChangedSince:
    @pytest.fixture
    async def _topic_db(self, test_db):
        session = test_db.processing_storage_session()
        try:
            from sqlalchemy import text

            await session.execute(text("DELETE FROM topic_cards"))
            await session.commit()
        finally:
            await session.close()
        return test_db

    @pytest.fixture
    async def card_repo(self, _topic_db):
        from tg_parser.storage.sqlalchemy.topic_card_repo import SATopicCardRepo

        session = _topic_db.processing_storage_session()
        try:
            yield SATopicCardRepo(session)
        finally:
            await session.close()

    async def _seed(self, card_repo, card: TopicCard):
        await card_repo.upsert(card)

    @pytest.mark.asyncio
    async def test_strict_gt_and_null_excluded(self, card_repo):
        cursor = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)
        changed = _make_card(
            "topic:changed", last_summarized_at=datetime(2026, 7, 24, 9, 0, tzinfo=UTC)
        )
        at_cursor = _make_card("topic:eq", last_summarized_at=cursor)
        never = _make_card("topic:null", last_summarized_at=None, summary_version=1)
        for c in (changed, at_cursor, never):
            await self._seed(card_repo, c)

        rows = await card_repo.list_topics_changed_since(
            cursor=cursor, topic_ids=["topic:changed", "topic:eq", "topic:null"]
        )
        ids = {r.id for r in rows}
        assert ids == {"topic:changed"}  # strict > excludes eq; NULL excluded

    @pytest.mark.asyncio
    async def test_channel_scope(self, card_repo):
        cursor = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)
        in_scope = _make_card(
            "topic:in",
            sources=["ch1"],
            last_summarized_at=datetime(2026, 7, 24, 9, 0, tzinfo=UTC),
        )
        out_scope = _make_card(
            "topic:out",
            sources=["ch2"],
            last_summarized_at=datetime(2026, 7, 24, 9, 0, tzinfo=UTC),
        )
        for c in (in_scope, out_scope):
            await self._seed(card_repo, c)

        rows = await card_repo.list_topics_changed_since(cursor=cursor, channel_ids=["ch1"])
        assert {r.id for r in rows} == {"topic:in"}

    @pytest.mark.asyncio
    async def test_no_scope_returns_empty(self, card_repo):
        rows = await card_repo.list_topics_changed_since(cursor=None)
        assert rows == []


# ============================================================================
# Repo round-trip of mode / topic_ids (Postgres)
# ============================================================================


@pg_only
@pytest.mark.asyncio
async def test_subscription_repo_roundtrip_topic_fields(test_db):
    from sqlalchemy import text

    from tg_parser.storage.sqlalchemy.digest_subscription_repo import SADigestSubscriptionRepo
    from tg_parser.storage.sqlalchemy.user_repo import SAUserRepo

    session = test_db.ingestion_state_session()
    try:
        await session.execute(text("DELETE FROM digest_subscriptions"))
        await session.execute(text("DELETE FROM users"))
        await session.commit()
        user_repo = SAUserRepo(session)
        owner = await user_repo.create_user(name="owner", role="admin")

        repo = SADigestSubscriptionRepo(session)
        sub = DigestSubscription(
            id=str(_uuid.uuid4()),
            owner_id=owner.id,
            chat_id=42,
            name="topic brief",
            channel_ids=["ch1"],
            mode=DigestMode.TOPIC,
            topic_ids=["topic:a", "topic:b"],
        )
        created = await repo.create(sub)
        assert created.mode == DigestMode.TOPIC
        assert created.topic_ids == ["topic:a", "topic:b"]

        # mode-change reset path.
        updated = await repo.update(created.id, mode=DigestMode.CHANNEL, unset_topic_ids=True,
                                    reset_cursor=True)
        assert updated.mode == DigestMode.CHANNEL
        assert updated.topic_ids is None
        assert updated.last_digest_cursor is None
    finally:
        await session.close()
